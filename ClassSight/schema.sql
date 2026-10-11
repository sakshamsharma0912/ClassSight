CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    faculty_no TEXT NOT NULL DEFAULT '',
    institution TEXT NOT NULL DEFAULT 'SRM Institute of Science and Technology',
    campus TEXT NOT NULL DEFAULT 'Delhi NCR Campus',
    department TEXT NOT NULL DEFAULT 'Computer Science and Engineering',
    academic_year TEXT NOT NULL DEFAULT '2026-2027',
    semester INTEGER NOT NULL DEFAULT 3 CHECK (semester BETWEEN 1 AND 12)
);
CREATE TABLE IF NOT EXISTS courses (
    code TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    position INTEGER NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER REFERENCES teachers(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL,
    name TEXT NOT NULL,
    section TEXT NOT NULL,
    batch TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (teacher_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_portal_students_scope ON students(teacher_id, section, batch);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_pk INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    course_code TEXT NOT NULL REFERENCES courses(code),
    max_hours INTEGER NOT NULL DEFAULT 0 CHECK (max_hours BETWEEN 0 AND 10000),
    attended_hours INTEGER NOT NULL DEFAULT 0 CHECK (attended_hours BETWEEN 0 AND max_hours),
    assignment_1 INTEGER CHECK (assignment_1 BETWEEN 0 AND 500),
    assignment_2 INTEGER CHECK (assignment_2 BETWEEN 0 AND 500),
    internal_exam_1 INTEGER CHECK (internal_exam_1 BETWEEN 0 AND 1500),
    mini_project INTEGER CHECK (mini_project BETWEEN 0 AND 1000),
    practical INTEGER CHECK (practical BETWEEN 0 AND 1000),
    internal_exam_2 INTEGER CHECK (internal_exam_2 BETWEEN 0 AND 1500),
    university_final INTEGER CHECK (university_final BETWEEN 0 AND 4000),
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_pk, course_code)
);
CREATE TABLE IF NOT EXISTS legacy_results (
    student_pk INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    source_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS student_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_pk INTEGER NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    auth_version INTEGER NOT NULL DEFAULT 1 CHECK (auth_version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS student_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_pk INTEGER NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
    email TEXT NOT NULL COLLATE NOCASE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS attendance_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    course_code TEXT NOT NULL REFERENCES courses(code),
    section TEXT NOT NULL,
    batch TEXT NOT NULL,
    held_on TEXT NOT NULL,
    hours INTEGER NOT NULL CHECK (hours BETWEEN 1 AND 12),
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS warning_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    student_pk INTEGER REFERENCES students(id) ON DELETE SET NULL,
    snapshot_json TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    reference TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (
    key TEXT PRIMARY KEY, failures INTEGER NOT NULL, started REAL NOT NULL
);
