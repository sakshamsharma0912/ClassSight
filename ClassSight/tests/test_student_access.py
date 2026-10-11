"""Exercise role authorization, enrollment and private report scopes through HTTP."""
import csv
import hashlib
import html
import io
import re
import time
from urllib.parse import urlsplit

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader
from werkzeug.security import check_password_hash

from app import create_app, get_db
from test_portal import app, client, Links, post, register, rows, token

STUDENT_PASSWORD = "StudentPass123"


def invite(teacher, pk=1, email="student@example.edu"):
    teacher.get(f"/students/{pk}/access")
    response = post(teacher, f"/students/{pk}/access", {"email": email})
    assert response.status_code == 200
    match = re.search(r'id="activation-link"[^>]*value="([^"]+)"', response.get_data(as_text=True))
    assert match, response.get_data(as_text=True)
    return urlsplit(html.unescape(match[1])).path


def activate(app, activation_path, password=STUDENT_PASSWORD):
    student = app.test_client()
    assert student.get(activation_path).status_code == 200
    response = post(student, activation_path, {"password": password, "confirm_password": password})
    assert response.status_code == 302
    assert response.location.endswith("/student/dashboard")
    student.get("/student/dashboard")
    return student


@pytest.fixture
def student(app, client):
    return activate(app, invite(client))


def student_login(app, email="student@example.edu", password=STUDENT_PASSWORD):
    visitor = app.test_client()
    visitor.get("/login?role=student")
    result = post(visitor, "/login", {"role": "student", "email": email, "password": password})
    assert result.status_code == 302
    assert result.location.endswith("/student/dashboard")
    visitor.get(result.location)
    return visitor


def test_branding_role_selector_and_canonical_dashboard_routes(app, client, student):
    for role in ("teacher", "student"):
        visitor = app.test_client()
        response = visitor.get("/login?role=" + role)
        page = response.get_data(as_text=True)
        assert "ClassSight" in page and "Track performance. Guide progress." in page
        assert f'name="role" value="{role}"' in page
        assert "Student Performance Analyzer" not in page
    for browser, canonical in ((client, "/teacher/dashboard"), (student, "/student/dashboard")):
        assert browser.get("/").location.endswith(canonical)
        assert browser.get("/dashboard").location.endswith(canonical)
        assert browser.get("/login?role=teacher").location.endswith(canonical)
        assert browser.get("/register").location.endswith(canonical)
        assert browser.get(canonical).status_code == 200
    assert client.get("/student/dashboard").status_code == 403
    assert client.get("/student/reports/pdf").status_code == 403


@pytest.mark.parametrize("path", ["/student/dashboard", "/student/settings", "/student/reports", "/student/reports/pdf"])
def test_student_routes_require_student_authentication(app, path):
    response = app.test_client().get(path)
    assert response.status_code == 302
    assert response.location.endswith("/login?role=student")


def test_student_account_is_linked_hashed_and_invitation_is_single_use(app, client):
    path = invite(client)
    secret = path.rsplit("/", 1)[1]
    stored = rows(app, "SELECT * FROM student_invites")[0]
    assert stored["token_hash"] == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in str(stored)
    student = activate(app, path)
    account = rows(app, "SELECT * FROM student_accounts")[0]
    assert account["student_pk"] == 1 and account["password_hash"].startswith("scrypt:")
    assert check_password_hash(account["password_hash"], STUDENT_PASSWORD)
    assert STUDENT_PASSWORD not in account["password_hash"]
    assert rows(app, "SELECT * FROM student_invites") == []
    assert app.test_client().get(path).status_code == 404
    with student.session_transaction() as session:
        assert session["role"] == "student" and "teacher_id" not in session
    assert post(student, "/logout").location.endswith("/login?role=student")
    student_login(app)


