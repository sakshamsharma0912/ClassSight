# ClassSight verification

## Results

- **132 Python tests passed**: 64 retained portal/analytics tests plus 68 role-routing, student privacy, enrollment, account/session and personal-report checks.
- **27 JavaScript tests passed**: retained grade boundaries, both goal algorithms and event-driven controls, plus activation-link copying and clipboard-permission fallback.
- Tailwind CSS rebuilt successfully. The compiled stylesheet includes the responsive chart, comparison, heatmap and overall-simulator components, ClassSight role selector and activation-link controls.
- JavaScript syntax checks passed for both controllers and their shared core.
- **46 live HTTP checks passed** against a real Flask process launched from a fresh extraction of the ClassSight ZIP. They verified startup, teacher registration and batch filtering, student activation and later login, each course selector, private graph/report content, faculty endpoint denials, password change, access revocation and all bundled assets. The test server was stopped after verification; its fictional runtime database and secret remain outside the delivered ZIP.


Run the checks with:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --test tests/*.test.cjs
```

## What the checks cover

Analytics distinguish pending components from completed failures; preserve the
first analyzer's 40/50/65 mark and 75/85 attendance thresholds; count unique
students; normalize component averages against their caps; use an evaluated
student denominator for academic pass rate; preserve unrounded grade boundaries;
and assign competition ranks only to fully evaluated students.

The app tests follow local chart, profile, navigation and export links from the
overview, analytics and combined detail pages. Fragment targets and modal IDs
exist; filtered CSV rows match grade, performance and class filters; saved mark
updates change the derived analysis; another faculty's data stays hidden.

The overall simulator validates decimal course totals, never decreases existing
marks or exceeds 100, repairs course totals below 40, and reaches fractional
average targets without relying on displayed rounding. Its live results remain
independent of the selected-course component simulator. Attendance stays fixed,
so a marks plan cannot clear an attendance shortage.

Original Maths/Science/English CSV records retain their own totals, grade scale,
risk status and graph. New university component marks remain pending rather
than being invented from those earlier subject totals.

The existing portal suite checks authentication, CSRF, password hashes, CRUD,
ownership, exact attendance margins/recovery, atomic and stale bulk saves, CSV
validation, PDF/Excel contents, letter/session snapshots, settings, migration
and empty classes.

## Student privacy and enrollment

The tests exercise both canonical dashboard routes and the legacy `/dashboard` redirect. Student requests use only the account-linked student primary key. Changing registration, student, section, batch, teacher or role selectors cannot widen that scope. Student render tests explicitly reject cohort-query helpers, class averages, section ranks, peer names and peer registration numbers.

Every teacher read endpoint and every teacher write endpoint is exercised as a student, including profile/record forms, class sessions, analytics, CSV, faculty reports, warning letters, settings and access provisioning. They return 403 before faculty queries or writes. Personal PDF, Excel and CSV downloads are inspected for exactly the student's course records and the absence of peer identities.

Enrollment checks include teacher ownership, CSRF, token hashing, expiry, replacement, single use, invalid-password retry, forged activation fields, duplicate emails, scrypt passwords, wrong login role, login throttling, password-session invalidation, access revocation, roster deletion and upgrades that preserve faculty records. Student links/assets and academic read-only forms are followed; an empty personal record scope never falls back to a class view.

## Limits

No real-browser layout or interactive session was available in this environment.
The responsive institutional design is retained and extended; JavaScript
controllers were exercised using event-driven DOM fixtures, and routes/templates
were checked through Flask's actual test client. Review desktop and mobile
layout in the browser you use for the presentation.

This is a local academic application, with no connection to official SRM SSO or
live university data. Sample students are fictional. No private runtime database,
faculty credentials or signing secrets are included in the source archive.

## GitHub-ready packaging

The GitHub-ready copy preserves all previously verified application, template,
asset, schema, dependency and test bytes. Only README/verification guidance,
.gitignore and GITHUB_UPDATE.md differ. Archive integrity, Python source syntax,
file count/size and excluded runtime paths were checked when packaging. No new
application behavior was introduced and the prior test results were reused.
