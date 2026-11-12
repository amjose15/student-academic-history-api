from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from typing import Any
import re

app = FastAPI(title="Student Academic History API")
students: dict[str, dict[str, Any]] = {}
catalog: dict[str, dict[str, Any]] = {}


class HistoryItem(BaseModel):
    course_code: str
    term: str
    credits_earned: int = 0
    status: str


class HistoryUpdate(BaseModel):
    history: list[HistoryItem]


class PlannedCourse(BaseModel):
    course_code: str
    term: str


class PlanUpdate(BaseModel):
    planned_courses: list[PlannedCourse]


def normalize_code(code: str) -> str:
    return re.sub(r"[\s-]", "", str(code or "")).upper()


def term_key(term: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{2})(W|SP|S|F)", str(term).strip().upper())
    if not match:
        # Unknown formats sort before valid terms, deterministically.
        return (-1, -1)
    return (int(match.group(1)), {"W": 0, "SP": 1, "S": 2, "F": 3}[match.group(2)])


def clean_text(cell):
    return " ".join(cell.stripped_strings).strip()


def header_key(value):
    return re.sub(r"[^a-z]", "", value.lower())


def grade_rank(grade):
    value = (grade or "").strip()
    if not value:
        return (0, 0)
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", value):
        return (4, float(value.rstrip("%")))
    if re.fullmatch(r"[A-F][+-]?", value.upper()):
        return (3, 0)
    if value.upper() == "P":
        return (2, 0)
    return (1, 0)


def parse_credits(value):
    match = re.search(r"-?\d+", str(value).strip())
    return int(match.group()) if match else 0


def extract_history(html):
    soup = BeautifulSoup(html, "html.parser")
    chosen = {}
    allowed = {"completed", "in-progress", "attempted"}
    for table in soup.find_all("table"):
        column_map = {}
        header_row = None
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            labels = [header_key(clean_text(c)) for c in cells]
            if all(x in labels for x in ("status", "course", "term", "credits")):
                header_row = row
                for i, label in enumerate(labels):
                    if label in ("status", "course", "grade", "term", "credits"):
                        column_map[label] = i
                break
        if header_row is None:
            continue
        for row in table.find_all("tr"):
            if row is header_row:
                continue
            cells = row.find_all(["th", "td"], recursive=False)
            required = max(column_map[k] for k in ("status", "course", "term", "credits"))
            if len(cells) <= required:
                continue
            status = clean_text(cells[column_map["status"]])
            course = clean_text(cells[column_map["course"]])
            term = clean_text(cells[column_map["term"]])
            credits = parse_credits(clean_text(cells[column_map["credits"]]))
            gi = column_map.get("grade")
            grade = clean_text(cells[gi]) if gi is not None and gi < len(cells) else ""
            if status.lower() not in allowed or not course or not term:
                continue
            record = {"course_code": course, "term": term, "credits_earned": credits, "status": status}
            key = (normalize_code(course), term.strip().upper())
            score = (grade_rank(grade), credits)
            if key not in chosen or score > chosen[key][0]:
                chosen[key] = (score, record)
    return [item[1] for item in chosen.values()]


def parse_code_list(value: str) -> list[str]:
    if not value or value.strip().lower() in {"none", "n/a", "-", "nil"}:
        return []
    # Catalogs commonly delimit multiple codes with commas, semicolons, or line breaks.
    parts = re.split(r"[,;\n]+", value)
    return [p.strip() for p in parts if p.strip() and p.strip().lower() not in {"none", "n/a", "-", "nil"}]


def extract_catalog(html: str) -> dict[str, dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    result = {}
    for table in soup.find_all("table"):
        mapping = {}
        header = None
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            labels = [header_key(clean_text(c)) for c in cells]
            code_idx = next((i for i, x in enumerate(labels) if x in {"coursecode", "code", "course"}), None)
            credit_idx = next((i for i, x in enumerate(labels) if x in {"credits", "credit", "creditvalue"}), None)
            if code_idx is not None and credit_idx is not None:
                header = row
                mapping["code"] = code_idx
                mapping["credits"] = credit_idx
                for i, label in enumerate(labels):
                    if "prereq" in label:
                        mapping["prerequisites"] = i
                    if "crosslist" in label or "crosslisted" in label:
                        mapping["cross_listed"] = i
                break
        if header is None:
            continue
        for row in table.find_all("tr"):
            if row is header:
                continue
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) <= max(mapping.values()):
                continue
            code = clean_text(cells[mapping["code"]])
            key = normalize_code(code)
            if not key:
                continue
            prereqs = parse_code_list(clean_text(cells[mapping["prerequisites"]])) if "prerequisites" in mapping else []
            cross = parse_code_list(clean_text(cells[mapping["cross_listed"]])) if "cross_listed" in mapping else []
            result[key] = {
                "course_code": code,
                "credits": parse_credits(clean_text(cells[mapping["credits"]])),
                "prerequisites": prereqs,
                "cross_listed": cross,
            }
    return result


