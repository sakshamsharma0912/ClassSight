"""ClassSight: teacher cohort insights and private student performance.

Run: python app.py. No official SRM SSO connection is made by this application.
"""
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from analyzer import analyze, original_result, select_students, student_profile

from portal_core import (COMPONENTS, COURSES, CSV_FIELDS, GRADES, clean_text,
                         enrich, init_database, insert_student, integer, mark,
                         parse_csv, points, safe_cell, seed_students,
                         student_values, summarize)

BASE_DIR = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
PRODUCT_NAME = "ClassSight"
PRODUCT_DESCRIPTION = "Track performance. Guide progress."


def get_db():
    if "db" not in g:
        from flask import current_app
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 15000")
    return g.db


def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def role_required(role):
    """Authorize the loaded account, never a role supplied in a form or URL."""
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.get("role"):
                return redirect(url_for("login", **({"role": "student"} if role == "student" else {})))
            if g.role != role:
                abort(403, description="This page is available only to " + role + " accounts.")
            return view(*args, **kwargs)
        return wrapped
    return decorate


teacher_required = role_required("teacher")
student_required = role_required("student")
# Existing faculty routes retain the same ownership guard under this alias.
login_required = teacher_required


def home_endpoint():
    return "student_dashboard" if g.get("role") == "student" else "dashboard" if g.get("teacher") else "login"


def student_course_url(pk, course="", **kwargs):
    if g.get("role") == "student":
        return url_for("student_dashboard", course=course, **kwargs)
    return url_for("student_detail", pk=pk, course=course, **kwargs)


def login_email(value):
    value = clean_text(value, "Email", 254).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("Enter a valid email address.")
    return value


def own_student_rows():
    """The student scope is the authenticated account's immutable roster link."""
    rows = get_db().execute(
        """SELECT r.*, s.student_id, s.name, s.section, s.batch, s.email,
        c.title AS course_title FROM records r JOIN students s ON s.id = r.student_pk
        JOIN courses c ON c.code = r.course_code WHERE s.id = ? ORDER BY c.position""",
        (g.student_user["student_pk"],))
    return [enrich(row) for row in rows]


def owned_student(pk):
    row = get_db().execute("SELECT * FROM students WHERE id = ? AND teacher_id = ?",
                           (pk, g.teacher["id"])).fetchone()
    if row is None:
        abort(404, description="Student record was not found.")
    return dict(row)


def owned_record(pk):
    row = get_db().execute(
        """SELECT r.*, s.student_id, s.name, s.section, s.batch, s.email,
        c.title AS course_title FROM records r JOIN students s ON s.id = r.student_pk
        JOIN courses c ON c.code = r.course_code WHERE r.id = ? AND s.teacher_id = ?""",
        (pk, g.teacher["id"])).fetchone()
    if row is None:
        abort(404, description="Course record was not found.")
    return enrich(row)


def scope_options():
    db = get_db()
    return {
        "sections": [r[0] for r in db.execute(
            "SELECT DISTINCT section FROM students WHERE teacher_id = ? ORDER BY section", (g.teacher["id"],))],
        "batches": [r[0] for r in db.execute(
            "SELECT DISTINCT batch FROM students WHERE teacher_id = ? ORDER BY batch DESC", (g.teacher["id"],))],
    }


