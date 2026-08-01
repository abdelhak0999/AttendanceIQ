from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..services import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    return {"username": user.username, "role": user.role, "token": "fake-jwt-token"}

@router.post("/setup")
def setup_admin(username: str, password: str, db: Session = Depends(get_db)):
    if db.query(User).first(): 
        raise HTTPException(status_code=400, detail="Admin déjà créé")
    user = User(username=username, password_hash=hash_password(password), role="admin")
    db.add(user)
    db.commit()
    return {"status": "ok", "message": "Admin créé avec succès"}