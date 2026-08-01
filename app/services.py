import os
import subprocess
import io
import pandas as pd
import bcrypt
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from .models import User, Employee, Shift, Punch, Absence, Holiday, Leave, SystemSetting, Department
import threading

_absences_lock = threading.Lock()

try:
    from zk import ZK
    PYZK_INSTALLED = True
except ImportError:
    try:
        from pyzk import ZK
        PYZK_INSTALLED = True
    except ImportError:
        PYZK_INSTALLED = False
        print("⚠️ pyzk/zk non installé")

MDB_FILE_PATH = os.path.abspath("ATT2000.MDB")

# --- Auth Helpers ---
def hash_password(password: str):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# --- Attendance Logic ---
def calculate_lateness(employee, date_obj, db: Session):
    settings = db.query(SystemSetting).first()
    if not settings or not employee.shift:
        return 0
    start_time_str = employee.shift.start_time
    punch = db.query(Punch).filter(
        Punch.employee_id == employee.id,
        func.date(Punch.punch_time) == date_obj
    ).order_by(Punch.punch_time.asc()).first()
    if not punch:
        return 0
    try:
        shift_start = datetime.strptime(f"{date_obj} {start_time_str}", "%Y-%m-%d %H:%M")
        diff = (punch.punch_time - shift_start).total_seconds() / 60
        return max(0, round(diff - settings.grace_period, 2))
    except:
        return 0

def detect_absences(db: Session):
    with _absences_lock:
        db.execute(text("PRAGMA busy_timeout = 30000"))
        db.commit()
        print("🔍 Détection des absences...")
        now_date = datetime.now().date()
        try:
            db.execute(text("SELECT 1 FROM absences LIMIT 1"))
        except:
            db.execute(text("""
                CREATE TABLE absences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    absence_date TEXT NOT NULL,
                    justification TEXT,
                    notes TEXT,
                    FOREIGN KEY(employee_id) REFERENCES employees(id)
                )
            """))
            db.commit()
        holidays = {h.holiday_date for h in db.query(Holiday).all()}
        leaves = db.query(Leave).all()
        employees = db.query(Employee).filter(Employee.is_active == True).all()
        if not employees:
            return
        punches = set(db.query(Punch.employee_id, func.date(Punch.punch_time)).all())
        absences_existing = set(db.query(Absence.employee_id, Absence.absence_date).all())
        new_absences = []
        for emp in employees:
            first_punch = db.query(func.min(Punch.punch_time)).filter(Punch.employee_id == emp.id).scalar()
            start_date = first_punch.date() if first_punch else now_date - timedelta(days=30)
            emp_leaves = [l for l in leaves if l.employee_id == emp.id]
            curr = start_date
            while curr <= now_date:
                if curr.weekday() < 5 and curr not in holidays:
                    on_leave = any(l.start_date <= curr <= l.end_date for l in emp_leaves)
                    if not on_leave and (emp.id, curr) not in punches and (emp.id, curr) not in absences_existing:
                        new_absences.append(Absence(employee_id=emp.id, absence_date=curr))
                curr += timedelta(days=1)
        if new_absences:
            db.add_all(new_absences)
            db.commit()
            print(f"✅ {len(new_absences)} absences ajoutées.")

# --- Helpers ---
def find_matricule_col(df):
    best, score = -1, -1
    for i in range(len(df.columns)):
        col = df[i].dropna()
        if col.empty: continue
        nums = pd.to_numeric(col, errors='coerce').dropna()
        if nums.empty: continue
        s = len(nums.unique())
        if (nums.diff().dropna() == 1).all():
            s -= 1000
        if s > score:
            score, best = s, i
    return best

def normalize_id(val):
    if pd.isnull(val):
        return None
    s = str(val).strip().strip('"').strip("'")
    if '.' in s:
        s = s.split('.')[0]
    return s

