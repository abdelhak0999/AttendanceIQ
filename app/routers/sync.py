from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..services import detect_absences, sync_from_mdb_internal, sync_from_device_internal

router = APIRouter(prefix="/sync", tags=["Synchronization"])

@router.post("/absences")
def sync_absences(db: Session = Depends(get_db)):
    detect_absences(db)
    return {"status": "success"}

@router.post("/mdb")
def sync_from_mdb(db: Session = Depends(get_db)):
    sync_from_mdb_internal(db)
    return {"status": "success"}

@router.post("/device")
def sync_from_device(db: Session = Depends(get_db)):
    sync_from_device_internal(db)
    return {"status": "success"}