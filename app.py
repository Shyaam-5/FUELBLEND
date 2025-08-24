from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
import pandas as pd
import pickle
from datetime import datetime
from werkzeug.utils import secure_filename
import numpy as np
import snowflake.connector
import joblib
from dotenv import load_dotenv
import boto3
from datetime import datetime
from io import StringIO
import json

# -------------------------
# Flask Setup
# -------------------------
app = Flask(__name__)
app.secret_key = "your_secret_key"
load_dotenv() 

# -------------------------
# Database Connection
# -------------------------
conn = snowflake.connector.connect(
    user=os.environ.get("SNOWFLAKE_USER"),
    password=os.environ.get("SNOWFLAKE_PASSWORD"),
    account=os.environ.get("SNOWFLAKE_ACCOUNT"),
    warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
    database=os.environ.get("SNOWFLAKE_DATABASE"),
    schema=os.environ.get("SNOWFLAKE_SCHEMA"),
    role=os.environ.get("SNOWFLAKE_ROLE")
)

cursor = conn.cursor() 

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_DEFAULT_REGION")
)
csv_buffer = StringIO()

pipeline = joblib.load("models/model_pipeline.pkl")


def predict_with_pipeline(pipeline, X):
    scaler = pipeline["scaler"]
    lgb_model = pipeline["lgb_model"]
    cat_model = pipeline["cat_model"]
    ridge_model = pipeline["ridge_model"]
    meta_model = pipeline["meta_model"]
    residual_model = pipeline["residual_model"]

    # Scale inputs
    X_scaled = scaler.transform(X)

    # Base model predictions
    lgb_preds = lgb_model.predict(X_scaled)
    cat_preds = cat_model.predict(X_scaled)
    ridge_preds = ridge_model.predict(X_scaled)

    # Stack predictions for meta model
    X_meta = np.concatenate([lgb_preds, cat_preds, ridge_preds], axis=1)

    # Final stacked + residual correction
    meta_preds = meta_model.predict(X_meta)
    final_preds = meta_preds + residual_model.predict(X_meta)
    return final_preds


@app.context_processor
def inject_globals():
    return {"datetime": datetime}

# -------------------------
# Load New XGBoost Model
# -------------------------
# with open("final_xgboost_model.pkl", "rb") as f:
#     trained_model = pickle.load(f)


# -------------------------
# Routes
# -------------------------

@app.route("/")
def index():
    return redirect(url_for("login"))

# -------------------------
# Registration
# -------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        existing = cursor.fetchone()
        if existing:
            flash("Username already exists, please login.", "danger")
            return redirect(url_for("login"))

        cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
        conn.commit()
        flash("Registration successful! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# -------------------------
# Login
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = cursor.fetchone()

        if user:
            session["user_id"] = user[0]
            session["username"] = user[1]
            return redirect(url_for("home"))
        else:
            flash("Invalid username or password", "danger")

    return render_template("login.html")

# -------------------------
# Logout
# -------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------------------
# Home
# -------------------------
@app.route("/home")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("home.html", username=session["username"])

# -------------------------
# Upload & Predict
# -------------------------
@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files["file"]
        test_data = pd.read_csv(file)

        # Keep IDs if present
        ids = test_data["ID"] if "ID" in test_data.columns else None
        if "ID" in test_data.columns:
            test_data = test_data.drop(columns=["ID"])

        # Run predictions using the stacked pipeline
        preds = predict_with_pipeline(pipeline, test_data)

        # Build results DataFrame
        submission = pd.DataFrame(
            preds,
            columns=[f"BlendProperty{i+1}" for i in range(preds.shape[1])]
        )
        if ids is not None:
            submission.insert(0, "ID", ids)

        # ---- Upload to S3 ----
        bucket_name = os.getenv("S3_BUCKET")
        s3_key = f"predictions/{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"

        csv_buffer = StringIO()
        submission.to_csv(csv_buffer, index=False)

        s3.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=csv_buffer.getvalue(),
            ContentType="text/csv"
        )

        s3_path = f"s3://{bucket_name}/{s3_key}"

        # ---- Store in Snowflake ----
        cursor.execute(
    """
    INSERT INTO predictions (user_id, filename, upload_time, file_path, result)
    VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
    """,
    (session["user_id"], file.filename, s3_path, submission.to_json())
)


        conn.commit()

        # Convert DataFrame to list of dicts for Jinja
        results = submission.to_dict(orient="records")

        return render_template("results.html", predictions=results, columns=submission.columns)

    return render_template("upload.html")

# -------------------------
# History
# -------------------------
@app.route("/history")
def history():
    cursor.execute("SELECT id, filename, upload_time, file_path, result FROM predictions WHERE user_id = %s", (session["user_id"],))
    rows = cursor.fetchall()

    predictions = []
    for row in rows:
        predictions.append({
            "id": row[0],
            "filename": row[1],
            # convert string to datetime
            "upload_time": row[2].strftime("%Y-%m-%d %H:%M") if hasattr(row[2], "strftime") else row[2],
            "file_path": row[3],
            "result": row[4],
        })

    return render_template("history.html", predictions=predictions)


# -------------------------
# View Results
# -------------------------
@app.route("/view/<int:prediction_id>")
def view_prediction(prediction_id):
    cursor.execute("SELECT result FROM predictions WHERE id=%s", (prediction_id,))
    row = cursor.fetchone()
    if not row:
        return "Not found", 404

    result_json = row[0]
    results = pd.DataFrame(json.loads(result_json))  # JSON → DataFrame

    return render_template(
        "results.html",
        predictions=results.to_dict(orient="records"),
        columns=results.columns
    )


# -------------------------
# Download CSV from S3
# -------------------------
@app.route("/download/<int:prediction_id>")
def download(prediction_id):
    cursor.execute("SELECT file_path FROM predictions WHERE id=%s", (prediction_id,))
    row = cursor.fetchone()
    if not row:
        flash("File not found", "danger")
        return redirect(url_for("history"))

    file_path = row[0]  # s3://bucket/.../file.csv

    # Extract bucket & key from file_path
    bucket_name = file_path.split("/")[2]
    key = "/".join(file_path.split("/")[3:])

    # Get file from S3
    file_obj = s3.get_object(Bucket=bucket_name, Key=key)
    file_content = file_obj["Body"].read()

    return (
        file_content,
        200,
        {
            "Content-Type": "text/csv",
            "Content-Disposition": f"attachment; filename={key.split('/')[-1]}"
        },
    )
# Run Flask
# -------------------------
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)