@pytest.mark.parametrize("parameters", ["", "?student=2", "?student_pk=2&teacher_id=2", "?section=CSE-B&batch=2024-2028&q=Other&role=teacher"])
def test_student_dashboard_does_not_leak_peer_or_cohort_data(app, student, parameters, monkeypatch):
    import app as app_module
    def reject_cohort_query(*_args, **_kwargs):
        raise AssertionError("Student requests must not query faculty/cohort scopes")
    monkeypatch.setattr(app_module, "scoped_rows", reject_cohort_query)
    students = rows(app, "SELECT * FROM students ORDER BY id")
    response = student.get("/student/dashboard" + parameters)
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert students[0]["name"] in page and students[0]["student_id"] in page
    for peer in students[1:]:
        assert peer["name"] not in page and peer["student_id"] not in page
    for restricted in ("Section rank", "Class average:", "Department reports", "Student directory", "Edit saved marks", 'action="/records/', 'action="/students/'):
        assert restricted not in page
    assert "data-semester-simulator" in page and "data-simulator" in page
    assert "My attendance" in page and "My marks" in page


TEACHER_GET_PATHS = [
    "/teacher/dashboard", "/analytics", "/analytics/export", "/students", "/students/add",
    "/students/1", "/students/2", "/students/1/edit", "/students/1/remove",
    "/records/1/marks", "/records/1/attendance", "/attendance", "/attendance/edit",
    "/attendance/session", "/attendance/sessions/1", "/marks", "/courses", "/import",
    "/csv/template", "/csv/export", "/reports", "/reports/pdf", "/reports/xlsx",
    "/reports/csv", "/warnings", "/warnings/1/download", "/settings", "/students/1/access",
]


@pytest.mark.parametrize("path", TEACHER_GET_PATHS)
def test_every_teacher_read_endpoint_rejects_students(student, path):
    response = student.get(path)
    assert response.status_code == 403
    assert b"My performance" in response.data
    assert b"Return to overview" in response.data


@pytest.mark.parametrize("path", [
    "/students/add", "/students/1/edit", "/students/1/delete", "/records/1/marks",
    "/records/1/attendance", "/attendance/edit", "/attendance/session", "/marks",
    "/import", "/warnings/issue/1", "/settings", "/students/1/access", "/students/1/access/revoke",
])
def test_every_teacher_write_endpoint_rejects_students_without_changing_data(app, student, path):
    before = rows(app)
    response = post(student, path, {"role": "teacher", "student": "2", "teacher_id": "1", "email": "evil@example.edu"})
    assert response.status_code == 403
    assert rows(app) == before


@pytest.mark.parametrize("format", ["pdf", "xlsx", "csv"])
def test_personal_downloads_contain_only_linked_student(app, student, format):
    names = rows(app, "SELECT name, student_id FROM students ORDER BY id")
    response = student.get(f"/student/reports/{format}?student=2&section=CSE-B&role=teacher")
    assert response.status_code == 200
    assert "classsight_student_report_" in response.headers["Content-Disposition"]
    if format == "pdf":
        pdf = PdfReader(io.BytesIO(response.data))
        text = "\n".join(page.extract_text() for page in pdf.pages)
        assert "Student Academic Performance Report" in text
        assert "ClassSight" in text
    elif format == "xlsx":
        workbook = load_workbook(io.BytesIO(response.data))
        text = "\n".join(str(value) for sheet in workbook for row in sheet.values for value in row)
        record_rows = list(workbook["Marks"].values)[1:]
        assert len(record_rows) == 7 and all(row[0] == names[0]["student_id"] for row in record_rows)
    else:
        text = response.data.decode("utf-8-sig")
        data = list(csv.reader(io.StringIO(text)))
        assert len(data[1:-1]) == 7 and all(row[0] == names[0]["student_id"] for row in data[1:-1])
        assert data[-1][0] == "Student summary"
    assert names[0]["name"] in text and names[0]["student_id"] in text
    for peer in names[1:]:
        assert peer["name"] not in text and peer["student_id"] not in text


