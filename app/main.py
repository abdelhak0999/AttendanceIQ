import os
import subprocess
import io
import pandas as pd
import json
import shutil
import bcrypt
from datetime import datetime, timedelta, date
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Query, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Date, func, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import List, Optional

# --- Configuration & Sécurité ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./attendance.db"
MDB_FILE_PATH = os.path.abspath("ATT2000.MDB")

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Models ---

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Models ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="manager") # admin or manager

class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    employees = relationship("Employee", back_populates="department")

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    matricule = Column(String, unique=True, index=True)
    name = Column(String)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    shift_type = Column(String, default="morning") # morning, evening, night
    created_at = Column(DateTime, default=datetime.utcnow)
    department = relationship("Department", back_populates="employees")
    punches = relationship("Punch", back_populates="employee")

class Punch(Base):
    __tablename__ = "punches"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    punch_time = Column(DateTime)
    punch_type = Column(String)
    employee = relationship("Employee", back_populates="punches")

class Absence(Base):
    __tablename__ = "absences"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    absence_date = Column(Date)
    justification = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    employee = relationship("Employee")

class Holiday(Base):
    __tablename__ = "holidays"
    id = Column(Integer, primary_key=True, index=True)
    holiday_date = Column(Date, unique=True)
    name = Column(String)

class Leave(Base):
    __tablename__ = "leaves"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    start_date = Column(Date)
    end_date = Column(Date)
    leave_type = Column(String) # Congé annuel, Maladie, etc.

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)
    details = Column(String)

class SystemSetting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    grace_period = Column(Integer, default=15)
    shift_morning_in = Column(String, default="08:00")
    shift_morning_out = Column(String, default="16:00")
    shift_evening_in = Column(String, default="16:00")
    shift_evening_out = Column(String, default="00:00")
    shift_night_in = Column(String, default="00:00")
    shift_night_out = Column(String, default="08:00")
    device_ip = Column(String, nullable=True)
    sync_interval = Column(Integer, default=30)

Base.metadata.create_all(bind=engine)

# --- Helpers ---
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def hash_password(password: str):
    # Utilisation directe de bcrypt pour éviter les bugs de passlib
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str):
    # Vérification directe avec bcrypt
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def sync_from_mdb_internal(db: Session):
    try:
        if not os.path.exists(MDB_FILE_PATH): 
            print("⚠️ Fichier MDB non trouvé, synchronisation ignorée.")
            return
        
        print("🔄 Synchronisation MDB en cours...")
        # Sync Users
        users_out = subprocess.check_output(["mdb-export", MDB_FILE_PATH, "USERINFO"]).decode()
        users_df = pd.read_csv(io.StringIO(users_out), header=None, dtype=str)
        for _, row in users_df.iterrows():
            try:
                u_id = str(int(float(row[0]))) if pd.notnull(row[0]) else None
                if not u_id: continue
                u_name = "Unknown"
                for col in row:
                    if pd.notnull(col) and any(c.isalpha() for c in str(col)):
                        u_name = str(col).strip(); break
                emp = db.query(Employee).filter(Employee.matricule == u_id).first()
                if not emp: db.add(Employee(matricule=u_id, name=u_name))
            except: continue
        db.commit()
        
        # Sync Punches
        punches_out = subprocess.check_output(["mdb-export", MDB_FILE_PATH, "CHECKINOUT"]).decode()
        punches_df = pd.read_csv(io.StringIO(punches_out), header=None, dtype=str)
        for _, row in punches_df.iterrows():
            try:
                u_id = str(int(float(row[0]))) if pd.notnull(row[0]) else None
                p_time = row[1]
                if u_id and p_time:
                    emp = db.query(Employee).filter(Employee.matricule == u_id).first()
                    if emp:
                        dt_punch = pd.to_datetime(p_time)
                        exists = db.query(Punch).filter(Punch.employee_id == emp.id, Punch.punch_time == dt_punch).first()
                        if not exists: db.add(Punch(employee_id=emp.id, punch_time=dt_punch, punch_type="in"))
            except: continue
        db.commit()
        detect_absences(db)
        print("✅ Synchronisation MDB terminée.")
    except Exception as e:
        print(f"❌ Erreur Sync MDB: {e}")

