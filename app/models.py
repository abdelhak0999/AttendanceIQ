from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Date, Text
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="manager")

class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    parent_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    employees = relationship("Employee", back_populates="department")
    parent = relationship("Department", remote_side=[id], back_populates="children")
    children = relationship("Department", back_populates="parent")

class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)
    start_time = Column(String)
    end_time = Column(String)
    employees = relationship("Employee", back_populates="shift")

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    matricule = Column(String, unique=True, index=True)
    name = Column(String)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    department = relationship("Department", back_populates="employees")
    shift = relationship("Shift", back_populates="employees")
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
    leave_type = Column(String)

class SystemSetting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    grace_period = Column(Integer, default=15)
    device_ip = Column(String, nullable=True)
    device_port = Column(Integer, default=4370)          # Nouveau champ
    device_password = Column(Integer, default=0)        # Nouveau champ (0 = pas de mot de passe)
    sync_interval = Column(Integer, default=30)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String(50))
    record_id = Column(Integer)
    old_value = Column(Text)
    new_value = Column(Text)
    changed_by = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)