def scoped_rows(default_course="", source=None):
    source = request.args if source is None else source
    filters = {"q": source.get("q", "").strip()[:80],
               "section": source.get("section", "").strip()[:20],
               "batch": source.get("batch", "").strip()[:9],
               "course": source.get("course", default_course).strip(),
               "status": source.get("status", "").strip(),
               "student": str(source.get("student", "")).strip()}
    if default_course and not filters["course"]:
        filters["course"] = default_course
    if filters["course"] and filters["course"] not in dict(COURSES):
        abort(400, description="Select a valid course.")
    if filters["status"] not in ("", "below", "eligible", "not_started"):
        abort(400, description="Select a valid attendance status.")
    conditions, params = ["s.teacher_id = ?"], [g.teacher["id"]]
    if filters["student"]:
        try:
            student_pk = integer(filters["student"], "Student reference", 1, 1000000000)
        except ValueError as exc:
            abort(400, description=str(exc))
        owned_student(student_pk)
        conditions.append("s.id = ?")
        params.append(student_pk)
    for field in ("section", "batch"):
        if filters[field]:
            conditions.append("s." + field + " = ?")
            params.append(filters[field])
    if filters["course"]:
        conditions.append("r.course_code = ?")
        params.append(filters["course"])
    if filters["q"]:
        escaped = filters["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("(s.student_id LIKE ? ESCAPE '\\' OR s.name LIKE ? ESCAPE '\\')")
        params += ["%" + escaped + "%"] * 2
    if filters["status"] == "below":
        conditions.append("r.max_hours > 0 AND 4 * r.attended_hours < 3 * r.max_hours")
    elif filters["status"] == "eligible":
        conditions.append("r.max_hours > 0 AND 4 * r.attended_hours >= 3 * r.max_hours")
    elif filters["status"] == "not_started":
        conditions.append("r.max_hours = 0")
    sql = """SELECT r.*, s.student_id, s.name, s.section, s.batch, s.email,
        c.title AS course_title FROM records r JOIN students s ON s.id = r.student_pk
        JOIN courses c ON c.code = r.course_code WHERE """ + " AND ".join(conditions)
    sql += " ORDER BY s.section, s.batch, s.student_id, c.position"
    return [enrich(r) for r in get_db().execute(sql, params)], filters


def filtered_url(endpoint, filters, **kwargs):
    values = {k: v for k, v in filters.items() if v}
    values.update(kwargs)
    return url_for(endpoint, **values)


def persistent_secret(instance_path):
    configured = os.getenv("SECRET_KEY")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("SECRET_KEY must contain at least 32 characters.")
        return configured
    path = Path(instance_path) / "secret.key"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as file:
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return path.read_text(encoding="ascii").strip()


def make_csv(headers, rows, filename):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows([[safe_cell(value) for value in row] for row in rows])
    return send_file(io.BytesIO(output.getvalue().encode("utf-8-sig")),
                     mimetype="text/csv", as_attachment=True, download_name=filename)


def create_app(test_config=None):
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.from_mapping(
        DATABASE=str(Path(app.instance_path) / "analyzer.sqlite3"),
        SECRET_KEY=(test_config or {}).get("SECRET_KEY") or persistent_secret(app.instance_path),
        MAX_CONTENT_LENGTH=3 * 1024 * 1024, MAX_FORM_MEMORY_SIZE=2 * 1024 * 1024,
        MAX_FORM_PARTS=20000, CSV_MAX_BYTES=2 * 1024 * 1024, SEED_DEMO=True,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("APP_HTTPS", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), SESSION_REFRESH_EACH_REQUEST=False,
        STUDENT_INVITE_SECONDS=48 * 60 * 60,
    )
    if test_config:
        app.config.update(test_config)
    app.jinja_env.filters["points"] = points
    app.jinja_env.globals.update(csrf_token=csrf_token, filtered_url=filtered_url,
                                home_endpoint=home_endpoint, student_course_url=student_course_url)

    @app.teardown_appcontext
    def close_db(_error):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.before_request
    def load_user_and_check_csrf():
        g.teacher = None
        g.student_user = None
        g.role = None
        stored_role = session.get("role")
        if stored_role == "student" and session.get("student_account_id") is not None and "teacher_id" not in session:
            user = get_db().execute(
                """SELECT a.id AS account_id, a.student_pk, a.email AS login_email,
                a.password_hash, a.active, a.auth_version, s.id, s.teacher_id, s.student_id,
                s.name, s.section, s.batch, s.email, t.institution, t.campus, t.department,
                t.academic_year, t.semester, t.name AS faculty_name, t.faculty_no,
                EXISTS(SELECT 1 FROM records r WHERE r.student_pk = a.student_pk) AS has_course_records
                FROM student_accounts a JOIN students s ON s.id = a.student_pk
                JOIN teachers t ON t.id = s.teacher_id WHERE a.id = ?""",
                (session["student_account_id"],)).fetchone()
            if user is None or not user["active"] or user["auth_version"] != session.get("student_auth_version"):
                session.clear()
            else:
                g.student_user, g.role = dict(user), "student"
        elif stored_role in (None, "teacher") and session.get("teacher_id") is not None and "student_account_id" not in session:
            pk = session["teacher_id"]
            user = get_db().execute("SELECT * FROM teachers WHERE id = ?", (pk,)).fetchone()
            if user is None:
                session.clear()
            else:
                g.teacher, g.role = dict(user), "teacher"
        elif stored_role is not None or "teacher_id" in session or "student_account_id" in session:
            session.clear()
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            expected, supplied = session.get("_csrf_token", ""), request.form.get("csrf_token", "")
            if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
                abort(400, description="This form expired. Reload the page and try again.")

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'")
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        if request.endpoint in ("student_activate", "student_access"):
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.context_processor
    def template_helpers():
        return {"teacher": g.get("teacher"), "current_user": g.get("teacher") or g.get("student_user"),
                "workspace": g.get("teacher") or g.get("student_user"),
                "portal_role": g.get("role"), "is_student_view": g.get("role") == "student",
                "product_name": PRODUCT_NAME, "product_description": PRODUCT_DESCRIPTION,
                "components": COMPONENTS, "courses": COURSES,
                "grade_options": GRADES, "today": datetime.now(IST).date().isoformat(),
                "scope": scope_options() if g.get("teacher") else {"sections": [], "batches": []}}

    @app.get("/")
    def index():
        return redirect(url_for(home_endpoint()))

    @app.get("/dashboard")
    def dashboard_redirect():
        return redirect(url_for(home_endpoint()))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if g.role:
            return redirect(url_for(home_endpoint()))
        error, values = None, {}
        if request.method == "POST":
            values = request.form
            try:
                name = clean_text(values.get("name"), "Faculty name")
                email = clean_text(values.get("email"), "Email", 254).lower()
                if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                    raise ValueError("Enter a valid email address.")
                password = values.get("password", "")
                if not 8 <= len(password) <= 128:
                    raise ValueError("Use a password containing 8–128 characters.")
                if password != values.get("confirm_password"):
                    raise ValueError("The passwords do not match.")
                faculty_no = clean_text(values.get("faculty_no"), "Faculty ID", 30, optional=True)
                db = get_db()
                with db:
                    cursor = db.execute(
                        "INSERT INTO teachers (name, email, password_hash, faculty_no) VALUES (?, ?, ?, ?)",
                        (name, email, generate_password_hash(password, method="scrypt"), faculty_no))
                    pk = cursor.lastrowid
                    unowned = db.execute("SELECT 1 FROM students WHERE teacher_id IS NULL LIMIT 1").fetchone()
                    if unowned:
                        db.execute("UPDATE students SET teacher_id = ? WHERE teacher_id IS NULL", (pk,))
                    elif app.config["SEED_DEMO"]:
                        seed_students(db, pk)
                session.clear()
                session["teacher_id"], session["role"], session.permanent = pk, "teacher", True
                flash("Faculty account created.", "success")
                return redirect(url_for("dashboard"))
            except ValueError as exc:
                error = str(exc)
            except sqlite3.IntegrityError:
                error = "This email already has a faculty account."
        return render_template("register.html", error=error, values=values), 400 if error else 200

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.role:
            return redirect(url_for(home_endpoint()))
        role = request.form.get("role", "teacher") if request.method == "POST" else request.args.get("role", "teacher")
        if role not in ("teacher", "student"):
            abort(400, description="Choose Teacher or Student access.")
        error, email = None, ""
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()[:254]
            password = request.form.get("password", "")
            db, now = get_db(), time.time()
            key = hmac.new(app.secret_key.encode(), (role + "|" + email + "|" + (request.remote_addr or "")).encode(),
                           hashlib.sha256).hexdigest()
            attempt = db.execute("SELECT * FROM login_attempts WHERE key = ?", (key,)).fetchone()
            if attempt and now - attempt["started"] < 900 and attempt["failures"] >= 10:
                return render_template("login.html", error="Too many attempts. Try again in 15 minutes.",
                                       email=email, role=role), 429
            if role == "teacher":
                account = db.execute("SELECT * FROM teachers WHERE email = ?", (email,)).fetchone()
            else:
                account = db.execute("""SELECT a.* FROM student_accounts a JOIN students s ON s.id = a.student_pk
                    WHERE a.email = ? AND a.active = 1 AND s.teacher_id IS NOT NULL""", (email,)).fetchone()
            if account is not None and len(password) <= 128 and check_password_hash(account["password_hash"], password):
                with db:
                    db.execute("DELETE FROM login_attempts WHERE key = ?", (key,))
                session.clear()
                session["role"], session.permanent = role, True
                if role == "teacher":
                    session["teacher_id"] = account["id"]
                else:
                    session["student_account_id"] = account["id"]
                    session["student_auth_version"] = account["auth_version"]
                return redirect(url_for("student_dashboard" if role == "student" else "dashboard"))
            with db:
                db.execute("DELETE FROM login_attempts WHERE started < ?", (now - 86400,))
                if not attempt or now - attempt["started"] >= 900:
                    db.execute("INSERT OR REPLACE INTO login_attempts VALUES (?, 1, ?)", (key, now))
                else:
                    db.execute("UPDATE login_attempts SET failures = failures + 1 WHERE key = ?", (key,))
            error = "Email or password is incorrect."
        return render_template("login.html", error=error, email=email, role=role), 400 if error else 200

    @app.post("/logout")
    def logout():
        if not g.role:
            return redirect(url_for("login"))
        role = g.role
        session.clear()
        return redirect(url_for("login", **({"role": "student"} if role == "student" else {})))

    @app.get("/teacher/dashboard")
    @login_required
    def dashboard():
        rows, filters = scoped_rows()
        summary = summarize(rows)
        by_course = []
        for code, title in COURSES:
            group = [r for r in rows if r["course_code"] == code]
            if not filters["course"] or code == filters["course"]:
                by_course.append({"code": code, "title": title, **summarize(group)})
        return render_template("dashboard.html", rows=rows, filters=filters, summary=summary,
                               by_course=by_course,
                               analysis=analyze(rows),
                               priority=[r for r in rows if r["attendance_status"] == "Below 75%"][:6])

    @app.get("/student/dashboard")
    @student_required
    def student_dashboard():
        student = {key: g.student_user[key] for key in ("id", "student_id", "name", "section", "batch", "email")}
        rows = own_student_rows()
        if not rows:
            return render_template("student_empty.html", student=student)
        selected = next((row for row in rows if row["course_code"] == request.args.get("course", COURSES[0][0])), None)
        if selected is None:
            abort(404, description="Course enrollment was not found.")
        archived = get_db().execute("SELECT source_json FROM legacy_results WHERE student_pk = ?",
                                    (g.student_user["student_pk"],)).fetchone()
        legacy = json.loads(archived[0]) if archived else None
        return render_template("student_dashboard.html", student=student, rows=rows, selected=selected,
                               summary=summarize(rows), profile=student_profile(rows),
                               course_comparison=[{"row": row, "class_average": None} for row in rows],
                               legacy=legacy, legacy_analysis=original_result(legacy) if legacy else None)

    @app.get("/student/reports")
    @student_required
    def student_reports():
        return render_template("student_reports.html", summary=summarize(own_student_rows()))

    @app.get("/student/reports/<format>")
    @student_required
    def student_download_report(format):
        if format not in ("pdf", "xlsx", "csv"):
            abort(404)
        from reports import department_pdf, department_workbook, report_csv
        rows = own_student_rows()
        generated = datetime.now(IST)
        user = g.student_user
        profile = {key: user[key] for key in ("institution", "campus", "department", "academic_year", "semester", "faculty_no")}
        profile["name"] = user["faculty_name"]
        filters = {"student": str(user["student_pk"]), "section": user["section"], "batch": user["batch"]}
        if format == "pdf":
            data, mime = department_pdf(profile, rows, filters, generated, personal=True), "application/pdf"
        elif format == "xlsx":
            data, mime = department_workbook(profile, rows, filters, generated, personal=True), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            data, mime = report_csv(rows, personal=True), "text/csv"
        return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True,
                         download_name="classsight_student_report_" + generated.strftime("%Y%m%d") + "." + format)

    @app.route("/student/settings", methods=["GET", "POST"])
    @student_required
    def student_settings():
        error = None
        if request.method == "POST":
            try:
                if request.form.get("action") != "password":
                    raise ValueError("Choose a valid account action.")
                old = request.form.get("current_password", "")
                if len(old) > 128 or not check_password_hash(g.student_user["password_hash"], old):
                    raise ValueError("Current password is incorrect.")
                new = request.form.get("new_password", "")
                if not 8 <= len(new) <= 128:
                    raise ValueError("New password must contain 8–128 characters.")
                if new != request.form.get("confirm_password"):
                    raise ValueError("New passwords do not match.")
                account_id, version = g.student_user["account_id"], g.student_user["auth_version"]
                db = get_db()
                with db:
                    changed = db.execute("""UPDATE student_accounts SET password_hash = ?, auth_version = auth_version + 1
                        WHERE id = ? AND active = 1 AND auth_version = ?""",
                        (generate_password_hash(new, method="scrypt"), account_id, version))
                    if changed.rowcount != 1:
                        raise ValueError("Your account changed. Sign in again before updating the password.")
                session.clear()
                session["role"], session["student_account_id"] = "student", account_id
                session["student_auth_version"], session.permanent = version + 1, True
                flash("Password changed. Other student sessions have been signed out.", "success")
                return redirect(url_for("student_settings"))
            except ValueError as exc:
                error = str(exc)
        return render_template("student_settings.html", error=error), 400 if error else 200

    @app.route("/students/<int:pk>/access", methods=["GET", "POST"])
    @teacher_required
    def student_access(pk):
        student = owned_student(pk)
        error, activation_link, expiry = None, None, None
        db = get_db()
        if request.method == "POST":
            try:
                email = login_email(request.form.get("email", ""))
                token = secrets.token_urlsafe(32)
                expires_at = int(time.time()) + app.config["STUDENT_INVITE_SECONDS"]
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    existing = db.execute("SELECT student_pk FROM student_accounts WHERE email = ?", (email,)).fetchone()
                    if existing and existing["student_pk"] != pk:
                        raise ValueError("This email is already assigned to another student account.")
                    db.execute("DELETE FROM student_invites WHERE student_pk = ?", (pk,))
                    db.execute("INSERT INTO student_invites (student_pk, email, token_hash, expires_at) VALUES (?, ?, ?, ?)",
                               (pk, email, hashlib.sha256(token.encode()).hexdigest(), expires_at))
                activation_link = url_for("student_activate", token=token, _external=True)
                expiry = datetime.fromtimestamp(expires_at, IST).strftime("%d %b %Y, %I:%M %p IST")
                flash("Student activation link created. Share it directly with this student.", "success")
            except ValueError as exc:
                error = str(exc)
            except sqlite3.IntegrityError:
                error = "The student account changed. Reload this page and try again."
        account = db.execute("SELECT email, active FROM student_accounts WHERE student_pk = ?", (pk,)).fetchone()
        pending = db.execute("SELECT email, expires_at FROM student_invites WHERE student_pk = ? AND expires_at > ?",
                             (pk, int(time.time()))).fetchone()
        return render_template("student_access.html", student=student, account=account, pending=pending,
                               activation_link=activation_link, expiry=expiry, error=error), 400 if error else 200

    @app.post("/students/<int:pk>/access/revoke")
    @teacher_required
    def revoke_student_access(pk):
        owned_student(pk)
        db = get_db()
        with db:
            db.execute("UPDATE student_accounts SET active = 0, auth_version = auth_version + 1 WHERE student_pk = ?", (pk,))
            db.execute("DELETE FROM student_invites WHERE student_pk = ?", (pk,))
        flash("Student login access and outstanding activation links have been revoked.", "success")
        return redirect(url_for("student_access", pk=pk))

    def find_student_invite(token):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            abort(404, description="This activation link is invalid, expired or already used.")
        row = get_db().execute("""SELECT i.*, s.name, s.student_id, s.section, s.batch
            FROM student_invites i JOIN students s ON s.id = i.student_pk
            WHERE i.token_hash = ? AND i.expires_at > ? AND s.teacher_id IS NOT NULL""",
            (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
        if row is None:
            abort(404, description="This activation link is invalid, expired or already used.")
        return dict(row)

    @app.route("/student/activate/<token>", methods=["GET", "POST"])
    def student_activate(token):
        if g.role:
            flash("Sign out before activating a student account.", "warning")
            return redirect(url_for(home_endpoint()))
        invitation, error = find_student_invite(token), None
        if request.method == "POST":
            try:
                password = request.form.get("password", "")
                if not 8 <= len(password) <= 128:
                    raise ValueError("Use a password containing 8–128 characters.")
                if password != request.form.get("confirm_password"):
                    raise ValueError("The passwords do not match.")
                hashed = generate_password_hash(password, method="scrypt")
                db = get_db()
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    invitation = find_student_invite(token)
                    db.execute("""INSERT INTO student_accounts (student_pk, email, password_hash)
                        VALUES (?, ?, ?) ON CONFLICT(student_pk) DO UPDATE SET
                        email = excluded.email, password_hash = excluded.password_hash, active = 1,
                        auth_version = student_accounts.auth_version + 1""",
                        (invitation["student_pk"], invitation["email"], hashed))
                    account = db.execute("SELECT id, auth_version FROM student_accounts WHERE student_pk = ?",
                                         (invitation["student_pk"],)).fetchone()
                    db.execute("DELETE FROM student_invites WHERE student_pk = ?", (invitation["student_pk"],))
                session.clear()
                session["role"], session["student_account_id"] = "student", account["id"]
                session["student_auth_version"], session.permanent = account["auth_version"], True
                flash("Your ClassSight student account is ready.", "success")
                return redirect(url_for("student_dashboard"))
            except ValueError as exc:
                error = str(exc)
            except sqlite3.IntegrityError:
                error = "This email is already in use. Ask your teacher for a new activation link."
        return render_template("student_activate.html", invitation=invitation, error=error, role="student"), 400 if error else 200

    @app.get("/analytics")
    @login_required
    def performance_analytics():
        rows, filters = scoped_rows()
        analysis = analyze(rows)
        filters.update({key: request.args.get(key, "").strip() for key in ("grade", "performance")})
        filters["order"] = request.args.get("order", "name").strip()
        try:
            listing = select_students(analysis["students"], **{key: filters[key] for key in ("grade", "performance", "order")})
        except ValueError as exc:
            abort(400, description=str(exc))
        return render_template("analytics.html", analysis=analysis, listing=listing, filters=filters)

    @app.get("/analytics/export")
    @login_required
    def export_analysis():
        rows, _filters = scoped_rows()
        try:
            listing = select_students(analyze(rows)["students"],
                                      **{key: request.args.get(key, "").strip() for key in ("grade", "performance")},
                                      order=request.args.get("order", "name"))
        except ValueError as exc:
            abort(400, description=str(exc))
        return make_csv(("student_id", "name", "section", "batch", "evaluated_average", "overall_grade",
                         "performance_status", "weighted_attendance", "evaluated_courses", "selected_courses",
                         "academic_failures", "attendance_shortages", "rank"),
                        [(p["student"]["student_id"], p["student"]["name"], p["student"]["section"],
                          p["student"]["batch"], f'{p["average"]:.2f}' if p["average"] is not None else "",
                          p["grade"], p["status"], f'{p["summary"]["attendance_pct"]:.2f}' if p["summary"]["attendance_pct"] is not None else "",
                          p["complete_count"], p["course_count"], len(p["failed_courses"]), len(p["shortage_courses"]),
                          p["rank"] or "") for p in listing], "student-performance-analysis.csv")

    @app.get("/students")
    @login_required
    def students():
        rows, filters = scoped_rows()
        grouped = {}
        for row in rows:
            grouped.setdefault(row["student_pk"], []).append(row)
        listing = [{"student": records[0], "summary": summarize(records), "profile": student_profile(records)} for records in grouped.values()]
        return render_template("students.html", listing=listing, filters=filters, summary=summarize(rows))

    @app.route("/students/add", methods=["GET", "POST"])
    @login_required
    def add_student():
        values, error = {"section": "CSE-A", "batch": "2025-2029"}, None
        if request.method == "POST":
            values = request.form
            try:
                validated = student_values(values)
                db = get_db()
                with db:
                    pk = insert_student(db, g.teacher["id"], validated)
                flash("Student added and enrolled in all seven courses.", "success")
                return redirect(url_for("student_detail", pk=pk))
            except ValueError as exc:
                error = str(exc)
            except sqlite3.IntegrityError:
                error = "This registration number already exists."
        return render_template("student_form.html", values=values, error=error, editing=False), 400 if error else 200

    @app.route("/students/<int:pk>/edit", methods=["GET", "POST"])
    @login_required
    def edit_student(pk):
        student = owned_student(pk)
        values, error = student, None
        if request.method == "POST":
            values = request.form
            try:
                v = student_values(values)
                db = get_db()
                with db:
                    db.execute("""UPDATE students SET student_id = ?, name = ?, section = ?, batch = ?,
                               email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND teacher_id = ?""",
                               (*(v[k] for k in ("student_id", "name", "section", "batch", "email")), pk, g.teacher["id"]))
                flash("Student profile updated. Academic records have been retained.", "success")
                return redirect(url_for("student_detail", pk=pk))
            except ValueError as exc:
                error = str(exc)
            except sqlite3.IntegrityError:
                error = "This registration number already exists."
        return render_template("student_form.html", values=values, student=student, error=error,
                               editing=True), 400 if error else 200

    @app.get("/students/<int:pk>")
    @login_required
    def student_detail(pk):
        student = owned_student(pk)
        records, _ = scoped_rows(source={})
        rows = [r for r in records if r["student_pk"] == pk]
        code = request.args.get("course", COURSES[0][0])
        selected = next((r for r in rows if r["course_code"] == code), None)
        if selected is None:
            abort(404, description="Course enrollment was not found.")
        archived = get_db().execute("SELECT source_json FROM legacy_results WHERE student_pk = ?", (pk,)).fetchone()
        cohort_rows = [row for row in records if row["section"] == student["section"] and row["batch"] == student["batch"]]
        cohort = analyze(cohort_rows)
        profile = next(p for p in cohort["students"] if p["student"]["student_pk"] == pk)
        course_comparison = [{"row": row, "class_average": next(c["average"] for c in cohort["courses"] if c["code"] == row["course_code"])} for row in rows]
        return render_template("detail.html", student=student, rows=rows, selected=selected,
                               summary=summarize(rows), profile=profile, course_comparison=course_comparison,
                               ranked_students=cohort["evaluated_students"],
                               legacy=json.loads(archived[0]) if archived else None,
                               legacy_analysis=original_result(json.loads(archived[0])) if archived else None)

    @app.get("/students/<int:pk>/remove")
    @login_required
    def remove_student(pk):
        return render_template("remove_student.html", student=owned_student(pk))

    @app.post("/students/<int:pk>/delete")
    @login_required
    def delete_student(pk):
        student = owned_student(pk)
        db = get_db()
        with db:
            db.execute("DELETE FROM students WHERE id = ? AND teacher_id = ?", (pk, g.teacher["id"]))
        flash(student["name"] + " and their academic records were removed.", "success")
        return redirect(url_for("students"))

    def validate_changes(row, form, prefix, kind):
        expected_version = integer(form.get(prefix + "version", ""), "Record version", 1, 1000000000)
        if expected_version != row["version"]:
            raise ValueError("This register changed after you opened it. Reload before saving.")
        if kind == "attendance":
            maximum = integer(form.get(prefix + "max_hours", ""), "Max hours")
            attended = integer(form.get(prefix + "attended_hours", ""), "Attended hours", 0, maximum)
            return ("max_hours = ?, attended_hours = ?", (maximum, attended), expected_version)
        values = tuple(mark(form.get(prefix + key, ""), label, cap) for key, label, cap in COMPONENTS)
        return (", ".join(key + " = ?" for key, _label, _cap in COMPONENTS), values, expected_version)

    def save_changes(changes):
        db = get_db()
        with db:
            db.execute("BEGIN IMMEDIATE")
            for row, (setters, values, version) in changes:
                cursor = db.execute("UPDATE records SET " + setters +
                                    ", version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ?",
                                    (*values, row["id"], version))
                if cursor.rowcount != 1:
                    raise ValueError("A record changed while saving. Nothing was saved; reload the register.")

    @app.route("/records/<int:pk>/<kind>", methods=["GET", "POST"])
    @login_required
    def edit_record(pk, kind):
        if kind not in ("attendance", "marks"):
            abort(404)
        row, error = owned_record(pk), None
        values = {k: points(row[k]) for k, _label, _cap in COMPONENTS}
        values.update(max_hours=row["max_hours"], attended_hours=row["attended_hours"], version=row["version"])
        if request.method == "POST":
            values = request.form
            try:
                save_changes([(row, validate_changes(row, values, "", kind))])
                flash("Course " + kind + " saved.", "success")
                return redirect(url_for("student_detail", pk=row["student_pk"], course=row["course_code"]))
            except ValueError as exc:
                error = str(exc)
        return render_template("record_form.html", row=row, kind=kind, values=values, error=error), 400 if error else 200

    @app.get("/attendance")
    @login_required
    def attendance():
        rows, filters = scoped_rows(COURSES[0][0])
        sessions = get_db().execute(
            "SELECT * FROM attendance_sessions WHERE teacher_id = ? ORDER BY id DESC LIMIT 10",
            (g.teacher["id"],)).fetchall()
        return render_template("attendance.html", rows=rows, filters=filters,
                               summary=summarize(rows), sessions=sessions)

    @app.route("/attendance/edit", methods=["GET", "POST"], endpoint="edit_attendance")
    @app.route("/marks", methods=["GET", "POST"])
    @login_required
    def register_grid():
        kind = "marks" if request.path == "/marks" else "attendance"
        rows, filters = scoped_rows(COURSES[0][0])
        error = None
        if request.method == "POST":
            try:
                submitted = request.form.getlist("record_id")
                if sorted(submitted) != sorted(str(r["id"]) for r in rows) or not rows:
                    raise ValueError("The student roster changed. Reload the register before saving.")
                changes = [(r, validate_changes(r, request.form, "r" + str(r["id"]) + "_", kind)) for r in rows]
                save_changes(changes)
                flash("All " + kind + " entries saved.", "success")
                return redirect(filtered_url("register_grid" if kind == "marks" else "attendance", filters))
            except ValueError as exc:
                error = str(exc)
        return render_template("register_grid.html", kind=kind, rows=rows, filters=filters,
                               summary=summarize(rows), error=error, posted=request.form if error else {}), 400 if error else 200

    @app.route("/attendance/session", methods=["GET", "POST"])
    @login_required
    def record_session():
        # A class session must select one complete section and batch.
        rows, filters = scoped_rows(COURSES[0][0])
        filters["q"], filters["status"], filters["student"] = "", "", ""
        rows, filters = scoped_rows(COURSES[0][0], filters)
        ready = bool(filters["course"] and filters["section"] and filters["batch"])
        if not ready:
            rows = []
        error = None
        if request.method == "POST":
            try:
                if not ready or not rows:
                    raise ValueError("Select a course, section, and batch containing students.")
                hours = integer(request.form.get("hours", ""), "Session hours", 1, 12)
                held_on = date.fromisoformat(request.form.get("held_on", ""))
                if held_on > datetime.now(IST).date():
                    raise ValueError("Attendance cannot be recorded for a future date.")
                submitted = request.form.getlist("record_id")
                if sorted(submitted) != sorted(str(r["id"]) for r in rows):
                    raise ValueError("The roster changed. Reload before recording attendance.")
                snapshot, changes = [], []
                for row in rows:
                    attended = integer(request.form.get("a" + str(row["id"]), ""), row["name"] + " attended hours", 0, hours)
                    version = integer(request.form.get("v" + str(row["id"]), ""), "Version", 1, 1000000000)
                    if version != row["version"] or row["max_hours"] + hours > 10000:
                        raise ValueError("A record changed or the hour limit was exceeded. Reload the register.")
                    snapshot.append({"student_id": row["student_id"], "name": row["name"], "attended": attended, "absent": hours - attended})
                    changes.append((row, attended, version))
                db = get_db()
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    for row, attended, version in changes:
                        changed = db.execute(
                            """UPDATE records SET max_hours = max_hours + ?, attended_hours = attended_hours + ?,
                            version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ?""",
                            (hours, attended, row["id"], version))
                        if changed.rowcount != 1:
                            raise ValueError("The register changed while saving. Nothing was recorded.")
                    db.execute("""INSERT INTO attendance_sessions
                        (teacher_id, course_code, section, batch, held_on, hours, snapshot_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                               (g.teacher["id"], filters["course"], filters["section"], filters["batch"],
                                held_on.isoformat(), hours, json.dumps(snapshot)))
                flash("Attendance recorded for " + str(len(rows)) + " students.", "success")
                return redirect(filtered_url("attendance", filters))
            except ValueError as exc:
                error = str(exc) or "Select a valid session date."
        return render_template("session_form.html", rows=rows, filters=filters, ready=ready,
                               error=error, posted=request.form if error else {}), 400 if error else 200

    @app.get("/attendance/sessions/<int:pk>")
    @login_required
    def session_detail(pk):
        row = get_db().execute("SELECT * FROM attendance_sessions WHERE id = ? AND teacher_id = ?",
                               (pk, g.teacher["id"])).fetchone()
        if row is None:
            abort(404)
        return render_template("session_detail.html", record=dict(row), entries=json.loads(row["snapshot_json"]))

    @app.get("/courses")
    @login_required
    def course_catalogue():
        rows, filters = scoped_rows(source={})
        catalogue = [{"code": code, "title": title, **summarize([r for r in rows if r["course_code"] == code])}
                     for code, title in COURSES]
        return render_template("courses.html", catalogue=catalogue, filters=filters)

    @app.route("/import", methods=["GET", "POST"])
    @login_required
    def import_csv():
        error = None
        if request.method == "POST":
            try:
                imported = parse_csv(request.files.get("file"), app.config["CSV_MAX_BYTES"])
                mode = request.form.get("mode", "reject")
                if mode not in ("reject", "update"):
                    raise ValueError("Select a valid import mode.")
                db, count = get_db(), 0
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    initially_existing = {r["student_id"]: dict(r) for r in db.execute(
                        "SELECT * FROM students WHERE teacher_id = ?", (g.teacher["id"],))}
                    current = dict(initially_existing)
                    for item in imported:
                        profile = item["profile"]
                        existing = current.get(profile["student_id"])
                        if existing and profile["student_id"] in initially_existing:
                            if mode == "reject":
                                raise ValueError("Registration number " + profile["student_id"] +
                                                 " already exists. Select Update existing records to replace its course values.")
                            if tuple(existing[k] for k in ("name", "section", "batch")) != tuple(
                                    profile[k] for k in ("name", "section", "batch")):
                                raise ValueError(profile["student_id"] + ": name, section, and batch must match the student profile.")
                        if not existing:
                            pk = insert_student(db, g.teacher["id"], profile)
                            existing = {"id": pk, **profile}
                            current[profile["student_id"]] = existing
                        if "legacy" in item:
                            db.execute("INSERT OR REPLACE INTO legacy_results VALUES (?, ?)",
                                       (existing["id"], json.dumps(item["legacy"])))
                        else:
                            keys = ("max_hours", "attended_hours") + tuple(k for k, _label, _cap in COMPONENTS)
                            db.execute("UPDATE records SET " + ", ".join(k + " = ?" for k in keys)
                                       + ", version = version + 1, updated_at = CURRENT_TIMESTAMP "
                                       "WHERE student_pk = ? AND course_code = ?",
                                       (*(item[k] for k in keys), existing["id"], item["course_code"]))
                        count += 1
                flash(str(count) + " course/student records imported.", "success")
                return redirect(url_for("students"))
            except (ValueError, csv.Error) as exc:
                error = str(exc)
            except sqlite3.IntegrityError:
                error = "Import conflicts with an existing record. No changes were saved."
        return render_template("upload.html", error=error, csv_fields=CSV_FIELDS), 400 if error else 200

    @app.get("/csv/template")
    @login_required
    def download_template():
        return make_csv(CSV_FIELDS, [("CSE25A101", "Aditi Sharma", "CSE-A", "2025-2029",
                                    COURSES[0][0], 40, 32, 4, 5, 12, 8, 9, 11, "")],
                        "faculty_import_template.csv")

    @app.get("/csv/export")
    @login_required
    def export_csv():
        rows, _filters = scoped_rows()
        data = [(r["student_id"], r["name"], r["section"], r["batch"], r["course_code"],
                 r["max_hours"], r["attended_hours"], *(points(r[k]) for k, _label, _cap in COMPONENTS))
                for r in rows]
        return make_csv(CSV_FIELDS, data, "faculty_course_records.csv")

    @app.get("/reports")
    @login_required
    def reports():
        rows, filters = scoped_rows()
        return render_template("reports.html", rows=rows, filters=filters, summary=summarize(rows))

    @app.get("/reports/<format>")
    @login_required
    def download_report(format):
        if format not in ("pdf", "xlsx", "csv"):
            abort(404)
        from reports import department_pdf, department_workbook, report_csv
        rows, filters = scoped_rows()
        generated = datetime.now(IST)
        profile = dict(g.teacher)
        profile.pop("password_hash", None)
        if format == "pdf":
            data, mime = department_pdf(profile, rows, filters, generated), "application/pdf"
        elif format == "xlsx":
            data, mime = department_workbook(profile, rows, filters, generated), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            data, mime = report_csv(rows), "text/csv"
        return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True,
                         download_name="department_report_" + generated.strftime("%Y%m%d") + "." + format)

    @app.get("/warnings")
    @login_required
    def warnings():
        rows, filters = scoped_rows()
        letters = get_db().execute(
            "SELECT * FROM warning_letters WHERE teacher_id = ? ORDER BY id DESC", (g.teacher["id"],)).fetchall()
        archive = [{"id": r["id"], "reference": r["reference"], "issued_at": r["issued_at"],
                    "course_code": json.loads(r["snapshot_json"])["record"]["course_code"],
                    **json.loads(r["snapshot_json"])["student"]} for r in letters]
        return render_template("warnings.html", rows=[r for r in rows if r["attendance_status"] == "Below 75%"],
                               filters=filters, letters=archive)

    @app.post("/warnings/issue/<int:pk>")
    @login_required
    def issue_warning(pk):
        row = owned_record(pk)
        if row["attendance_status"] != "Below 75%":
            abort(400, description="This course has no current attendance shortage.")
        profile = dict(g.teacher)
        profile.pop("password_hash", None)
        generated = datetime.now(IST)
        snapshot = {"profile": profile, "student": {k: row[k] for k in ("student_id", "name", "section", "batch")},
                    "record": row}
        reference = "FP-ATT-" + generated.strftime("%Y%m%d") + "-" + secrets.token_hex(4).upper()
        db = get_db()
        with db:
            cursor = db.execute(
                """INSERT INTO warning_letters (teacher_id, student_pk, snapshot_json, issued_at, reference)
                VALUES (?, ?, ?, ?, ?)""",
                (g.teacher["id"], row["student_pk"], json.dumps(snapshot), generated.isoformat(), reference))
        return redirect(url_for("download_warning", pk=cursor.lastrowid))

    @app.get("/warnings/<int:pk>/download")
    @login_required
    def download_warning(pk):
        from reports import warning_pdf
        letter = get_db().execute("SELECT * FROM warning_letters WHERE id = ? AND teacher_id = ?",
                                  (pk, g.teacher["id"])).fetchone()
        if letter is None:
            abort(404)
        data = warning_pdf(json.loads(letter["snapshot_json"]), letter["reference"], letter["issued_at"])
        return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
                         download_name=letter["reference"] + ".pdf")

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings():
        values, error = g.teacher, None
        if request.method == "POST":
            values = request.form
            try:
                action = request.form.get("action", "")
                db = get_db()
                if action == "profile":
                    fields = ("name", "faculty_no", "institution", "campus", "department", "academic_year")
                    validated = [clean_text(values.get(k), k.replace("_", " ").title(), 100,
                                            optional=k == "faculty_no") for k in fields]
                    if not re.fullmatch(r"20\d{2}-20\d{2}", validated[-1]) or int(validated[-1][5:]) != int(validated[-1][:4]) + 1:
                        raise ValueError("Academic year must span consecutive years, for example 2026-2027.")
                    semester = integer(values.get("semester", ""), "Semester", 1, 12)
                    with db:
                        db.execute("UPDATE teachers SET " + ", ".join(k + " = ?" for k in fields)
                                   + ", semester = ? WHERE id = ?", (*validated, semester, g.teacher["id"]))
                    flash("Faculty and report settings saved.", "success")
                elif action == "password":
                    if not check_password_hash(g.teacher["password_hash"], values.get("current_password", "")):
                        raise ValueError("Current password is incorrect.")
                    new = values.get("new_password", "")
                    if not 8 <= len(new) <= 128:
                        raise ValueError("New password must contain 8–128 characters.")
                    if new != values.get("confirm_password"):
                        raise ValueError("New passwords do not match.")
                    with db:
                        db.execute("UPDATE teachers SET password_hash = ? WHERE id = ?",
                                   (generate_password_hash(new, method="scrypt"), g.teacher["id"]))
                    pk = g.teacher["id"]
                    session.clear()
                    session["teacher_id"], session["role"], session.permanent = pk, "teacher", True
                    flash("Password changed.", "success")
                else:
                    raise ValueError("Choose a valid settings action.")
                return redirect(url_for("settings"))
            except ValueError as exc:
                error = str(exc)
        return render_template("settings.html", values=values, error=error), 400 if error else 200

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(413)
    def friendly_error(error):
        message = "Upload is too large. Use a CSV of 2 MB or smaller." if error.code == 413 else error.description
        return render_template("error.html", code=error.code, message=message), error.code

    with app.app_context():
        init_database(get_db(), app.config["DATABASE"], app.config["SEED_DEMO"])
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