# --- Business Logic ---
def calculate_lateness(employee, date_obj, db: Session):
    # 1. Get Shift start time
    settings = db.query(SystemSetting).first()
    if not settings: return 0
    
    shift_map = {
        "morning": settings.shift_morning_in,
        "evening": settings.shift_evening_in,
        "night": settings.shift_night_in
    }
    start_time_str = shift_map.get(employee.shift_type, "08:00")
    
    # 2. Find first punch of the day
    punch = db.query(Punch).filter(
        Punch.employee_id == employee.id,
        func.date(Punch.punch_time) == date_obj
    ).order_by(Punch.punch_time.asc()).first()
    
    if not punch: return 0 # Counted as absence, not lateness
    
    # 3. Calculate difference
    shift_start = datetime.strptime(f"{date_obj} {start_time_str}", "%Y-%m-%d %H:%M")
    punch_time = punch.punch_time
    
    diff = (punch_time - shift_start).total_seconds() / 60
    late_mins = max(0, diff - settings.grace_period)
    return round(late_mins, 2)

def detect_absences(db: Session):
    print("🔍 Détection intelligente des absences...")
    # Start date: First punch in DB or 30 days ago
    first_punch = db.query(func.min(Punch.punch_time)).scalar()
    start_date = first_punch.date() if first_punch else datetime.utcnow().date() - timedelta(days=30)
    end_date = datetime.utcnow().date()
    
    # Cache for efficiency
    holidays = {h.holiday_date for h in db.query(Holiday).all()}
    leaves = db.query(Leave).all()
    
    employees = db.query(Employee).filter(Employee.is_active == True).all()
    
    for emp in employees:
        # Employee leave periods
        emp_leaves = [l for l in leaves if l.employee_id == emp.id]
        
        curr_date = start_date
        while curr_date <= end_date:
            # Skip weekends (5=Sat, 6=Sun)
            if curr_date.weekday() < 5 and curr_date not in holidays:
                # Check if employee is on leave
                on_leave = any(l.start_date <= curr_date <= l.end_date for l in emp_leaves)
                
                if not on_leave:
                    has_punch = db.query(Punch).filter(
                        Punch.employee_id == emp.id,
                        func.date(Punch.punch_time) == curr_date
                    ).first()
                    
                    if not has_punch:
                        exists = db.query(Absence).filter(
                            Absence.employee_id == emp.id,
                            Absence.absence_date == curr_date
                        ).first()
                        if not exists:
                            db.add(Absence(employee_id=emp.id, absence_date=curr_date))
            curr_date += timedelta(days=1)
    db.commit()
    print("✨ Absences mises à jour.")

# --- API ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup_event():
    import threading
    def start_task():
        db = SessionLocal()
        # 1. Création du compte admin par défaut si vide
        if not db.query(User).first():
            print("🔑 Création du compte admin par défaut...")
            admin = User(username="admin", password_hash=hash_password("admin123"), role="admin")
            db.add(admin)
            db.commit()
        
        # 2. Synchronisation MDB
        sync_from_mdb_internal(db)
        db.close()
    threading.Thread(target=start_task).start()

# --- Auth Endpoints ---
@app.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    return {"username": user.username, "role": user.role, "token": "fake-jwt-token"}

@app.post("/auth/setup")
def setup_admin(username: str, password: str, db: Session = Depends(get_db)):
    if db.query(User).first(): raise HTTPException(status_code=400, detail="Admin déjà créé")
    user = User(username=username, password_hash=hash_password(password), role="admin")
    db.add(user)
    db.commit()
    return {"status": "Admin créé avec succès"}

@app.get("/employees/departments")
def get_departments(db: Session = Depends(get_db)):
    return [d.name for d in db.query(Department).all()]