# --- Synchronisation MDB (corrigée avec skiprows=1) ---
def sync_from_mdb_internal(db: Session):
    try:
        if not os.path.exists(MDB_FILE_PATH):
            print("❌ MDB non trouvé")
            return
        print("🔄 Sync MDB...")

        # 1. Départements
        depts = pd.read_csv(io.StringIO(subprocess.check_output(["mdb-export", MDB_FILE_PATH, "DEPARTMENTS"]).decode()), dtype=str)
        dept_map = {}
        for _, r in depts.iterrows():
            mid = normalize_id(r['DEPTID'])
            name = r['DEPTNAME'].strip()
            if mid and name:
                existing = db.query(Department).filter(Department.name == name).first()
                if not existing:
                    d = Department(name=name)
                    db.add(d)
                    db.flush()
                    dept_map[mid] = d.id
                else:
                    dept_map[mid] = existing.id
        db.commit()
        for _, r in depts.iterrows():
            mid = normalize_id(r['DEPTID'])
            pmid = normalize_id(r['SUPDEPTID'])
            if mid and pmid and pmid != '0' and mid in dept_map and pmid in dept_map:
                child = db.query(Department).filter(Department.id == dept_map[mid]).first()
                if child and child.parent_id is None:
                    child.parent_id = dept_map[pmid]
        db.commit()

        # 2. Employés
        users = pd.read_csv(io.StringIO(subprocess.check_output(["mdb-export", MDB_FILE_PATH, "USERINFO"]).decode()), dtype=str)
        for _, r in users.iterrows():
            mat = normalize_id(r['Badgenumber'])
            if not mat:
                continue
            name = r['Name'].strip() if pd.notnull(r['Name']) else "Inconnu"
            dept_mdb = normalize_id(r['DEFAULTDEPTID'])
            emp = db.query(Employee).filter(Employee.matricule == mat).first()
            if not emp:
                emp = Employee(matricule=mat, name=name)
                db.add(emp)
                db.flush()
            emp.name = name
            if dept_mdb and dept_mdb in dept_map:
                emp.department_id = dept_map[dept_mdb]
        db.commit()

        # 3. Pointages (CORRECTION : skiprows=1 pour ignorer l'en-tête)
        punches = pd.read_csv(
            io.StringIO(subprocess.check_output(["mdb-export", MDB_FILE_PATH, "CHECKINOUT"]).decode()),
            header=None,
            dtype=str,
            skiprows=1   # <-- ICI LA CORRECTION
        )
        imported = 0
        for _, r in punches.iterrows():
            uid = normalize_id(r[0])
            if not uid:
                continue
            ptime = r[1].strip() if len(r) > 1 else None
            if not ptime:
                continue
            emp = db.query(Employee).filter(Employee.matricule == uid).first()
            if not emp:
                emp = Employee(matricule=uid, name=f"Employé {uid}")
                db.add(emp)
                db.flush()
            dt = pd.to_datetime(ptime)
            if not db.query(Punch).filter(Punch.employee_id == emp.id, Punch.punch_time == dt).first():
                db.add(Punch(employee_id=emp.id, punch_time=dt, punch_type="in"))
                imported += 1
        db.commit()
        print(f"✅ {imported} pointages importés.")
        detect_absences(db)
    except Exception as e:
        print(f"❌ Sync MDB error: {e}")
        import traceback
        traceback.print_exc()

# --- Synchronisation ZKTeco ---
def sync_from_device_internal(db: Session):
    if not PYZK_INSTALLED:
        print("⚠️ pyzk/zk non installé")
        return
    settings = db.query(SystemSetting).first()
    if not settings or not settings.device_ip:
        print("⚠️ IP non configurée")
        return
    ip = settings.device_ip
    port = settings.device_port or 4370
    password = settings.device_password or 0
    print(f"🔄 Connexion à {ip}:{port}...")
    try:
        zk = ZK(ip, port=port, timeout=10, password=password)
        conn = zk.connect()
        if not conn:
            print("❌ Connexion échouée")
            return
        records = conn.get_attendance()
        imported = 0
        for rec in records:
            uid = str(rec.user_id)
            ptime = rec.timestamp
            emp = db.query(Employee).filter(Employee.matricule == uid).first()
            if emp:
                if not db.query(Punch).filter(Punch.employee_id == emp.id, Punch.punch_time == ptime).first():
                    db.add(Punch(employee_id=emp.id, punch_time=ptime, punch_type="in"))
                    imported += 1
        conn.disconnect()
        db.commit()
        print(f"✅ {imported} pointages importés depuis le terminal.")
        detect_absences(db)
    except Exception as e:
        print(f"❌ Erreur terminal: {e}")