def test_students_cannot_issue_invites_or_choose_record_at_activation(app, client):
    path = invite(client)
    guest = app.test_client()
    guest.get(path)
    result = post(guest, path, {"password": STUDENT_PASSWORD, "confirm_password": STUDENT_PASSWORD,
                               "student_pk": "2", "email": "different@example.edu", "role": "teacher"})
    assert result.location.endswith("/student/dashboard")
    account = rows(app, "SELECT * FROM student_accounts")[0]
    assert account["student_pk"] == 1 and account["email"] == "student@example.edu"
    assert len(rows(app, "SELECT * FROM teachers")) == 1
    assert len(rows(app, "SELECT * FROM student_accounts")) == 1


def test_invite_expiry_reissue_and_ownership(app, client):
    old = invite(client)
    new = invite(client)
    assert app.test_client().get(old).status_code == 404
    assert app.test_client().get(new).status_code == 200
    outsider = app.test_client()
    register(outsider, "other.teacher@example.edu")
    outsider.get("/teacher/dashboard")
    assert outsider.get("/students/1/access").status_code == 404
    assert post(outsider, "/students/1/access", {"email": "stolen@example.edu"}).status_code == 404
    assert post(outsider, "/students/1/access/revoke").status_code == 404
    with app.app_context():
        get_db().execute("UPDATE student_invites SET expires_at = ?", (int(time.time()) - 1,))
        get_db().commit()
    assert app.test_client().get(new).status_code == 404


def test_revocation_and_deletion_invalidate_existing_sessions(app, client, student):
    another = student_login(app)
    assert post(client, "/students/1/access/revoke").status_code == 302
    for browser in (student, another):
        assert browser.get("/student/dashboard").location.endswith("/login?role=student")
    visitor = app.test_client()
    visitor.get("/login?role=student")
    assert post(visitor, "/login", {"role": "student", "email": "student@example.edu", "password": STUDENT_PASSWORD}).status_code == 400
    student = activate(app, invite(client))
    assert post(client, "/students/1/delete").status_code == 302
    assert rows(app, "SELECT * FROM student_accounts") == []
    assert student.get("/student/dashboard").status_code == 302


def test_reactivation_rotates_password_and_revokes_old_sessions(app, client, student):
    another = student_login(app)
    replacement = activate(app, invite(client), password="ReplacementPass123")
    for browser in (student, another):
        assert browser.get("/student/dashboard").status_code == 302
    assert replacement.get("/student/dashboard").status_code == 200
    student_login(app, password="ReplacementPass123")
    assert len(rows(app, "SELECT * FROM student_accounts")) == 1


def test_student_password_change_is_csrf_protected_and_invalidates_other_sessions(app, student):
    another = student_login(app)
    student.get("/student/settings")
    assert student.post("/student/settings", data={"action": "password"}).status_code == 400
    response = post(student, "/student/settings", {"action": "password", "current_password": STUDENT_PASSWORD,
                    "new_password": "UpdatedStudent123", "confirm_password": "UpdatedStudent123"})
    assert response.location.endswith("/student/settings")
    assert student.get("/student/dashboard").status_code == 200
    assert another.get("/student/dashboard").status_code == 302
    assert check_password_hash(rows(app, "SELECT password_hash FROM student_accounts")[0]["password_hash"], "UpdatedStudent123")


def test_wrong_login_role_and_invalid_roles_do_not_grant_access(app, client, student):
    guest = app.test_client()
    guest.get("/login")
    for data in ({"role": "teacher", "email": "student@example.edu", "password": STUDENT_PASSWORD},
                 {"role": "student", "email": "faculty@example.edu", "password": "FacultyPass123"},
                 {"role": "admin", "email": "faculty@example.edu", "password": "FacultyPass123"}):
        assert post(guest, "/login", data).status_code == 400
    assert guest.get("/teacher/dashboard").status_code == 302
    assert app.test_client().get("/login?role=admin").status_code == 400