def require_student(student_id):
    if student_id not in students:
        raise HTTPException(status_code=404, detail="Student not found")
    return students[student_id]


@app.get("/")
def root():
    return {"status": "ok", "service": "student-academic-history-api"}


@app.post("/api/v1/admin/catalog/import", status_code=201)
async def import_catalog(file: UploadFile = File(...)):
    global catalog
    catalog = extract_catalog((await file.read()).decode("utf-8", errors="replace"))
    return {"status": "success", "courses_imported": len(catalog)}


@app.post("/api/v1/students/{student_id}/history/import", status_code=201)
async def import_history(student_id: str, file: UploadFile = File(...)):
    history = extract_history((await file.read()).decode("utf-8", errors="replace"))
    students[student_id] = {"history": history, "plan": []}
    return {"status": "success", "past_courses_imported": len(history)}


@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, body: HistoryUpdate):
    student = require_student(student_id)
    student["history"] = [item.model_dump() for item in body.history]
    return {"status": "success", "message": "Academic history updated successfully"}


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    require_student(student_id)["history"] = []
    return {"status": "success", "message": "Academic history cleared"}


@app.post("/api/v1/students/{student_id}/plan")
def save_plan(student_id: str, body: PlanUpdate):
    student = require_student(student_id)
    student["plan"] = [item.model_dump() for item in body.planned_courses]
    return {"status": "success", "planned_courses_saved": len(student["plan"])}


@app.put("/api/v1/students/{student_id}/plan")
def replace_plan(student_id: str, body: PlanUpdate):
    return save_plan(student_id, body)


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    require_student(student_id)["plan"] = []
    return {"status": "success", "message": "Plan cleared"}


@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    student = require_student(student_id)
    return {"student_id": student_id, "history": student["history"], "plan": student["plan"]}


@app.get("/api/v1/students/{student_id}/audit-report")
def audit_report(student_id: str, strict: bool = False):
    student = require_student(student_id)
    history = student.get("history", [])
    plan = student.get("plan", [])
    completed = [h for h in history if str(h.get("status", "")).strip().lower() == "completed"]

    # Count a course only once. A successful later retake supersedes a failed attempt.
    earned_by_course = {}
    for item in completed:
        key = normalize_code(item.get("course_code", ""))
        if key:
            earned_by_course[key] = max(earned_by_course.get(key, 0), int(item.get("credits_earned", 0) or 0))
    total_earned = sum(earned_by_course.values())

    timeline_errors = {}
    cross_violations = []
    total_planned = 0
    completed_codes = set(earned_by_course)
    for planned in plan:
        code = planned.get("course_code", "")
        key = normalize_code(code)
        term = str(planned.get("term", "")).strip().upper()
        course = catalog.get(key)
        if not course:
            continue
        total_planned += int(course.get("credits", 0) or 0)
        for prerequisite in course.get("prerequisites", []):
            prereq_key = normalize_code(prerequisite)
            prior_pass = any(
                normalize_code(h.get("course_code", "")) == prereq_key
                and str(h.get("status", "")).strip().lower() == "completed"
                and term_key(str(h.get("term", ""))) < term_key(term)
                for h in history
            )
            if not prior_pass:
                timeline_errors.setdefault(term, []).append({
                    "course_code": code,
                    "type": "MISSING_PREREQUISITE",
                    "message": f"Missing prerequisite: {prerequisite}",
                })
        for cross_code in course.get("cross_listed", []):
            if normalize_code(cross_code) in completed_codes:
                cross_violations.append({
                    "course_code": code,
                    "type": "CROSS_LIST_CONFLICT",
                    "message": f"Cross-listed with completed course {cross_code}",
                })
                break

    timeline_validation = [
        {"term": term, "errors": timeline_errors[term]}
        for term in sorted(timeline_errors, key=term_key)
    ]
    has_issues = bool(timeline_validation or cross_violations)
    status = ("failed" if strict else "warning") if has_issues else "ok"
    return {
        "student_id": student_id,
        "status": status,
        "timeline_validation": timeline_validation,
        "cross_list_violations": cross_violations,
        "credit_summary": {
            "total_earned": total_earned,
            "total_planned": total_planned,
            "total_remaining_for_graduation": max(0, 120 - total_earned - total_planned),
        },
    }
