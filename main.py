from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from typing import Any
import re

app = FastAPI(title="Student Academic History API")

students: dict[str, dict[str, Any]] = {}


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


def clean_text(cell):
    return " ".join(cell.stripped_strings).strip()


def header_key(value):
    return re.sub(r"[^a-z]", "", value.lower())


def grade_rank(grade):
    value = grade.strip()
    if not value:
        return (0, 0)
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", value):
        try:
            return (4, float(value.rstrip("%")))
        except ValueError:
            return (4, 0)
    if re.fullmatch(r"[A-F][+-]?", value.upper()):
        return (3, 0)
    if value.upper() == "P":
        return (2, 0)
    return (1, 0)


def parse_credits(value):
    match = re.search(r"-?\d+", value.strip())
    if not match:
        return 0
    return int(match.group())


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
            if not cells:
                continue

            required = max(
                column_map[k] for k in ("status", "course", "term", "credits")
            )
            if len(cells) <= required:
                continue

            status = clean_text(cells[column_map["status"]])
            course = clean_text(cells[column_map["course"]])
            term = clean_text(cells[column_map["term"]])
            credits = parse_credits(clean_text(cells[column_map["credits"]]))

            grade_index = column_map.get("grade")
            grade = (
                clean_text(cells[grade_index])
                if grade_index is not None and grade_index < len(cells)
                else ""
            )

            if status.lower() not in allowed or not course or not term:
                continue

            record = {
                "course_code": course,
                "term": term,
                "credits_earned": credits,
                "status": status,
            }

            key = (course, term)
            score = (grade_rank(grade), credits)

            if key not in chosen or score > chosen[key][0]:
                chosen[key] = (score, record)

    return [item[1] for item in chosen.values()]


def require_student(student_id):
    if student_id not in students:
        raise HTTPException(status_code=404, detail="Student not found")
    return students[student_id]


@app.get("/")
def root():
    return {"status": "ok", "service": "student-academic-history-api"}


@app.post("/api/v1/students/{student_id}/history/import", status_code=201)
async def import_history(student_id: str, file: UploadFile = File(...)):
    content = await file.read()
    history = extract_history(content)
    students[student_id] = {"history": history, "plan": []}
    return {
        "status": "success",
        "past_courses_imported": len(history),
    }


@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, body: HistoryUpdate):
    student = require_student(student_id)
    student["history"] = [item.model_dump() for item in body.history]
    return {"status": "success", "message": "Academic history updated successfully"}


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    student = require_student(student_id)
    student["history"] = []
    return {"status": "success", "message": "Academic history cleared"}


@app.post("/api/v1/students/{student_id}/plan")
def save_plan(student_id: str, body: PlanUpdate):
    student = require_student(student_id)
    student["plan"] = [item.model_dump() for item in body.planned_courses]
    return {"status": "success", "planned_courses_saved": len(student["plan"])}


@app.put("/api/v1/students/{student_id}/plan")
def replace_plan(student_id: str, body: PlanUpdate):
    student = require_student(student_id)
    student["plan"] = [item.model_dump() for item in body.planned_courses]
    return {"status": "success", "planned_courses_saved": len(student["plan"])}


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    student = require_student(student_id)
    student["plan"] = []
    return {"status": "success", "message": "Plan cleared"}


@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    student = require_student(student_id)
    return {
        "student_id": student_id,
        "history": student["history"],
        "plan": student["plan"],
    }
