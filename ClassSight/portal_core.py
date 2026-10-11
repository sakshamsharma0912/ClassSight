"""Exact academic calculations, validation, CSV parsing, and SQLite migration."""
import csv
import io
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

COURSES = (
    ("21CSC201J", "Data Structures and Algorithms"),
    ("21CSC202J", "Operating Systems"),
    ("21CSC203P", "Advanced Programming Practice"),
    ("21CSS201T", "Computer Organization and Architecture"),
    ("21DCS201P", "Design Thinking and Methodology"),
    ("21LEM201T", "Professional Ethics"),
    ("21MAB201T", "Transforms and Boundary Value Problems"),
)
# The order and caps are the project's explicitly requested assessment scheme.
# SQLite stores centimarks, so 4.99 never rounds into the 5-mark maximum.
COMPONENTS = (
    ("assignment_1", "Assignment 1", 5),
    ("assignment_2", "Assignment 2", 5),
    ("internal_exam_1", "Internal Exam 1", 15),
    ("mini_project", "Mini Project", 10),
    ("practical", "Practical", 10),
    ("internal_exam_2", "Internal Exam 2", 15),
    ("university_final", "University Final Exam", 40),
)
GRADES = (("O", 90), ("A+", 80), ("A", 70), ("B+", 60), ("B", 50), ("C", 40), ("F", 0))
CSV_FIELDS = ("student_id", "name", "section", "batch", "course_code",
              "max_hours", "attended_hours") + tuple(c[0] for c in COMPONENTS)
LEGACY_FIELDS = ("student_id", "name", "maths", "science", "english", "attendance")


def clean_text(value, label, limit=80, optional=False):
    value = str(value or "").strip()
    if optional and not value:
        return ""
    if not 1 <= len(value) <= limit or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError(f"{label} must contain 1–{limit} printable characters.")
    return value


def integer(value, label, low=0, high=10000):
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,10}", text):
        raise ValueError(f"{label} must be a whole number.")
    result = int(text)
    if not low <= result <= high:
        raise ValueError(f"{label} must be between {low} and {high}.")
    return result


def mark(value, label, cap):
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,2})?", text):
        raise ValueError(f"{label} must be a number with at most two decimal places.")
    try:
        points = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{label} is invalid.") from None
    if not 0 <= points <= cap:
        raise ValueError(f"{label} must be between 0 and {cap}.")
    return int(points * 100)


def attendance_metrics(max_hours, attended):
    """Use integer inequalities: displayed rounding never grants eligibility."""
    required = (3 * max_hours + 3) // 4
    shortage = max(0, required - attended)
    eligible = max_hours > 0 and 4 * attended >= 3 * max_hours
    return {
        "max_hours": max_hours, "attended_hours": attended,
        "absent_hours": max_hours - attended,
        "attendance_pct": (100 * attended / max_hours) if max_hours else None,
        "required_hours": required,
        "margin": attended - required,
        "can_miss": max(0, (4 * attended - 3 * max_hours) // 3) if max_hours else 0,
        "recover_hours": max(0, 3 * max_hours - 4 * attended),
        "shortage_hours": shortage,
        "attendance_status": ("Not started" if max_hours == 0 else
                              "Below 75%" if not eligible else "Eligible"),
        "eligible": eligible,
    }


def grade_for(total_centimarks):
    return next(label for label, minimum in GRADES if total_centimarks >= minimum * 100)


def enrich(row):
    result = dict(row)
    result.update(attendance_metrics(row["max_hours"], row["attended_hours"]))
    result["internal"] = sum(row[key] or 0 for key, _label, _cap in COMPONENTS[:6]) / 100
    result["internal_complete"] = all(row[key] is not None for key, _label, _cap in COMPONENTS[:6])
    result["complete"] = all(row[key] is not None for key, _label, _cap in COMPONENTS)
    result["entered"] = sum(row[key] is not None for key, _label, _cap in COMPONENTS)
    result["total"] = sum(row[key] or 0 for key, _label, _cap in COMPONENTS) / 100
    result["grade"] = grade_for(round(result["total"] * 100)) if result["complete"] else "Pending"
    result["exam_status"] = ("Not started" if not row["max_hours"] else
                             "Attendance shortage" if not result["eligible"] else "Attendance eligible")
    return result


def summarize(rows):
    total = sum(r["max_hours"] for r in rows)
    attended = sum(r["attended_hours"] for r in rows)
    summary = attendance_metrics(total, attended)
    complete = [r for r in rows if r["complete"]]
    summary.update({
        "records": len(rows), "students": len({r["student_pk"] for r in rows}),
        "at_risk": sum(r["attendance_status"] == "Below 75%" for r in rows),
        "eligible_count": sum(r["eligible"] for r in rows),
        "pending": sum(not r["complete"] for r in rows),
        "average": sum(r["total"] for r in complete) / len(complete) if complete else None,
        "complete_count": len(complete),
        # The sum of individual margins, not a newly rounded aggregate threshold.
        "margin": sum(r["margin"] for r in rows),
    })
    return summary


def student_values(form):
    reg = clean_text(form.get("student_id"), "Registration number", 30).upper()
    if not re.fullmatch(r"[A-Z0-9._-]+", reg):
        raise ValueError("Registration number may contain letters, digits, periods, underscores, or hyphens.")
    section = clean_text(form.get("section"), "Section", 20).upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 -]*", section):
        raise ValueError("Section may contain letters, digits, spaces, or hyphens.")
    batch = clean_text(form.get("batch"), "Batch", 9)
    if not re.fullmatch(r"20\d{2}-20\d{2}", batch) or not 1 <= int(batch[5:]) - int(batch[:4]) <= 6:
        raise ValueError("Batch must be a valid year range, for example 2025-2029.")
    email = clean_text(form.get("email"), "Student email", 254, optional=True).lower()
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Enter a valid student email.")
    return {"student_id": reg, "name": clean_text(form.get("name"), "Student name"),
            "section": section, "batch": batch, "email": email}


