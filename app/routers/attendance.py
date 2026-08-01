from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import pandas as pd
from datetime import date, datetime, timedelta
from ..database import get_db
from ..models import Shift, Holiday, Leave, Absence, Employee, Department
from ..schemas import HolidayCreate, LeaveCreate
from ..services import calculate_lateness

router = APIRouter(prefix="/attendance", tags=["Attendance"])

@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    total_emp = db.query(Employee).filter(Employee.is_active == True).count()
    total_abs = db.query(Absence).count()
    total_late = 0
    now = datetime.now().date()
    start = now.replace(day=1)
    for e in db.query(Employee).all():
        curr = start
        while curr <= now:
            total_late += calculate_lateness(e, curr, db)
            curr += timedelta(days=1)
    return {
        "total_employees": total_emp,
        "total_absences": total_abs,
        "total_late_mins": round(total_late, 0),
        "absenteeism_rate": round((total_abs / (total_emp * 20)) * 100, 1) if total_emp else 0
    }

@router.get("/shifts/")
def list_shifts(db: Session = Depends(get_db)):
    return [{"id": s.id, "name": s.name, "start": s.start_time, "end": s.end_time} for s in db.query(Shift).all()]

@router.post("/shifts/")
def add_shift(name: str, start_time: str, end_time: str, db: Session = Depends(get_db)):
    if db.query(Shift).filter(Shift.name == name).first():
        raise HTTPException(400, "Shift existe déjà")
    db.add(Shift(name=name, start_time=start_time, end_time=end_time))
    db.commit()
    return {"status": "ok"}

@router.delete("/shifts/{shift_id}")
def delete_shift(shift_id: int, db: Session = Depends(get_db)):
    shift = db.query(Shift).filter(Shift.id == shift_id).first()
    if not shift:
        raise HTTPException(404)
    db.query(Employee).filter(Employee.shift_id == shift_id).update({"shift_id": None})
    db.delete(shift)
    db.commit()
    return {"status": "ok"}

@router.get("/holidays/")
def list_holidays(db: Session = Depends(get_db)):
    return [{"id": h.id, "date": str(h.holiday_date), "name": h.name} for h in db.query(Holiday).order_by(Holiday.holiday_date).all()]

@router.post("/holidays/")
def add_holiday(data: HolidayCreate, db: Session = Depends(get_db)):
    d = date.fromisoformat(data.date_str)
    if db.query(Holiday).filter(Holiday.holiday_date == d).first():
        raise HTTPException(400, "Déjà existant")
    db.add(Holiday(holiday_date=d, name=data.name))
    db.commit()
    return {"status": "ok"}

@router.delete("/holidays/{holiday_id}")
def delete_holiday(holiday_id: int, db: Session = Depends(get_db)):
    h = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if not h:
        raise HTTPException(404)
    db.delete(h)
    db.commit()
    return {"status": "ok"}

@router.post("/holidays/seed-algeria")
def seed_algeria_holidays(year: int = None, db: Session = Depends(get_db)):
    if not year:
        year = datetime.now().year
    added = 0
    for d, n in [(f"{year}-01-01", "Nouvel An"), (f"{year}-01-12", "Yennayer"), (f"{year}-05-01", "Fête du Travail"), (f"{year}-07-05", "Fête de l'Indépendance"), (f"{year}-11-01", "Révolution")]:
        day = date.fromisoformat(d)
        if not db.query(Holiday).filter(Holiday.holiday_date == day).first():
            db.add(Holiday(holiday_date=day, name=n))
            added += 1
    db.commit()
    return {"status": "ok", "added": added}

@router.get("/leaves/")
def list_leaves(db: Session = Depends(get_db)):
    return [{"id": l.id, "employee_name": l.employee.name if l.employee else "-", "start": str(l.start_date), "end": str(l.end_date), "type": l.leave_type} for l in db.query(Leave).all()]

@router.post("/leaves/")
def add_leave(data: LeaveCreate, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == data.employee_id).first()
    if not emp:
        raise HTTPException(404, "Employé introuvable")
    db.add(Leave(employee_id=data.employee_id, start_date=date.fromisoformat(data.start_date), end_date=date.fromisoformat(data.end_date), leave_type=data.leave_type))
    db.commit()
    return {"status": "ok"}

@router.delete("/leaves/{leave_id}")
def delete_leave(leave_id: int, db: Session = Depends(get_db)):
    l = db.query(Leave).filter(Leave.id == leave_id).first()
    if not l:
        raise HTTPException(404)
    db.delete(l)
    db.commit()
    return {"status": "ok"}

@router.get("/absences/")
def list_absences(start_date: str = None, end_date: str = None, db: Session = Depends(get_db)):
    query = db.query(Absence).join(Employee)
    if start_date and end_date:
        query = query.filter(Absence.absence_date.between(start_date, end_date))
    return [{"id": a.id, "employee_name": a.employee.name, "matricule": a.employee.matricule, "department": a.employee.department.name if a.employee.department else "-", "absence_date": str(a.absence_date), "justification": a.justification, "notes": a.notes} for a in query.all()]

@router.put("/absences/{abs_id}")
def update_absence(abs_id: int, data: dict, db: Session = Depends(get_db)):
    a = db.query(Absence).filter(Absence.id == abs_id).first()
    if not a:
        raise HTTPException(404)
    a.justification = data.get("justification")
    a.notes = data.get("notes")
    db.commit()
    return {"status": "ok"}

@router.get("/reports/deductions")
def get_deductions(start_date: str, end_date: str, department: str = None, db: Session = Depends(get_db)):
    s = date.fromisoformat(start_date)
    e = date.fromisoformat(end_date)
    q = db.query(Employee).filter(Employee.is_active == True)
    if department:
        q = q.join(Department).filter(Department.name == department)
    results = []
    curr = s
    while curr <= e:
        if curr.weekday() < 5:
            for emp in q.all():
                late = calculate_lateness(emp, curr, db)
                if late > 0:
                    results.append({"employee_name": emp.name, "matricule": emp.matricule, "date": str(curr), "late_mins": late, "deduction_hours": round(late/60, 2)})
        curr += timedelta(days=1)
    return results

@router.get("/reports/export")
def export_report(start_date: str, end_date: str, db: Session = Depends(get_db)):
    data = get_deductions(start_date, end_date, db=db)
    df = pd.DataFrame(data)
    path = "monthly_report.xlsx"
    df.to_excel(path, index=False)
    return FileResponse(path, filename="Rapport_Absences_Retards.xlsx")