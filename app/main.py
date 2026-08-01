import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import engine, Base, SessionLocal
from .routers import auth, employees, attendance, settings, sync
from .models import User, Shift, Department
from .services import hash_password, sync_from_mdb_internal

# Création des tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AttendanceIQ", description="Professional Time and Attendance Management System")

# ========== MONTER LE DOSSIER STATIQUE ==========
# Ici, nous servons les fichiers HTML/CSS/JS depuis le dossier "uploads"
# sous l'URL "/static". Si vous renommez le dossier en "static", changez le directory.
app.mount("/static", StaticFiles(directory="uploads"), name="static")

# ========== CORS ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== ROUTERS ==========
app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(attendance.router)
app.include_router(settings.router)
app.include_router(sync.router)

# ========== ÉVÉNEMENT DE DÉMARRAGE ==========
@app.on_event("startup")
async def startup_event():
    def start_task():
        db = SessionLocal()
        try:
            # Créer l'admin par défaut si inexistant
            if not db.query(User).first():
                admin = User(username="admin", password_hash=hash_password("admin123"), role="admin")
                db.add(admin)
                db.commit()

            # Créer les shifts par défaut
            if not db.query(Shift).first():
                defaults = [
                    Shift(name="Matin", start_time="08:00", end_time="16:00"),
                    Shift(name="Soir", start_time="16:00", end_time="00:00"),
                    Shift(name="Nuit", start_time="00:00", end_time="08:00")
                ]
                db.add_all(defaults)
                db.commit()

            # Seed de la hiérarchie CETIM
            root_dept = db.query(Department).filter(Department.name == "CETIM").first()
            if not root_dept:
                print("🌱 Seeding CETIM Hierarchy...")
                cetim = Department(name="CETIM")
                db.add(cetim)
                db.commit()

                dg = Department(name="DG", parent_id=cetim.id)
                dga = Department(name="DGA", parent_id=cetim.id)
                daf = Department(name="DAF", parent_id=cetim.id)
                dqmi = Department(name="DQMI", parent_id=cetim.id)
                retraiter = Department(name="retraiter", parent_id=cetim.id)
                db.add_all([dg, dga, daf, dqmi, retraiter])
                db.commit()

                # Sous-départements
                for parent, children in [
                    (dg, ["AACG", "DTC", "HSE"]),
                    (dga, ["DEV", "DEAP", "DLC"]),
                    (deap := Department(name="DEAP", parent_id=dga.id), ["DEAP 1", "DEAP2", "ENVIR"]),
                    (daf, ["SD/LOG", "SD/FC", "SD/RH"]),
                    (dqmi, ["DR", "SD/IV", "SD/MQ"])
                ]:
                    for child_name in children:
                        db.add(Department(name=child_name, parent_id=parent.id))
                db.commit()
                print("✅ CETIM Hierarchy seeded.")

            # ========== SYNCHRONISATION MDB DÉSACTIVÉE AU DÉMARRAGE ==========
            # Pour éviter les verrous de base de données, on ne lance plus
            # automatiquement l'import de l'intégralité de la MDB.
            # Utilisez le bouton "Sync MDB" dans l'interface ou l'API /sync/mdb.
            # sync_from_mdb_internal(db)
            print("ℹ️ Synchronisation MDB désactivée au démarrage. Utilisez le bouton Sync MDB.")

        except Exception as e:
            print(f"Startup error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            db.close()

    threading.Thread(target=start_task, daemon=True).start()

# ========== ROUTE RACINE ==========
@app.get("/")
def root():
    return {"message": "Welcome to AttendanceIQ API. Visit /docs for documentation."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
