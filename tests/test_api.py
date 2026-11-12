from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

CATALOG = b'''<table><tr><th>Course Code</th><th>Title</th><th>Credits</th><th>Prerequisites</th><th>Cross-listed</th></tr>
<tr><td>COSC-4426</td><td>Capstone</td><td>3</td><td>COSC-3127</td><td></td></tr>
<tr><td>ITEC-3506</td><td>Web</td><td>3</td><td>None</td><td>COSC-3506</td></tr>
<tr><td>COSC-3506</td><td>Software</td><td>3</td><td>None</td><td>ITEC-3506</td></tr>
<tr><td>COSC-2406</td><td>Data</td><td>3</td><td>None</td><td></td></tr></table>'''
TRANSCRIPT = b'''<table><tr><th>Status</th><th>Course</th><th></th><th>Grade</th><th>Term</th><th>Credits</th></tr>
<tr><td>Attempted</td><td>COSC-1701</td><td>Intro</td><td>45</td><td>25F</td><td>3</td></tr>
<tr><td>Completed</td><td>COSC-1701</td><td>Intro</td><td>68</td><td>26W</td><td>3</td></tr>
<tr><td>Completed</td><td>COSC-3506</td><td>Software</td><td>75</td><td>26W</td><td>3</td></tr>
<tr><td>Completed</td><td>MATH-1056</td><td>Math</td><td>72</td><td>25W</td><td>3</td></tr></table>'''


def setup_function():
    main.students.clear()
    main.catalog.clear()


def test_health_and_not_found():
    assert client.get('/').json()['status'] == 'ok'
    assert client.get('/api/v1/students/no/profile').status_code == 404


def test_catalog_history_plan_and_audit():
    assert client.post('/api/v1/admin/catalog/import', files={'file': ('catalog.html', CATALOG, 'text/html')}).status_code == 201
    assert client.post('/api/v1/students/770001/history/import', files={'file': ('transcript.html', TRANSCRIPT, 'text/html')}).status_code == 201
    plan = {'planned_courses': [
        {'course_code': 'COSC 4426', 'term': '26F'},
        {'course_code': 'ITEC-3506', 'term': '26F'},
        {'course_code': 'COSC-2406', 'term': '26F'}]}
    assert client.post('/api/v1/students/770001/plan', json=plan).status_code == 200
    report = client.get('/api/v1/students/770001/audit-report').json()
    assert report['status'] == 'warning'
    assert report['credit_summary'] == {'total_earned': 9, 'total_planned': 9, 'total_remaining_for_graduation': 102}
    assert report['timeline_validation'][0]['errors'][0]['type'] == 'MISSING_PREREQUISITE'
    assert report['cross_list_violations'][0]['type'] == 'CROSS_LIST_CONFLICT'
    assert client.get('/api/v1/students/770001/audit-report?strict=true').json()['status'] == 'failed'


def test_history_plan_crud_and_clean_audit():
    client.post('/api/v1/admin/catalog/import', files={'file': ('catalog.html', CATALOG, 'text/html')})
    client.post('/api/v1/students/x/history/import', files={'file': ('t.html', TRANSCRIPT, 'text/html')})
    assert client.get('/api/v1/students/x/profile').status_code == 200
    assert client.put('/api/v1/students/x/history', json={'history': [
        {'course_code': 'COSC-3127', 'term': '25F', 'credits_earned': 3, 'status': 'Completed'}]}).status_code == 200
    assert client.put('/api/v1/students/x/plan', json={'planned_courses': [
        {'course_code': 'COSC-4426', 'term': '26F'}]}).status_code == 200
    report = client.get('/api/v1/students/x/audit-report').json()
    assert report['status'] == 'ok'
    assert report['credit_summary']['total_earned'] == 3
    assert client.delete('/api/v1/students/x/plan').status_code == 200
    assert client.delete('/api/v1/students/x/history').status_code == 200


def test_helpers_and_catalog_edge_cases():
    assert main.normalize_code('cosc 3506') == 'COSC3506'
    assert main.term_key('23F') < main.term_key('24W') < main.term_key('24F')
    assert main.term_key('26SP') < main.term_key('26F')
    assert main.parse_code_list('None') == []
    assert main.parse_code_list('COSC-1; ITEC-2') == ['COSC-1', 'ITEC-2']
    assert main.parse_credits('3 credits') == 3
    assert main.parse_credits('unknown') == 0
    assert main.grade_rank('85') > main.grade_rank('B')
    assert main.extract_history('<html></html>') == []
    assert main.extract_catalog('<html></html>') == {}
