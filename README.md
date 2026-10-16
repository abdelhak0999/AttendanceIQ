# AttendanceIQ

Professional time and attendance management system.

## Features

- Employee management with hierarchical departments.
- Shift definition and bulk assignment.
- Import/export via Excel.
- Synchronization with ZKTeco devices.
- Import from MDB files.
- Automatic absence detection.
- Reporting on lateness.

## Installation

1. Clone the repository.
2. Create a virtual environment: `python3 -m venv venv`
3. Activate it: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Install system dependencies: `sudo apt install mdbtools` (or `dnf` for Fedora).
6. Copy `.env.example` to `.env` and adjust.
7. Run the server: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## First login

Before the first start, set `ADMIN_PASSWORD` in `.env` (and optionally `ADMIN_USERNAME`, default `admin`). The admin account is created from these values when the database has no users yet.

## License

MIT