def ensure_records(db, student_pk):
    db.executemany("INSERT OR IGNORE INTO records (student_pk, course_code) VALUES (?, ?)",
                   [(student_pk, code) for code, _title in COURSES])


def insert_student(db, teacher_id, values, pk=None):
    cursor = db.execute(
        "INSERT INTO students (id, teacher_id, student_id, name, section, batch, email) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pk, teacher_id, *(values[k] for k in ("student_id", "name", "section", "batch", "email"))))
    ensure_records(db, cursor.lastrowid)
    return cursor.lastrowid


def seed_students(db, teacher_id=None):
    """Fictional starter classroom; no passwords or real personal data are seeded."""
    names = ("Aarav Mehta", "Ananya Rao", "Kabir Sethi", "Ishita Verma",
             "Rohan Das", "Diya Nair", "Arjun Kapoor", "Sana Ali",
             "Vivaan Shah", "Meera Joshi", "Aditya Sen", "Tara Iyer",
             "Dev Malhotra", "Nisha Gupta", "Yash Patel", "Zoya Khan")
    attendance = (96, 90, 83, 78, 65, 100, 75, 89, 71, 85, 80, 98, 73, 76, 60, 88)
    performance = (94, 88, 77, 69, 45, 93, 59, 83, 37, 73, 64, 97, 52, 81, 31, 48)
    for index, name in enumerate(names):
        section = "CSE-A" if index < 8 else "CSE-B"
        pk = insert_student(db, teacher_id, {"student_id": f"CSE25{section[-1]}{index % 8 + 1:03}",
                            "name": name, "section": section, "batch": "2025-2029", "email": ""})
        for c, (code, _title) in enumerate(COURSES):
            max_hours = (48, 44, 36, 42, 24, 28, 46)[c]
            attended = min(max_hours, max(0, round(max_hours * (attendance[index] - c % 3) / 100)))
            scores = [max(0, min(cap * 100, round(cap * (performance[index] - c % 4))))
                      for _key, _label, cap in COMPONENTS]
            # A blank final exam represents pending evaluation, not a zero.
            if index in (3, 7, 10) and c in (1, 4):
                scores[-1] = None
            setters = ", ".join(key + " = ?" for key, _label, _cap in COMPONENTS)
            db.execute("UPDATE records SET max_hours = ?, attended_hours = ?, " + setters
                       + " WHERE student_pk = ? AND course_code = ?",
                       (max_hours, attended, *scores, pk, code))


def init_database(db, database_path, seed=True):
    """Upgrade original three-subject DB atomically, with a physical backup first."""
    old_columns = {r[1] for r in db.execute("PRAGMA table_info(students)")}
    legacy = "maths" in old_columns
    legacy_rows = [dict(r) for r in db.execute("SELECT * FROM students")] if legacy else []
    if legacy and database_path != ":memory:":
        backup = str(database_path) + ".v1-backup-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        destination = sqlite3.connect(backup)
        try:
            db.backup(destination)
        finally:
            destination.close()
    try:
        db.execute("BEGIN IMMEDIATE")
        if legacy:
            db.execute("ALTER TABLE students RENAME TO legacy_students_v1")
        schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        # Execute statements inside this transaction. executescript() would commit it.
        for statement in schema.split(";"):
            if statement.strip():
                db.execute(statement)
        teacher_columns = {r[1] for r in db.execute("PRAGMA table_info(teachers)")}
        additions = {
            "faculty_no": "TEXT NOT NULL DEFAULT ''",
            "institution": "TEXT NOT NULL DEFAULT 'SRM Institute of Science and Technology'",
            "campus": "TEXT NOT NULL DEFAULT 'Delhi NCR Campus'",
            "department": "TEXT NOT NULL DEFAULT 'Computer Science and Engineering'",
            "academic_year": "TEXT NOT NULL DEFAULT '2026-2027'",
            "semester": "INTEGER NOT NULL DEFAULT 3",
        }
        for column, definition in additions.items():
            if column not in teacher_columns:
                db.execute("ALTER TABLE teachers ADD COLUMN " + column + " " + definition)
        db.executemany("INSERT OR IGNORE INTO courses VALUES (?, ?, ?)",
                       [(code, title, i) for i, (code, title) in enumerate(COURSES)])
        for old in legacy_rows:
            pk = insert_student(db, old["teacher_id"], {
                "student_id": old["student_id"], "name": old["name"],
                "section": "CSE-A", "batch": "2025-2029", "email": ""}, pk=old["id"])
            db.execute("INSERT INTO legacy_results VALUES (?, ?)", (pk, json.dumps(old)))
        initialized = db.execute("SELECT value FROM app_meta WHERE key = 'portal_v2_initialized'").fetchone()
        if not initialized:
            if not legacy and not db.execute("SELECT 1 FROM students LIMIT 1").fetchone() and seed:
                teachers = db.execute("SELECT id FROM teachers").fetchall()
                for teacher in teachers:
                    seed_students(db, teacher[0])
                if not teachers:
                    seed_students(db)
            db.execute("INSERT INTO app_meta VALUES ('portal_v2_initialized', '1')")
        db.commit()
    except Exception:
        db.rollback()
        raise


def parse_csv(upload, max_bytes=2 * 1024 * 1024):
    if not upload or not upload.filename.lower().endswith(".csv"):
        raise ValueError("Choose a UTF-8 CSV file.")
    data = upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("CSV files must be 2 MB or smaller.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Save the CSV in UTF-8 encoding.") from None
    if "\x00" in text:
        raise ValueError("The file contains invalid text.")
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if reader.fieldnames is None:
        raise ValueError("The CSV is empty.")
    headers = [h.strip().lower() for h in reader.fieldnames]
    if len(headers) != len(set(headers)):
        raise ValueError("Duplicate CSV headers are not allowed.")
    legacy = set(headers) == set(LEGACY_FIELDS)
    expected = LEGACY_FIELDS if legacy else CSV_FIELDS
    if set(headers) != set(expected):
        raise ValueError("CSV headers must be: " + ", ".join(CSV_FIELDS) + ".")
    reader.fieldnames = headers
    rows, seen, profiles = [], set(), {}
    try:
        for raw in reader:
            line = reader.line_num
            if len(rows) >= 1000:
                raise ValueError("Import at most 1,000 course records per CSV.")
            if None in raw or any(v is None for v in raw.values()):
                raise ValueError(f"Line {line}: column count does not match the header.")
            try:
                profile = student_values({**raw, "section": raw.get("section", "CSE-A"),
                                          "batch": raw.get("batch", "2025-2029")})
                key = profile["student_id"]
                if legacy:
                    marks = {k: integer(raw[k], k.title(), 0, 100) for k in ("maths", "science", "english")}
                    legacy_att = mark(raw["attendance"], "Attendance", 100)
                    if legacy_att is None:
                        raise ValueError("Attendance is required.")
                    row = {"profile": profile, "legacy": {**marks, "attendance": legacy_att / 100}}
                else:
                    code = raw["course_code"].strip().upper()
                    if code not in dict(COURSES):
                        raise ValueError("Unknown course code.")
                    maximum = integer(raw["max_hours"], "Max hours")
                    attended = integer(raw["attended_hours"], "Attended hours", 0, maximum)
                    row = {"profile": profile, "course_code": code, "max_hours": maximum,
                           "attended_hours": attended}
                    row.update({k: mark(raw[k], label, cap) for k, label, cap in COMPONENTS})
                    key += "|" + code
                if key in seen:
                    raise ValueError("Duplicate student/course record in this CSV.")
                identity = tuple(profile[k] for k in ("name", "section", "batch"))
                previous = profiles.get(profile["student_id"])
                if previous is not None and previous != identity:
                    raise ValueError("A student's name, section, and batch must agree across all rows.")
                profiles[profile["student_id"]] = identity
                seen.add(key)
                rows.append(row)
            except ValueError as exc:
                raise ValueError(f"Line {line}: {exc}") from None
    except csv.Error as exc:
        raise ValueError(f"Invalid CSV: {exc}") from None
    if not rows:
        raise ValueError("The CSV contains no student rows.")
    return rows


def safe_cell(value):
    text = str(value) if value is not None else ""
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def points(centimarks):
    if centimarks is None:
        return ""
    return format(Decimal(centimarks) / 100, "f").rstrip("0").rstrip(".") if centimarks % 100 else str(centimarks // 100)
