from __future__ import annotations

import io
import csv
import os
import re
import secrets
import smtplib
import sqlite3
import warnings
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_file, session, url_for)
from flask_wtf import CSRFProtect, FlaskForm
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash
from wtforms import FileField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = INSTANCE_DIR / "uploads"
DATABASE_PATH = INSTANCE_DIR / "garden_requests.sqlite3"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
SERVICES = [
    ("lawn_mowing", "Lawn mowing and grass cutting"),
    ("weed_removal", "Weed removal"),
    ("flower_beds", "Flower planting and flower-bed maintenance"),
    ("hedge_trimming", "Hedge and shrub trimming"),
    ("garden_cleaning", "Garden cleaning and waste removal"),
    ("landscaping", "Landscaping and garden improvements"),
    ("regular_maintenance", "Regular garden maintenance"),
    ("other", "Other gardening service"),
]
REQUEST_STATUSES = [
    ("new", "New"),
    ("contacted", "Contacted"),
    ("quoted", "Quote sent"),
    ("scheduled", "Scheduled"),
    ("completed", "Completed"),
    ("declined", "Declined"),
]


def create_app() -> Flask:
    app = Flask(__name__, instance_path=str(INSTANCE_DIR))
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "local-development-only-change-this-key"),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        WTF_CSRF_TIME_LIMIT=3600,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=3600,
    )
    CSRFProtect(app)

    def validate_cellphone(form, field):
        value = (field.data or "").strip()
        if not re.fullmatch(r"\+?[0-9][0-9\s().-]*", value) or not 7 <= len(re.sub(r"\D", "", value)) <= 15:
            raise ValidationError("Enter a valid cellphone number with 7 to 15 digits.")

    class RequestForm(FlaskForm):
        full_name = StringField("Full name", filters=[lambda v: v.strip() if v else v], validators=[DataRequired(), Length(2, 100)])
        cellphone = StringField("Cellphone number", filters=[lambda v: v.strip() if v else v], validators=[DataRequired(), Length(max=30), validate_cellphone])
        email = StringField("Email address", filters=[lambda v: v.strip() if v else v], validators=[DataRequired(), Email(), Length(max=254)])
        garden_location = StringField("Garden address or location", filters=[lambda v: v.strip() if v else v], validators=[DataRequired(), Length(3, 250)])
        service_required = SelectField("Service required", choices=SERVICES, validators=[DataRequired()])
        work_description = TextAreaField("Describe the work you want done", filters=[lambda v: v.strip() if v else v], validators=[DataRequired(), Length(10, 2000)])
        photo = FileField("Garden photo (optional)")
        submit = SubmitField("Send garden service request")

    class LoginForm(FlaskForm):
        password = PasswordField("Admin password", validators=[DataRequired()])
        submit = SubmitField("Sign in")

    class ChangePasswordForm(FlaskForm):
        current_password = PasswordField("Current password", validators=[DataRequired()])
        new_password = PasswordField("New password", validators=[DataRequired(), Length(min=12, max=128)])
        confirm_password = PasswordField("Confirm new password", validators=[DataRequired(), EqualTo("new_password", message="The new passwords must match.")])

    def connect_db():
        db = sqlite3.connect(DATABASE_PATH)
        db.row_factory = sqlite3.Row
        return db

    with connect_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS garden_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_code TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL, cellphone TEXT NOT NULL, email TEXT NOT NULL,
            garden_location TEXT NOT NULL, service_required TEXT NOT NULL,
            work_description TEXT NOT NULL, photo_filename TEXT,
            created_at TEXT NOT NULL)""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(garden_requests)")}
        if "status" not in columns:
            db.execute("ALTER TABLE garden_requests ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")
        if "admin_notes" not in columns:
            db.execute("ALTER TABLE garden_requests ADD COLUMN admin_notes TEXT NOT NULL DEFAULT ''")
        db.execute("""CREATE TABLE IF NOT EXISTS admin_auth (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            password_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        configured_admin_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
        if configured_admin_hash:
            db.execute(
                "INSERT OR IGNORE INTO admin_auth (id, password_hash, updated_at) VALUES (1, ?, ?)",
                (configured_admin_hash, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )

    def send_request_notifications(reference, form):
        """Send basic business and customer email notices; storage never depends on mail."""
        smtp_host = os.environ.get("SMTP_HOST")
        smtp_username = os.environ.get("SMTP_USERNAME")
        smtp_password = os.environ.get("SMTP_PASSWORD")
        admin_email = os.environ.get("ADMIN_EMAIL")
        if not all((smtp_host, smtp_username, smtp_password)):
            app.logger.info("SMTP is not configured; request %s saved without email notification.", reference)
            return
        sender = os.environ.get("SMTP_FROM", smtp_username)
        service_name = dict(SERVICES).get(form.service_required.data, form.service_required.data)
        notifications = []
        if admin_email:
            admin_message = EmailMessage()
            admin_message["Subject"] = f"New garden request {reference}"
            admin_message["From"] = sender
            admin_message["To"] = admin_email
            admin_message.set_content(
                f"A new TS Prime Garden Solutions request was received.\n\nReference: {reference}\n"
                f"Name: {form.full_name.data}\nPhone: {form.cellphone.data}\nEmail: {form.email.data}\n"
                f"Location: {form.garden_location.data}\nService: {service_name}\n\n"
                f"Description:\n{form.work_description.data}\n\nSign in to the admin dashboard to review the request and its photo."
            )
            notifications.append(("admin", admin_message))

        customer_message = EmailMessage()
        customer_message["Subject"] = f"We received your garden request {reference}"
        customer_message["From"] = sender
        customer_message["To"] = form.email.data
        customer_message.set_content(
            f"Hello {form.full_name.data},\n\n"
            "Thank you for contacting TS Prime Garden Solutions. We have received your garden service request.\n\n"
            f"Reference: {reference}\nService requested: {service_name}\n\n"
            "Our team will review your enquiry and contact you using the details you provided. "
            "This email confirms receipt only; it is not a quote or booking confirmation.\n\n"
            "Kind regards,\nTS Prime Garden Solutions"
        )
        notifications.append(("customer", customer_message))
        try:
            with smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", "587")), timeout=15) as smtp:
                smtp.starttls()
                smtp.login(smtp_username, smtp_password)
                for recipient_type, message in notifications:
                    try:
                        smtp.send_message(message)
                    except Exception:
                        app.logger.exception("Could not send the %s notification for request %s.", recipient_type, reference)
        except Exception:
            app.logger.exception("Request %s was saved, but email delivery could not be completed.", reference)

    def save_image(upload):
        if not upload or not upload.filename:
            return None
        raw = upload.stream.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("The photo must be 5 MB or smaller.")
        if not raw:
            raise ValueError("The uploaded photo is empty.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as probe:
                    if probe.format not in ALLOWED_IMAGE_FORMATS:
                        raise ValueError("Upload a JPG, PNG or WebP image.")
                    probe.verify()
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > MAX_IMAGE_PIXELS:
                        raise ValueError("The image dimensions are too large.")
                    image = ImageOps.exif_transpose(image)
                    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                        rgba = image.convert("RGBA")
                        flattened = Image.new("RGB", rgba.size, "white")
                        flattened.paste(rgba, mask=rgba.getchannel("A"))
                        image = flattened
                    else:
                        image = image.convert("RGB")
                    image.thumbnail((3000, 3000))
                    filename = f"{uuid4().hex}.jpg"
                    image.save(UPLOAD_DIR / filename, "JPEG", quality=88, optimize=True)
                    return filename
        except ValueError:
            raise
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError("We couldn't read that image. Choose a valid JPG, PNG or WebP photo.")

    def admin_required():
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login", next=request.path))
        return None

    @app.get("/")
    def index():
        return render_template("home.html")

    @app.get("/services")
    def services():
        return render_template("services.html", services=SERVICES)

    @app.route("/request", methods=["GET", "POST"])
    def request_service():
        form = RequestForm()
        requested_service = request.args.get("service", "")
        if request.method == "GET" and requested_service in dict(SERVICES):
            form.service_required.data = requested_service
        if form.validate_on_submit():
            try:
                photo_filename = save_image(form.photo.data)
            except ValueError as error:
                form.photo.errors.append(str(error))
            else:
                reference = "TSP-" + secrets.token_hex(4).upper()
                try:
                    with connect_db() as db:
                        db.execute("""INSERT INTO garden_requests
                        (reference_code, full_name, cellphone, email, garden_location,
                         service_required, work_description, photo_filename, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                            reference, form.full_name.data, form.cellphone.data, form.email.data,
                            form.garden_location.data, form.service_required.data,
                            form.work_description.data, photo_filename,
                            datetime.now(timezone.utc).isoformat(timespec="seconds")))
                except sqlite3.Error:
                    app.logger.exception("Could not save a garden service request.")
                    if photo_filename:
                        (UPLOAD_DIR / photo_filename).unlink(missing_ok=True)
                    return render_template("request_form.html", form=form, database_error=True), 500
                send_request_notifications(reference, form)
                return redirect(url_for("success", reference=reference))
        return render_template("request_form.html", form=form), 400 if request.method == "POST" else 200

    @app.get("/success")
    def success():
        reference = request.args.get("reference", "")
        if not re.fullmatch(r"TSP-[A-F0-9]{8}", reference):
            abort(404)
        return render_template("success.html", reference=reference)

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if session.get("admin_authenticated"):
            return redirect(url_for("admin_dashboard"))
        form = LoginForm()
        if form.validate_on_submit():
            with connect_db() as db:
                admin_account = db.execute("SELECT password_hash FROM admin_auth WHERE id = 1").fetchone()
            password_hash = admin_account["password_hash"] if admin_account else ""
            if password_hash and check_password_hash(password_hash, form.password.data):
                session.clear()
                session.permanent = True
                session["admin_authenticated"] = True
                return redirect(url_for("admin_dashboard"))
            flash("The password was not accepted.", "error")
        return render_template("admin_login.html", form=form)

    @app.route("/admin/change-password", methods=["POST"])
    def admin_change_password():
        denied = admin_required()
        if denied:
            return denied
        form = ChangePasswordForm()
        if form.validate_on_submit():
            with connect_db() as db:
                admin_account = db.execute("SELECT password_hash FROM admin_auth WHERE id = 1").fetchone()
                if not admin_account or not check_password_hash(admin_account["password_hash"], form.current_password.data):
                    flash("The current password was not accepted.", "error")
                    return redirect(url_for("admin_dashboard"))
                db.execute(
                    "UPDATE admin_auth SET password_hash = ?, updated_at = ? WHERE id = 1",
                    (generate_password_hash(form.new_password.data), datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
            session.clear()
            flash("Password changed. Sign in with your new password.", "success")
            return redirect(url_for("admin_login"))
        for field_errors in form.errors.values():
            for error_message in field_errors:
                flash(error_message, "error")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/logout")
    def admin_logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("admin_login"))

    @app.get("/admin")
    def admin_dashboard():
        denied = admin_required()
        if denied:
            return denied
        search = request.args.get("q", "").strip()[:120]
        status_filter = request.args.get("status", "").strip()
        if status_filter not in dict(REQUEST_STATUSES):
            status_filter = ""
        where, parameters = [], []
        if status_filter:
            where.append("status = ?")
            parameters.append(status_filter)
        if search:
            where.append("(reference_code LIKE ? OR full_name LIKE ? OR cellphone LIKE ? OR email LIKE ? OR garden_location LIKE ? OR work_description LIKE ?)")
            parameters.extend([f"%{search}%"] * 6)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        with connect_db() as db:
            rows = db.execute(f"SELECT * FROM garden_requests{where_sql} ORDER BY created_at DESC LIMIT 500", parameters).fetchall()
            counts = {row["status"]: row["amount"] for row in db.execute("SELECT status, COUNT(*) AS amount FROM garden_requests GROUP BY status")}
            total = db.execute("SELECT COUNT(*) FROM garden_requests").fetchone()[0]
        return render_template(
            "admin_dashboard.html", requests=rows, service_names=dict(SERVICES),
            status_names=dict(REQUEST_STATUSES), status_choices=REQUEST_STATUSES,
            counts=counts, total=total, search=search, status_filter=status_filter,
            password_form=ChangePasswordForm(),
        )

    @app.post("/admin/request/<int:request_id>/update")
    def admin_update_request(request_id):
        denied = admin_required()
        if denied:
            return denied
        new_status = request.form.get("status", "")
        notes = request.form.get("admin_notes", "").strip()
        if new_status not in dict(REQUEST_STATUSES):
            flash("Choose a valid request status.", "error")
        elif len(notes) > 2000:
            flash("Admin notes must be 2,000 characters or fewer.", "error")
        else:
            with connect_db() as db:
                result = db.execute(
                    "UPDATE garden_requests SET status = ?, admin_notes = ? WHERE id = ?",
                    (new_status, notes, request_id),
                )
            if result.rowcount:
                flash("Request updated.", "success")
            else:
                abort(404)
        search = request.args.get("q", "")[:120]
        status_filter = request.args.get("status", "")
        return redirect(url_for("admin_dashboard", q=search, status=status_filter))

    @app.get("/admin/export.csv")
    def admin_export():
        denied = admin_required()
        if denied:
            return denied
        search = request.args.get("q", "").strip()[:120]
        status_filter = request.args.get("status", "").strip()
        if status_filter not in dict(REQUEST_STATUSES):
            status_filter = ""
        where, parameters = [], []
        if status_filter:
            where.append("status = ?")
            parameters.append(status_filter)
        if search:
            where.append("(reference_code LIKE ? OR full_name LIKE ? OR cellphone LIKE ? OR email LIKE ? OR garden_location LIKE ? OR work_description LIKE ?)")
            parameters.extend([f"%{search}%"] * 6)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        with connect_db() as db:
            rows = db.execute(f"SELECT * FROM garden_requests{where_sql} ORDER BY created_at DESC", parameters).fetchall()

        def safe_csv_cell(value):
            cell = "" if value is None else str(value)
            if cell.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
                cell = "'" + cell
            return cell

        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Reference", "Submitted (UTC)", "Status", "Customer", "Phone", "Email", "Location", "Service", "Description", "Admin notes"])
        service_names = dict(SERVICES)
        status_names = dict(REQUEST_STATUSES)
        for row in rows:
            writer.writerow([safe_csv_cell(value) for value in (
                row["reference_code"], row["created_at"], status_names.get(row["status"], row["status"]),
                row["full_name"], row["cellphone"], row["email"], row["garden_location"],
                service_names.get(row["service_required"], row["service_required"]),
                row["work_description"], row["admin_notes"],
            )])
        response = app.response_class("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = f"attachment; filename=ts-prime-requests-{date.today().isoformat()}.csv"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/admin/photo/<int:request_id>")
    def admin_photo(request_id):
        denied = admin_required()
        if denied:
            return denied
        with connect_db() as db:
            row = db.execute("SELECT photo_filename FROM garden_requests WHERE id=?", (request_id,)).fetchone()
        if not row or not row["photo_filename"]:
            abort(404)
        path = (UPLOAD_DIR / row["photo_filename"]).resolve()
        if path.parent != UPLOAD_DIR.resolve() or not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/jpeg", as_attachment=False, download_name="garden-photo.jpg")

    @app.errorhandler(413)
    def request_too_large(_error):
        return render_template("too_large.html"), 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG", "").lower() == "1")
