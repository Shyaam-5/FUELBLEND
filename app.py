from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
import mysql.connector
import pandas as pd
import pickle
from datetime import datetime
from werkzeug.utils import secure_filename
import numpy as np

# -------------------------
# Flask Setup
# -------------------------
app = Flask(__name__)
app.secret_key = "your_secret_key"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# -------------------------
# Database Connection
# -------------------------
conn = mysql.connector.connect(
    host="localhost",
    user="root",       # change to your MySQL username
    password="1234",   # change to your MySQL password
    database="ml_app"
)
cursor = conn.cursor()
from datetime import datetime

@app.context_processor
def inject_globals():
    return {"datetime": datetime}

# -------------------------
# Load New XGBoost Model
# -------------------------
with open("final_xgboost_model.pkl", "rb") as f:
    trained_model = pickle.load(f)


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

        # if not file:
        #     return "No file uploaded"

        test_data = pd.read_csv("./test.csv")
        
        # Keep IDs if present
        ids = test_data["ID"] if "ID" in test_data.columns else None
        if "ID" in test_data.columns:
            test_data = test_data.drop(columns=["ID"])

        # Run predictions using the new XGBoost model
        preds = trained_model.predict(test_data)

        # Build results DataFrame
        submission = pd.DataFrame(
            preds,
            columns=[f"BlendProperty{i+1}" for i in range(preds.shape[1])]
        )
        if ids is not None:
            submission.insert(0, "ID", ids)

        # Optionally save to CSV
        submission.to_csv("uploaded_submission.csv", index=False)

        # Convert DataFrame to list of dicts for Jinja
        results = submission.to_dict(orient="records")

        return render_template("results.html", predictions=results, columns=submission.columns)

    return render_template("upload.html")

# -------------------------
# History
# -------------------------
@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect(url_for("login"))

    cursor.execute(
        "SELECT filename, upload_time, result FROM predictions WHERE user_id=%s ORDER BY upload_time DESC",
        (session["user_id"],)
    )
    rows = cursor.fetchall()

    predictions = []
    for row in rows:
        predictions.append({
            "filename": row[0],
            "upload_time": row[1],
            "result": row[2]
        })

    return render_template("history.html", predictions=predictions)

# -------------------------
# Run Flask
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
