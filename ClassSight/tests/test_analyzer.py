import csv
import io
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest
from analyzer import analyze, original_result, select_students, student_profile
from app import create_app, get_db
from portal_core import COMPONENTS, COURSES, enrich

def course(pk=1, code=COURSES[0][0], score=80, attendance=90, pending=False):
    row = {"id": pk*10, "student_pk":pk, "student_id":f"TEST{pk}", "name":f"Student {pk}",
           "section":"CSE-A", "batch":"2025-2029", "course_code":code,
           "course_title":dict(COURSES)[code], "max_hours":100, "attended_hours":attendance}
    row.update({key:round(cap*score) for key,_label,cap in COMPONENTS})
    if pending: row["university_final"]=None
    return enrich(row)

def test_pending_marks_never_become_a_failed_course_or_final_grade():
    profile=student_profile([course(score=85),course(code=COURSES[1][0],score=30,pending=True)])
    assert profile["average"]==85
    assert profile["grade"]=="Pending" and profile["status"]=="Pending"
    assert not profile["failed_courses"] and not profile["passed"]
    result=analyze(profile["records"])
    assert result["pass_rate"] is None and sum(result["grade_counts"].values())==0

def test_an_eligible_weighted_average_does_not_hide_a_course_shortage():
    profile=student_profile([course(attendance=74),course(code=COURSES[1][0],attendance=100)])
    assert profile["summary"]["attendance_pct"]==87
    assert profile["status"]=="At Risk" and len(profile["shortage_courses"])==1
    assert profile["passed"]

@pytest.mark.parametrize("score,attendance,status",[(39,95,"At Risk"),(50,95,"Watchlist"),(80,75,"Watchlist"),(80,80,"Watchlist"),(80,85,"On Track"),(80,74,"At Risk")])
def test_risk_policy_combines_academics_with_course_attendance(score,attendance,status):
    assert student_profile([course(score=score,attendance=attendance)])["status"]==status

def test_unique_students_pass_denominator_grades_and_competition_ranks():
    result=analyze([course(pk=1,score=90),course(pk=1,code=COURSES[1][0],score=90),
                    course(pk=2,score=90),course(pk=3,score=39),course(pk=4,pending=True)])
    assert result["summary"]["students"]==4 and result["evaluated_students"]==3
    assert result["pass_rate"]==pytest.approx(200/3)
    assert result["grade_counts"]["O"]==2 and result["grade_counts"]["F"]==1
    assert [p["rank"] for p in result["students"]]==[1,1,3,None]

def test_component_percentages_use_component_caps_and_exclude_pending_values():
    result=analyze([course(score=80),course(pk=2,score=60,pending=True)])
    components=result["courses"][0]["components"]
    assert components[0]["average"]==3.5 and components[0]["percentage"]==70
    assert components[-1]["count"]==1 and components[-1]["percentage"]==80

def test_overall_grade_uses_unrounded_average():
    first,second=course(score=80),course(code=COURSES[1][0],score=80)
    first["assignment_1"]-=1
    profile=student_profile([enrich(first),second])
    assert profile["average"]==79.995 and profile["grade"]=="A"

def test_empty_analytics_and_invalid_filters_are_safe():
    result=analyze([])
    assert result["pass_rate"] is None and result["summary"]["average"] is None
    assert select_students([])==[]
    for kwargs in ({"grade":"INVALID"},{"performance":"INVALID"},{"order":"DROP TABLE students"}):
        with pytest.raises(ValueError):select_students([],**kwargs)

def test_original_three_subject_analysis_keeps_its_original_grade_and_risk_policy():
    result=original_result({'maths':95,'science':92,'english':94,'attendance':96})
    assert result['total']==281 and result['percentage']==pytest.approx(281/3)
    assert result['grade']=='A+' and result['status']=='On Track'
    assert original_result({'maths':49,'science':49,'english':49,'attendance':96})['status']=='At Risk'
    assert original_result({'maths':64,'science':64,'english':64,'attendance':84})['status']=='Watchlist'

@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING":True,"DATABASE":str(tmp_path/'analyzer.sqlite3'),"SECRET_KEY":"analyzer-test-key"*4})

def signup(client,email="analyzer@example.edu"):
    client.get('/register')
    with client.session_transaction() as session:token=session['_csrf_token']
    response=client.post('/register',data={'csrf_token':token,'name':'Analyzer Faculty','email':email,
                         'password':'AnalyzerPass123','confirm_password':'AnalyzerPass123'})
    assert response.status_code==302

@pytest.fixture
def client(app):
    client=app.test_client();signup(client)
    return client

class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.ids=set();self.triggers=set();self.ids_seen=[];self.sliders=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.add(attrs['id']);self.ids_seen.append(attrs['id'])
        if 'data-dialog' in attrs:self.triggers.add(attrs['data-dialog'])
        if tag=='a':self.links.append(attrs.get('href',''))
        if tag=='input' and attrs.get('type')=='range':self.sliders.append(attrs)

