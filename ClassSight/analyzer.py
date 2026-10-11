"""Student-focused analytics over the portal's owner-scoped course records.

Pending evaluations are never treated as failed marks. Every course is out of
100; the overall average is an equal-course average, not a credit-weighted GPA.
"""
from collections import Counter, defaultdict
from fractions import Fraction
from decimal import Decimal

from portal_core import COMPONENTS, COURSES, GRADES, grade_for, summarize

STATES = ("At Risk", "Watchlist", "On Track", "Pending")


def student_profile(records):
    complete = [row for row in records if row["complete"]]
    totals = [sum(row[key] for key, _label, _cap in COMPONENTS) for row in complete]
    mean = Fraction(sum(totals), len(totals)) if totals else None
    academic_failures = [row for row in complete if row["grade"] == "F"]
    shortages = [row for row in records if row["attendance_status"] == "Below 75%"]
    near_minimum = [row for row in records if row["max_hours"] and
                    3 * row["max_hours"] <= 4 * row["attended_hours"] and
                    20 * row["attended_hours"] < 17 * row["max_hours"]]
    fully_evaluated = bool(records) and len(complete) == len(records)
    reasons = []
    if academic_failures:
        reasons.append(f'{len(academic_failures)} course(s) below 40 marks')
    if shortages:
        reasons.append(f'{len(shortages)} course(s) below 75% attendance')
    if mean is not None and mean < 5000:
        reasons.append("Evaluated average below 50 marks")
    if reasons:
        status = "At Risk"
    elif near_minimum or (mean is not None and mean < 6500):
        status = "Watchlist"
        if near_minimum:
            reasons.append("Attendance buffer below 85% in at least one course")
        if mean is not None and mean < 6500:
            reasons.append("Evaluated average below 65 marks")
    elif not fully_evaluated or any(not row["max_hours"] for row in records):
        status = "Pending"
        reasons.append("Awaiting complete marks or attendance records")
    else:
        status = "On Track"
        reasons.append("All courses meet the academic and attendance thresholds")
    strongest = max(complete, key=lambda row: row["total"], default=None)
    weakest = min(complete, key=lambda row: row["total"], default=None)
    return {
        "student": records[0] if records else None, "records": records,
        "summary": summarize(records), "average": float(mean / 100) if mean is not None else None,
        "grade": grade_for(mean) if fully_evaluated else "Pending",
        "fully_evaluated": fully_evaluated, "complete_count": len(complete),
        "course_count": len(records), "passed": fully_evaluated and not academic_failures,
        "failed_courses": academic_failures, "shortage_courses": shortages,
        "status": status, "reasons": reasons, "strongest": strongest,
        "weakest": weakest, "rank": None,
    }


def analyze(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["student_pk"]].append(row)
    students = [student_profile(records) for records in groups.values()]
    evaluated = [student for student in students if student["fully_evaluated"]]
    # Competition ranking; tied averages receive the same rank.
    for student in evaluated:
        student["rank"] = 1 + sum(other["average"] > student["average"] for other in evaluated)
    courses = []
    for code, title in COURSES:
        course_rows = [row for row in rows if row["course_code"] == code]
        if not course_rows:
            continue
        component_data = []
        for key, label, cap in COMPONENTS:
            values = [row[key] for row in course_rows if row[key] is not None]
            component_data.append({"key": key, "label": label, "cap": cap,
                                   "count": len(values),
                                   "average": sum(values) / (100 * len(values)) if values else None,
                                   "percentage": sum(values) / (cap * len(values)) if values else None})
        completed = [row for row in course_rows if row["complete"]]
        courses.append({"code": code, "title": title, **summarize(course_rows),
                        "pass_rate": 100 * sum(row["grade"] != "F" for row in completed) / len(completed) if completed else None,
                        "components": component_data})
    grade_counts = {grade: sum(student["grade"] == grade for student in evaluated) for grade, _minimum in GRADES}
    states = Counter(student["status"] for student in students)
    cohorts = []
    for section, batch in sorted({(row["section"], row["batch"]) for row in rows}):
        group = [student for student in students if student["student"]["section"] == section and student["student"]["batch"] == batch]
        finished = [student for student in group if student["fully_evaluated"]]
        group_rows = [row for row in rows if row["section"] == section and row["batch"] == batch]
        cohorts.append({"section": section, "batch": batch, "students": len(group),
                        "average": sum(student["average"] for student in finished) / len(finished) if finished else None,
                        "evaluated": len(finished), "at_risk": sum(student["status"] == "At Risk" for student in group),
                        "attendance": summarize(group_rows)["attendance_pct"]})
    priority = sorted((student for student in students if student["status"] in ("At Risk", "Watchlist")),
                      key=lambda student: (student["status"] != "At Risk",
                                           student["average"] if student["average"] is not None else 101,
                                           student["student"]["student_id"]))
    return {"students": students, "courses": courses, "summary": summarize(rows),
            "evaluated_students": len(evaluated), "passed": sum(student["passed"] for student in evaluated),
            "pass_rate": 100 * sum(student["passed"] for student in evaluated) / len(evaluated) if evaluated else None,
            "grade_counts": grade_counts, "max_grade_count": max(grade_counts.values(), default=0) or 1,
            "states": {state: states[state] for state in STATES}, "priority": priority,
            "cohorts": cohorts, "pending_students": len(students) - len(evaluated)}


def select_students(students, grade="", performance="", order="name"):
    if grade not in ("", "Pending", *(grade for grade, _minimum in GRADES)):
        raise ValueError("Select a valid result grade.")
    if performance not in ("", *STATES):
        raise ValueError("Select a valid performance status.")
    if order not in ("name", "highest", "lowest", "attendance"):
        raise ValueError("Select a valid performance sort order.")
    result = [student for student in students if (not grade or student["grade"] == grade) and
              (not performance or student["status"] == performance)]
    def sort_key(student):
        average = student["average"]
        if order == "highest": return (average is None, -(average or 0), student["student"]["name"])
        if order == "lowest": return (average is None, average or 0, student["student"]["name"])
        if order == "attendance":
            attendance = student["summary"]["attendance_pct"]
            return (attendance is None, attendance or 0, student["student"]["name"])
        return (student["student"]["name"].casefold(), student["student"]["student_id"])
    return sorted(result, key=sort_key)


def original_result(data):
    """Reconstruct the original analyzer result for a migrated/imported archive."""
    marks = [Decimal(str(data[subject])) for subject in ("maths", "science", "english")]
    attendance = Decimal(str(data["attendance"]))
    percentage = sum(marks) / 3
    bands = (("A+",90),("A",80),("B",70),("C",60),("D",50),("E",40),("F",0))
    status = ("At Risk" if min(marks) < 40 or percentage < 50 or attendance < 75 else
              "Watchlist" if percentage < 65 or attendance < 85 else "On Track")
    return {"subjects": list(zip(("Maths","Science","English"),map(float,marks))),
            "total":float(sum(marks)), "percentage":float(percentage),
            "grade":next(label for label,minimum in bands if percentage>=minimum),
            "status":status, "attendance":float(attendance)}