@app.post("/employees/departments")
def add_dept(name: str, db: Session = Depends(get_db)):
    dept = Department(name=name)
    db.add(dept)
    db.commit()
    return {"status": "ok"}

# --- Employee & Sync ---
def find_matricule_col(df):
    sample = df.head(100)
    best_col, highest_score = -1, -1
    for col_idx in range(len(df.columns)):
        col_data = sample[col_idx].dropna()
        if col_data.empty: continue
        numeric_data = pd.to_numeric(col_data, errors='coerce').dropna()
        if numeric_data.empty: continue
        diffs = numeric_data.diff().dropna()
        is_sequence = len(diffs) > 0 and (diffs == 1).all()
        score = len(numeric_data.unique())
        if is_sequence: score -= 1000
        if score > highest_score:
            highest_score = score
            best_col = col_idx
    return best_col

@app.post("/import/excel")
async def import_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = await file.read()
    engine_type = "openpyxl" if file.filename.endswith(".xlsx") else "xlrd"
    df = pd.read_excel(io.BytesIO(contents), header=None, engine=engine_type, dtype=str)
    if df.empty: return {"status": "error", "message": "Fichier vide"}
    
    id_col = find_matricule_col(df)
    if id_col == -1: raise HTTPException(status_code=400, detail="Colonne matricule non trouvée")
    
    added, updated = 0, 0
    for _, row in df.iterrows():
        try:
            raw_id = str(row[id_col]).strip() if pd.notnull(row[id_col]) else None
            if not raw_id or raw_id.lower() == 'nan': continue
            u_id = str(int(float(raw_id)))
            u_name = "Unknown"
            for col in row:
                if col != row[id_col] and pd.notnull(col) and any(c.isalpha() for c in str(col)):
                    u_name = str(col).strip()
                    break
            emp = db.query(Employee).filter(Employee.matricule == u_id).first()
            if not emp:
                db.add(Employee(matricule=u_id, name=u_name))
                db.flush()
                added += 1
            else:
                emp.name = u_name
                updated += 1
        except: continue
    db.commit()
    return {"status": "success", "added": added, "updated": updated}

