import os
import json
import pandas as pd
import numpy as np
import snowflake.connector
import joblib
import boto3
from datetime import datetime
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# -------------------------
# Configuration and Setup
# -------------------------

# Load environment variables from a .env file for local development
load_dotenv()

# Initialize the Flask application
application = Flask(__name__)

# IMPORTANT: Load the secret key from an environment variable for session security
application.secret_key = os.environ.get("SECRET_KEY")

# Check if the secret key is set, exit if not in a production environment
if not application.secret_key:
    print("FATAL ERROR: SECRET_KEY environment variable is not set.")
    # In a real app, you might want to exit or raise an exception
    # For now, we'll set a default for local dev, but this is NOT secure for production
    application.secret_key = "default-dev-key-is-not-secure"

# -------------------------
# Service Clients & Model Loading
# -------------------------

# Boto3 S3 client can be initialized once as it's thread-safe
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_DEFAULT_REGION")
)

# Load the machine learning pipeline once at startup
try:
    pipeline = joblib.load("models/model_pipeline.pkl")
except FileNotFoundError:
    print("FATAL ERROR: Model file 'models/model_pipeline.pkl' not found.")
    pipeline = None # Or exit

# -------------------------
# Helper Functions
# -------------------------

def get_db_connection():
    """Creates and returns a new Snowflake connection. Manages connections per request."""
    try:
        conn = snowflake.connector.connect(
            user=os.environ.get("SNOWFLAKE_USER"),
            password=os.environ.get("SNOWFLAKE_PASSWORD"),
            account=os.environ.get("SNOWFLAKE_ACCOUNT"),
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
            database=os.environ.get("SNOWFLAKE_DATABASE"),
            schema=os.environ.get("SNOWFLAKE_SCHEMA"),
            role=os.environ.get("SNOWFLAKE_ROLE")
        )
        return conn
    except Exception as e:
        # Log the error for debugging
        print(f"Database connection error: {e}")
        return None

def predict_with_pipeline(pipe, X):
    """Encapsulates the prediction logic."""
    if pipe is None:
        raise ValueError("ML Pipeline is not loaded.")
    # ... (Your prediction logic remains the same) ...
    scaler = pipe["scaler"]
    lgb_model = pipe["lgb_model"]
    cat_model = pipe["cat_model"]
    ridge_model = pipe["ridge_model"]
    meta_model = pipe["meta_model"]
    residual_model = pipe["residual_model"]

    X_scaled = scaler.transform(X)
    lgb_preds = lgb_model.predict(X_scaled)
    cat_preds = cat_model.predict(X_scaled)
    ridge_preds = ridge_model.predict(X_scaled)

    X_meta = np.concatenate([lgb_preds, cat_preds, ridge_preds], axis=1)
    
    meta_preds = meta_model.predict(X_meta)
    final_preds = meta_preds + residual_model.predict(X_meta)
    return final_preds

@application.context_processor
def inject_globals():
    """Injects variables into all templates."""
    return {"datetime": datetime}

# -------------------------
# Routes
# -------------------------

@application.route("/")
def index():
    return redirect(url_for("login"))

@application.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        if not conn:
            flash("Database connection could not be established.", "danger")
            return render_template("register.html")
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
                if cursor.fetchone():
                    flash("Username already exists. Please choose another or login.", "danger")
                    return redirect(url_for("login"))

                # Hash the password for secure storage
                hashed_password = generate_password_hash(password)
                cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_password))
                conn.commit()
                flash("Registration successful! Please login.", "success")
        except Exception as e:
            flash(f"An error occurred: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for("login"))
    return render_template("register.html")

@application.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        if not conn:
            flash("Database connection could not be established.", "danger")
            return render_template("login.html")

        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, username, password FROM users WHERE username=%s", (username,))
                user = cursor.fetchone()

                # Verify the user exists and the password hash matches
                if user and check_password_hash(user[2], password): # user[2] is the hashed password column
                    session["user_id"] = user[0]
                    session["username"] = user[1]
                    return redirect(url_for("home"))
                else:
                    flash("Invalid username or password.", "danger")
        except Exception as e:
            flash(f"An error occurred: {e}", "danger")
        finally:
            conn.close()

    return render_template("login.html")

@application.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))

@application.route("/home")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("home.html", username=session["username"])

@application.route("/upload", methods=["GET", "POST"])
def upload():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        if 'file' not in request.files or request.files['file'].filename == '':
            flash('No file selected', 'warning')
            return redirect(request.url)
        
        file = request.files["file"]
        
        # --- Prediction Logic ---
        test_data = pd.read_csv(file)
        ids = test_data.get("ID")
        if "ID" in test_data.columns:
            test_data = test_data.drop(columns=["ID"])
            
        preds = predict_with_pipeline(pipeline, test_data)
        
        submission = pd.DataFrame(preds, columns=[f"BlendProperty{i+1}" for i in range(preds.shape[1])])
        if ids is not None:
            submission.insert(0, "ID", ids)
            
        # --- S3 Upload ---
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

        # --- Snowflake Insert ---
        conn = get_db_connection()
        if not conn:
            flash("Database connection could not be established.", "danger")
            return render_template("upload.html")

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO predictions (user_id, filename, upload_time, file_path, result)
                    VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
                    """,
                    (session["user_id"], file.filename, s3_path, submission.to_json())
                )
                conn.commit()
        except Exception as e:
            flash(f"An error occurred while saving results: {e}", "danger")
        finally:
            conn.close()

        results = submission.to_dict(orient="records")
        return render_template("results.html", predictions=results, columns=submission.columns)

    return render_template("upload.html")

# Add the remaining routes (/history, /view/<id>, /download/<id>) using the same
# `conn = get_db_connection()` and `try...finally` pattern for all database interactions.


# -------------------------
# Main Execution
# -------------------------
if __name__ == "__main__":
    # This block is for local development only.
    # It is not used by production servers like Gunicorn.
    port = int(os.environ.get("PORT", 5000))
    application.run(host="0.0.0.0", port=port, debug=True)