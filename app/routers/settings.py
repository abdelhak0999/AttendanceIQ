from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import SystemSetting
from ..schemas import SystemSettingOut
try:
    from zk import ZK
    PYZK_INSTALLED = True
except:
    try:
        from pyzk import ZK
        PYZK_INSTALLED = True
    except:
        PYZK_INSTALLED = False

router = APIRouter(prefix="/settings", tags=["Settings"])

@router.get("/", response_model=SystemSettingOut)
def get_settings(db: Session = Depends(get_db)):
    s = db.query(SystemSetting).first()
    if not s:
        s = SystemSetting()
        db.add(s)
        db.commit()
        db.refresh(s)
    return s

@router.put("/")
def update_settings(data: dict, db: Session = Depends(get_db)):
    s = db.query(SystemSetting).first()
    if not s:
        s = SystemSetting()
        db.add(s)
    allowed = {"grace_period", "device_ip", "device_port", "device_password", "sync_interval"}
    for k, v in data.items():
        if k in allowed:
            setattr(s, k, v)
    db.commit()
    return {"status": "ok"}

@router.post("/test-connection")
def test_connection(db: Session = Depends(get_db)):
    if not PYZK_INSTALLED:
        return {"status": "error", "message": "pyzk non installé"}
    s = db.query(SystemSetting).first()
    if not s or not s.device_ip:
        return {"status": "error", "message": "IP non configurée"}
    try:
        zk = ZK(s.device_ip, port=s.device_port or 4370, password=s.device_password or 0, timeout=5)
        conn = zk.connect()
        if conn:
            conn.disconnect()
            return {"status": "success", "message": f"✅ Connecté à {s.device_ip}"}
        else:
            return {"status": "error", "message": "❌ Connexion échouée"}
    except Exception as e:
        return {"status": "error", "message": f"❌ {str(e)}"}