@app.post("/sync/mdb")
async def sync_from_mdb(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    def task():
        db_sync = SessionLocal()
        sync_from_mdb_internal(db_sync)
        db_sync.close()
    background_tasks.add_task(task)
    return {"status": "success"}

# --- Holidays & Leaves ---
@app.get("/holidays/")
def list_holidays(db: Session = Depends(get_db)):
    return [{"id": h.id, "date": str(h.holiday_date), "name": h.name} for h in db.query(Holiday).all()]

@app.post("/holidays/")
def add_holiday(date_str: str, name: str, db: Session = Depends(get_db)):
    db.add(Holiday(holiday_date=date.fromisoformat(date_str), name=name))
    db.commit()
    return {"status": "ok"}

@app.get("/leaves/")
def list_leaves(db: Session = Depends(get_db)):
    return [{"id": l.id, "employee_name": l.employee.name if hasattr(l, 'employee') else "Unknown", "start": str(l.start_date), "end": str(l.end_date), "type": l.leave_type} for l in db.query(Leave).all()]

@app.post("/leaves/")
def add_leave(employee_id: int, start_date: str, end_date: str, leave_type: str, db: Session = Depends(get_db)):
    db.add(Leave(employee_id=employee_id, start_date=date.fromisoformat(start_date), end_date=date.fromisoformat(end_date), leave_type=leave_type))
    db.commit()
    return {"status": "ok"}

# --- Reports ---
@app.get("/reports/deductions")
def get_deductions(start_date: str, end_date: str, department: str = None, db: Session = Depends(get_db)):
    s_date = date.fromisoformat(start_date)
    e_date = date.fromisoformat(end_date)
    
    employees = db.query(Employee).filter(Employee.is_active == True)
    if department: employees = employees.join(Department).filter(Department.name == department)
    
    results = []
    curr = s_date
    while curr <= e_date:
        if curr.weekday() < 5:
            for e in employees.all():
                late = calculate_lateness(e, curr, db)
                if late > 0:
                    results.append({
                        "employee_name": e.name, 
                        "matricule": e.matricule, 
                        "date": str(curr),
                        "late_mins": late, 
                        "deduction_hours": round(late/60, 2)
                    })
        curr += timedelta(days=1)
    return results

@app.get("/reports/export")
def export_report(start_date: str, end_date: str, db: Session = Depends(get_db)):
    data = get_deductions(start_date, end_date, db=db)
    df = pd.DataFrame(data)
    file_path = "monthly_report.xlsx"
    df.to_excel(file_path, index=False)
    return FileResponse(file_path, filename="Rapport_Absences_Retards.xlsx")

# --- Dashboard Stats ---
@app.get("/dashboard/stats")
def get_stats(db: Session = Depends(get_db)):
    total_emp = db.query(Employee).filter(Employee.is_active == True).count()
    total_abs = db.query(Absence).count()
    total_late = 0
    # Simplified late sum for the month
    start_of_month = datetime.utcnow().date().replace(day=1)
    end_of_month = datetime.utcnow().date()
    
    # This is a heavy query, we'll optimize in production
    for e in db.query(Employee).all():
        curr = start_of_month
        while curr <= end_of_month:
            total_late += calculate_lateness(e, curr, db)
            curr += timedelta(days=1)
            
    return {
        "total_employees": total_emp,
        "total_absences": total_abs,
        "total_late_mins": round(total_late, 0),
        "absenteeism_rate": round((total_abs / (total_emp * 20)) * 100, 1) if total_emp > 0 else 0
    }

# --- Admin & Setup ---
@app.get("/settings/")
def get_settings(db: Session = Depends(get_db)):
    s = db.query(SystemSetting).first()
    if not s: s = SystemSetting(); db.add(s); db.commit(); db.refresh(s)
    return s

@app.put("/settings/")
def update_settings(data: dict, db: Session = Depends(get_db)):
    s = db.query(SystemSetting).first()
    for k, v in data.items(): setattr(s, k, v)
    db.commit()
    return {"status": "ok"}

@app.post("/sync/absences")
async def sync_absences(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(detect_absences, db)
    return {"status": "success"}

@app.get("/employees/")
def list_employees(search: str = None, department: str = None, include_inactive: bool = False, db: Session = Depends(get_db)):
    query = db.query(Employee)
    if not include_inactive: query = query.filter(Employee.is_active == True)
    if search: query = query.filter((Employee.name.contains(search)) | (Employee.matricule.contains(search)))
    if department: query = query.join(Department).filter(Department.name == department)
    return [{"id": e.id, "name": e.name, "matricule": e.matricule, "department": e.department.name if e.department else "-", "is_active": e.is_active, "shift_type": e.shift_type} for e in query.all()]

@app.put("/employees/{emp_id}")
def update_employee(emp_id: int, data: dict, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp: raise HTTPException(status_code=404)
    for k, v in data.items(): setattr(emp, k, v)
    db.commit()
    return {"status": "ok"}

@app.get("/absences/")
def list_absences(start_date: str = None, end_date: str = None, db: Session = Depends(get_db)):
    query = db.query(Absence).join(Employee)
    if start_date and end_date: query = query.filter(Absence.absence_date.between(start_date, end_date))
    return [{"id": a.id, "employee_name": a.employee.name, "matricule": a.employee.matricule, "department": a.employee.department.name if a.employee.department else "-", "absence_date": str(a.absence_date), "justification": a.justification, "notes": a.notes} for a in query.all()]

@app.put("/absences/{abs_id}")
def update_absence(abs_id: int, data: dict, db: Session = Depends(get_db)):
    abs_obj = db.query(Absence).filter(Absence.id == abs_id).first()
    if not abs_obj: raise HTTPException(status_code=404)
    abs_obj.justification = data.get("justification")
    abs_obj.notes = data.get("notes")
    db.commit()
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
