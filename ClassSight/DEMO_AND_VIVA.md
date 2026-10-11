# ClassSight demonstration and viva guide

## Presentation sequence

1. Launch run.bat and register a faculty account. Introduce ClassSight: “Track performance. Guide progress.” Explain the separate teacher and student workspaces.
2. Open Performance overview. Show class averages, academic pass rate, unique
   at-risk students, subject performance, grade distribution and student results.
3. Open Performance analytics, filter CSE-A and the batch, then select a grade bar.
   Explain the scatter plot, section comparison and normalized component heatmap.
4. Sort student results by lowest score, inspect risk reasons and export the filtered
   performance CSV. Explain that pending marks do not become failures or final grades.
5. Open a student profile. Compare saved scores with section averages and show the
   strongest course, improvement opportunity, overall grade and section rank.
6. Move overall course sliders. Show live average, grade, academic pass, status and
   change from baseline. Apply a balanced 80% plan, then reset. Nothing is saved.
7. Use the selected-course component simulator. Point out all seven component caps,
   the final-exam target, impossible targets and the fixed attendance condition.
8. Open Edit saved marks, save a real change, and confirm that charts recalculate.
9. Open Attendance and show max, attended, absent, signed margin and future recovery.
   Record a two-hour class session and show its preserved snapshot.
10. Issue a shortage notice, download it, and export a department PDF/Excel report.
11. Import examples/additional_course_records.csv, then add/edit/remove a student.
    An older six-column subject CSV produces a preserved original-result chart.
12. From a student profile, open Student access and issue an activation link. Open it in a private browser, choose a student password, and show the private student dashboard with both simulators and personal downloads.
13. Demonstrate that `/teacher/dashboard` and faculty editing/export URLs return 403 for a student. Revoke the student login and confirm the session is signed out.
14. Sign out and register another teacher account to demonstrate isolated faculty workspaces.

## Explain attendance precisely

74 attended of 100 conducted gives absent 26, required 75 and current margin −1.
Four consecutive attended hours are required: 78/104 = exactly 75%.

90 attended of 100 conducted gives current margin +15. Twenty additional
hours may be missed: 90/120 = exactly 75%.

Current shortage and future allowance use different denominators. Eligibility
uses integer comparisons before display rounding and is checked per course.

## Likely viva questions

| Question | Answer |
|---|---|
| Why two dashboards? | Teachers need batch-level insights; students should access only their own performance and attendance. |
| How is student access restricted? | A teacher-issued, single-use activation link creates an account tied to one roster primary key. Server-side role checks block faculty routes, and personal queries use that linked key. |
| Can changing a URL show another student? | No; student record selectors are never used as authorization. Class averages and ranks stay in teacher views. |
| What makes this an analyzer? | It derives class averages, grades, pass rates, risk flags, rankings, course comparisons and improvement scenarios from stored records. |
| What was combined? | The first project's student analysis and balanced subject simulation, with the newer portal's university data model, light UI, attendance, marks and reports. |
| Why Flask? | Straightforward Python routes, sessions, requests and Jinja templates. |
| Why SQLite? | Local operation without a separate database service, with transactions, foreign keys and constraints. |
| How are marks stored? | Integer centimarks with exact component caps; unassessed values are NULL. |
| How is attendance stored? | Whole conducted and attended hours per student/course; absent hours and margins are derived. |
| Is class attendance a simple average? | No; sum of attended student-hours divided by conducted student-hours. |
| Can overall attendance clear a shortage? | No; the minimum is checked individually per course. |
| Can another faculty use a known student ID? | Ownership is checked by the session faculty ID; foreign records return 404. |
| Why CSRF? | To protect authenticated mutations from forms submitted by another origin. |
| Are passwords plaintext? | No; Werkzeug scrypt hashes are stored and verified. |
| One CSV row is invalid — what happens? | Validation and a transaction ensure no changes are saved. |
| How do two open forms avoid overwriting? | A record version rejects stale saves atomically. |
| What do the two simulators do? | One plans course totals together; the other plans seven components within one course. Both are temporary and keep attendance fixed. |
| How is the improvement plan balanced? | It adds centimarks to the weakest courses, keeps existing stronger marks, respects 100, and brings every course to at least 40. |
| Is overall percentage a GPA? | No; each course is out of 100 and receives equal weight. GPA needs actual course credits and a separately defined policy. |
| Are all students included in pass rate? | Only students with every selected course fully evaluated. Pending records are shown separately. |
| How do ties affect rank? | Competition ranking: equal averages share rank and the next rank skips those positions. |
| What does the simulator save? | Nothing; explicit marks forms persist actual evaluation values. |
| Does a blank final mean zero? | No; the grade remains Pending until all components are entered. |
| Does upgrading lose original marks? | No; the old DB is backed up and results archived. Real university components cannot be inferred, so new records start blank. |
| Is this the actual SRM SSO portal? | No; it is an independent local academic project using verified course references. |
| Are these weightings universal SRM policy? | No; they are the exact assessment scheme requested for the project. |
| How are downloads made? | ReportLab PDFs and openpyxl workbooks use the same scoped records as the UI. |
| Why snapshot letters? | An issued document must keep the attendance recorded at issue time. |

## Verification

Run `python -m pytest -q` and `node --test tests/*.test.cjs`.
See VERIFICATION.md for test counts, link checks and verification limits.
Node is optional for ordinary use. Check the responsive UI in your presentation
browser; a real browser was unavailable in the build environment.