def test_new_routes_require_login(app):
    for route in ('/analytics','/analytics/export','/teacher/dashboard','/students/1'):
        assert app.test_client().get(route).location.endswith('/login')

def test_chart_filters_export_and_profile_navigation_are_live(client):
    for path in ('/teacher/dashboard','/analytics','/analytics?section=CSE-A','/analytics?grade=O',
                 '/analytics?performance=At+Risk&order=lowest','/students/1'):
        response=client.get(path)
        assert response.status_code==200
        parser=Page();parser.feed(response.get_data(as_text=True))
        assert len(parser.ids_seen)==len(set(parser.ids_seen))
        assert parser.triggers<=parser.ids
        for link in parser.links:
            target=urlsplit(link)
            if target.scheme or target.netloc:continue
            destination=client.get(target.path+'?'+target.query if target.path else path.split('?')[0])
            assert destination.status_code==200,(path,link,destination.status_code)
            if target.fragment:
                other=Page();other.feed(destination.get_data(as_text=True))
                assert target.fragment in other.ids,(path,link)

def test_combined_detail_has_two_independent_simulators(client):
    response=client.get('/students/1')
    page=Page();page.feed(response.get_data(as_text=True))
    assert len(page.sliders)==14
    assert [int(x['max']) for x in page.sliders if 'data-key' in x]==[5,5,15,10,10,15,40]
    assert sum('data-course-baseline' in x for x in page.sliders)==7
    assert {'student-analysis','overall-goal-seeker','goal-seeker','course-attendance'}<=page.ids

def test_legacy_csv_renders_original_charts_without_inventing_university_marks(app,client):
    client.get('/import')
    with client.session_transaction() as session:token=session['_csrf_token']
    csv_data=b'student_id,name,maths,science,english,attendance\nLEGACY01,Original Student,50,60,70,80\n'
    response=client.post('/import',data={'csrf_token':token,'file':(io.BytesIO(csv_data),'original.csv')},content_type='multipart/form-data')
    assert response.status_code==302
    with app.app_context():pk=get_db().execute('SELECT id FROM students WHERE student_id=?',('LEGACY01',)).fetchone()[0]
    response=client.get(f'/students/{pk}')
    body=response.get_data(as_text=True)
    assert response.status_code==200 and 'Original three-subject analysis' in body
    assert '60.00%' in body and 'Original letter grade' in body and 'Maths' in body
    assert '0/7 courses evaluated' in body
    with app.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM records WHERE student_pk=? AND university_final IS NOT NULL',(pk,)).fetchone()[0]==0

def test_export_matches_selected_grade_status_and_class_scope(client):
    for query in ('section=CSE-A','section=CSE-B&grade=F','performance=At+Risk','grade=Pending','q=missingstudent'):
        response=client.get('/analytics/export?'+query)
        assert response.status_code==200 and 'attachment' in response.headers['Content-Disposition']
        data=list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))
        if 'section=CSE-A' in query:assert len(data)==8 and all(row['section']=='CSE-A' for row in data)
        if 'grade=F' in query:assert data and all(row['overall_grade']=='F' for row in data)
        if 'performance=At+Risk' in query:assert data and all(row['performance_status']=='At Risk' for row in data)
        if 'grade=Pending' in query:assert data and all(row['rank']=='' and row['overall_grade']=='Pending' for row in data)
        if 'q=missingstudent' in query:assert not data

def test_chart_statistics_update_after_saved_mark_edit(app,client):
    with app.app_context():
        db=get_db();db.execute('UPDATE records SET '+','.join(key+'=0' for key,_label,_cap in COMPONENTS)+' WHERE student_pk=1');db.commit()
    data=list(csv.DictReader(io.StringIO(client.get('/analytics/export?grade=F').data.decode('utf-8-sig'))))
    assert any(row['student_id']=='CSE25A001' and row['evaluated_average']=='0.00' for row in data)
    assert 'At Risk' in client.get('/students/1').get_data(as_text=True)

def test_analytics_never_exposes_another_faculty_workspace(app,client):
    second=app.test_client();signup(second,'second@example.edu')
    with app.app_context():
        db=get_db();second_id=db.execute('SELECT id FROM teachers WHERE email=?',('second@example.edu',)).fetchone()[0]
        db.execute('UPDATE students SET name=? WHERE teacher_id=?',('Private Second Faculty Student',second_id));db.commit()
    assert b'Private Second Faculty Student' not in client.get('/analytics').data
    assert b'Private Second Faculty Student' not in client.get('/analytics/export').data

@pytest.mark.parametrize('query',['grade=INVALID','performance=INVALID','order=INVALID','course=INVALID'])
def test_invalid_analyzer_filters_are_rejected(client,query):
    assert client.get('/analytics?'+query).status_code==400
    assert client.get('/analytics/export?'+query).status_code==400
