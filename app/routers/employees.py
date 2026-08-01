from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import pandas as pd
import io
from typing import Optional
from datetime import date, datetime, timedelta
from ..database import get_db
from ..models import Employee, Department, Punch, Shift
from ..schemas import BulkShiftAssign
from ..services import find_matricule_col

router = APIRouter(prefix="/employees", tags=["Employees"])

def get_all_child_ids(db: Session, parent_id: int):
    ids = [parent_id]
    children = db.query(Department).filter(Department.parent_id == parent_id).all()
    for child in children:
        ids.extend(get_all_child_ids(db, child.id))
    return ids

@router.get("/")
def list_employees(
    search: Optional[str] = None,
    dept_id: Optional[int] = None,
    status: str = "active",
    db: Session = Depends(get_db)
):
    query = db.query(Employee)
    if status == "active":
        query = query.filter(Employee.is_active == True)
    elif status == "inactive":
        query = query.filter(Employee.is_active == False)
    if search:
        query = query.filter(
            (Employee.name.contains(search)) | 
            (Employee.matricule.contains(search))
        )
    if dept_id:
        all_dept_ids = get_all_child_ids(db, dept_id)
        query = query.filter(Employee.department_id.in_(all_dept_ids))
    employees = query.all()
    return [{
        "id": e.id,
        "name": e.name,
        "matricule": e.matricule,
        "department": e.department.name if e.department else "-",
        "department_id": e.department_id,
        "is_active": e.is_active,
        "shift_name": e.shift.name if e.shift else "Non assigné",
        "shift_id": e.shift_id
    } for e in employees]

# ----- ROUTE MANQUANTE : récupérer un employé par ID -----
@router.get("/{emp_id}")
def get_employee(emp_id: int, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(404, detail="Employé introuvable")
    return {
        "id": emp.id,
        "name": emp.name,
        "matricule": emp.matricule,
        "department": emp.department.name if emp.department else "-",
        "department_id": emp.department_id,
        "is_active": emp.is_active,
        "shift_name": emp.shift.name if emp.shift else "Non assigné",
        "shift_id": emp.shift_id
    }

@router.get("/departments")
def get_departments(db: Session = Depends(get_db)):
    depts = db.query(Department).all()
    if not depts:
        return []
    dept_dict = {d.id: d for d in depts}
    result = []
    for d in depts:
        path_parts = []
        current = d
        while current:
            path_parts.insert(0, current.name)
            current = dept_dict.get(current.parent_id) if current.parent_id else None
        result.append({"id": d.id, "path": " > ".join(path_parts)})
    return result

@router.get("/departments/tree")
def get_department_tree(db: Session = Depends(get_db)):
    def build(parent_id=None):
        children = db.query(Department).filter(Department.parent_id == parent_id).all()
        return [{"id": c.id, "name": c.name, "children": build(c.id)} for c in children]
    root = db.query(Department).filter(Department.parent_id == None).first()
    return [{"id": root.id, "name": root.name, "children": build(root.id)}] if root else []

@router.put("/bulk-assign-shift")
def bulk_assign_shift(data: BulkShiftAssign, db: Session = Depends(get_db)):
    if not data.employee_ids:
        raise HTTPException(400, "Aucun employé")
    shift = db.query(Shift).filter(Shift.id == data.shift_id).first() if data.shift_id else None
    if data.shift_id and not shift:
        raise HTTPException(404, "Shift introuvable")
    updated = db.query(Employee).filter(Employee.id.in_(data.employee_ids)).update(
        {"shift_id": data.shift_id}, synchronize_session=False
    )
    db.commit()
    return {"status": "ok", "updated": updated}

@router.put("/{emp_id}")
def update_employee(emp_id: int, data: dict, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(404, "Employé introuvable")
    for k, v in data.items():
        if hasattr(emp, k):
            setattr(emp, k, v)
    db.commit()
    return {"status": "ok"}

@router.get("/export-inactive")
def export_inactive(db: Session = Depends(get_db)):
    inactives = db.query(Employee).filter(Employee.is_active == False).all()
    df = pd.DataFrame([{"matricule": e.matricule, "name": e.name, "department": e.department.name if e.department else "-"} for e in inactives])
    path = "inactive_employees.xlsx"
    df.to_excel(path, index=False)
    return FileResponse(path, filename="employes_inactifs.xlsx")

@router.post("/import/excel")
async def import_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents), header=None, dtype=str)
    if df.empty:
        return {"status": "error", "message": "Fichier vide"}
    id_col = find_matricule_col(df)
    if id_col == -1:
        raise HTTPException(400, "Colonne matricule non trouvée")
    dept_col = -1
    all_depts = {d.name: d.id for d in db.query(Department).all()}
    for col in range(len(df.columns)):
        if col == id_col: continue
        sample = df[col].dropna().head(20)
        matches = sum(1 for v in sample if str(v).strip() in all_depts)
        if matches > 0:
            dept_col = col
            break
    added = updated = 0
    for _, row in df.iterrows():
        try:
            raw_id = str(row[id_col]).strip()
            if not raw_id or raw_id.lower() == 'nan': continue
            u_id = str(int(float(raw_id)))
            name = "Unknown"
            for col in row:
                if col != row[id_col] and (dept_col == -1 or col != row[dept_col]) and pd.notnull(col) and any(c.isalpha() for c in str(col)):
                    name = str(col).strip()
                    break
            dept_id = None
            if dept_col != -1:
                dept_name = str(row[dept_col]).strip()
                if dept_name in all_depts:
                    dept_id = all_depts[dept_name]
                elif dept_name:
                    root = db.query(Department).filter(Department.name == "CETIM").first()
                    new_dept = Department(name=dept_name, parent_id=root.id if root else None)
                    db.add(new_dept)
                    db.flush()
                    dept_id = new_dept.id
                    all_depts[dept_name] = dept_id
            emp = db.query(Employee).filter(Employee.matricule == u_id).first()
            if not emp:
                db.add(Employee(matricule=u_id, name=name, department_id=dept_id))
                added += 1
            else:
                emp.name = name
                if dept_id:
                    emp.department_id = dept_id
                updated += 1
        except:
            continue
    db.commit()
    return {"status": "success", "added": added, "updated": updated}