def test_failed_activation_does_not_consume_the_link(app, client):
    path = invite(client)
    guest = app.test_client()
    guest.get(path)
    for password, confirmation in (("short", "short"), (STUDENT_PASSWORD, "different")):
        assert post(guest, path, {"password": password, "confirm_password": confirmation}).status_code == 400
        assert rows(app, "SELECT * FROM student_accounts") == []
        assert len(rows(app, "SELECT * FROM student_invites")) == 1
    assert activate(app, path).get("/student/dashboard").status_code == 200


def test_student_login_throttle_is_active(app):
    visitor = app.test_client()
    visitor.get("/login?role=student")
    data = {"role": "student", "email": "missing@student.example", "password": "incorrect"}
    for _ in range(10):
        assert post(visitor, "/login", data).status_code == 400
    assert post(visitor, "/login", data).status_code == 429


def test_student_links_and_assets_are_live_and_read_only(app, student):
    for path in ("/student/dashboard", "/student/settings", "/student/reports"):
        response = student.get(path)
        assert response.status_code == 200
        parser = Links()
        parser.feed(response.get_data(as_text=True))
        for href in parser.links + parser.assets:
            assert href and href != "#"
            target = urlsplit(href)
            if target.path:
                assert student.get(target.path + ("?" + target.query if target.query else "")).status_code == 200, href
        for form in parser.forms:
            action = form.get("action", path)
            assert action == "/logout" or action.startswith("/student/"), action


def test_student_empty_record_scope_never_falls_back_to_a_class(app, student):
    with app.app_context():
        db = get_db()
        db.execute("DELETE FROM records WHERE student_pk = 1")
        db.commit()
    response = student.get("/student/dashboard")
    assert response.status_code == 200
    assert b"No course records yet" in response.data
    assert b"data-semester-simulator" not in response.data
    assert b"#course-attendance" not in response.data
    assert b"#component-marks" not in response.data
    assert b"#overall-goal-seeker" not in response.data
    peer = rows(app, "SELECT name FROM students WHERE id = 2")[0]["name"]
    assert peer not in response.get_data(as_text=True)


def test_account_secret_is_not_in_student_templates(app, student):
    password_hash = rows(app, "SELECT password_hash FROM student_accounts")[0]["password_hash"]
    for path in ("/student/dashboard", "/student/settings", "/student/reports"):
        assert password_hash not in student.get(path).get_data(as_text=True)


def test_invitation_creation_and_activation_reject_missing_csrf(app, client):
    assert client.post("/students/1/access", data={"email": "student@example.edu"}).status_code == 400
    path = invite(client)
    guest = app.test_client()
    guest.get(path)
    assert guest.post(path, data={"password": STUDENT_PASSWORD, "confirm_password": STUDENT_PASSWORD}).status_code == 400
    assert rows(app, "SELECT * FROM student_accounts") == []


def test_duplicate_login_email_cannot_reassign_an_existing_student(app, client, student):
    client.get("/students/2/access")
    response = post(client, "/students/2/access", {"email": "student@example.edu"})
    assert response.status_code == 400
    assert len(rows(app, "SELECT * FROM student_accounts")) == 1
    assert rows(app, "SELECT student_pk FROM student_accounts")[0]["student_pk"] == 1


def test_upgrade_adds_student_auth_tables_without_replacing_faculty_records(app, client):
    original = rows(app)
    with app.app_context():
        get_db().execute("DROP TABLE student_invites")
        get_db().execute("DROP TABLE student_accounts")
        get_db().commit()
    updated = create_app(dict(app.config))
    assert rows(updated) == original
    assert rows(updated, "SELECT * FROM student_accounts") == []
    assert rows(updated, "SELECT * FROM student_invites") == []
    assert len(rows(updated, "SELECT * FROM teachers")) == 1