# ----- ROUTE D'HISTORIQUE (déjà présente) -----
@router.get("/{emp_id}/history")
def get_employee_history(emp_id: int, month: str = None, db: Session = Depends(get_db)):
    """Retourne l'historique des pointages d'un employé pour un mois donné."""
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(404, detail="Employé introuvable")
    
    if month:
        try:
            year, mon = map(int, month.split('-'))
            start_date = date(year, mon, 1)
            if mon == 12:
                end_date = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(year, mon + 1, 1) - timedelta(days=1)
        except:
            start_date = datetime.now().date().replace(day=1)
            end_date = datetime.now().date()
    else:
        start_date = datetime.now().date().replace(day=1)
        end_date = datetime.now().date()
    
    punches = db.query(Punch).filter(
        Punch.employee_id == emp_id,
        Punch.punch_time >= start_date,
        Punch.punch_time <= end_date + timedelta(days=1)
    ).order_by(Punch.punch_time.asc()).all()
    
    days = {}
    for p in punches:
        day = p.punch_time.date()
        if day not in days:
            days[day] = []
        days[day].append(p)
    
    result = []
    curr = start_date
    while curr <= end_date:
        day_data = {
            "date": curr.isoformat(),
            "entree_matin": None,
            "sortie_pause": None,
            "entree_apres_midi": None,
            "sortie_soir": None,
            "statut": "absent",
            "minutes_retard": 0
        }
        if curr in days:
            day_punches = days[curr]
            times = [p.punch_time.time().strftime("%H:%M") for p in day_punches]
            if len(times) >= 1:
                day_data["entree_matin"] = times[0]
            if len(times) >= 2:
                day_data["sortie_pause"] = times[1]
            if len(times) >= 3:
                day_data["entree_apres_midi"] = times[2]
            if len(times) >= 4:
                day_data["sortie_soir"] = times[3]
            day_data["statut"] = "a_l_heure" if len(times) > 0 else "absent"
            if emp.shift and day_data["entree_matin"]:
                shift_start = datetime.strptime(f"{curr} {emp.shift.start_time}", "%Y-%m-%d %H:%M")
                punch_dt = datetime.strptime(f"{curr} {day_data['entree_matin']}", "%Y-%m-%d %H:%M")
                diff = (punch_dt - shift_start).total_seconds() / 60
                if diff > 0:
                    day_data["minutes_retard"] = round(diff, 2)
        result.append(day_data)
        curr += timedelta(days=1)
    
    summary = {
        "days_present": sum(1 for d in result if d["statut"] != "absent"),
        "days_absent": sum(1 for d in result if d["statut"] == "absent"),
        "late_count": sum(1 for d in result if d["minutes_retard"] > 0),
        "total_late_mins": round(sum(d["minutes_retard"] for d in result), 2)
    }
    return {"summary": summary, "days": result}