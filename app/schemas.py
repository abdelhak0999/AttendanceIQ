from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime

class UserBase(BaseModel):
    username: str
    role: str = "manager"

class UserCreate(UserBase):
    password: str

class UserOut(UserBase):
    id: int
    class Config:
        from_attributes = True

class EmployeeBase(BaseModel):
    matricule: str
    name: str
    department_id: Optional[int] = None
    shift_id: Optional[int] = None
    is_active: bool = True

class EmployeeCreate(EmployeeBase):
    pass

class EmployeeOut(EmployeeBase):
    id: int
    department: Optional[str] = None
    shift_name: Optional[str] = None
    class Config:
        from_attributes = True

class ShiftBase(BaseModel):
    name: str
    start_time: str
    end_time: str

class ShiftCreate(ShiftBase):
    pass

class ShiftOut(ShiftBase):
    id: int
    class Config:
        from_attributes = True

class HolidayCreate(BaseModel):
    date_str: str
    name: str

class HolidayOut(BaseModel):
    id: int
    date: date
    name: str
    class Config:
        from_attributes = True

class LeaveCreate(BaseModel):
    employee_id: int
    start_date: str
    end_date: str
    leave_type: str

class LeaveOut(BaseModel):
    id: int
    employee_name: str
    start: date
    end: date
    type: str
    class Config:
        from_attributes = True

class AbsenceOut(BaseModel):
    id: int
    employee_name: str
    matricule: str
    department: Optional[str]
    absence_date: date
    justification: Optional[str]
    notes: Optional[str]
    class Config:
        from_attributes = True

class BulkShiftAssign(BaseModel):
    employee_ids: List[int]
    shift_id: Optional[int] = None

class SystemSettingOut(BaseModel):
    grace_period: int
    device_ip: Optional[str]
    device_port: int          # Nouveau
    device_password: int      # Nouveau
    sync_interval: int
    class Config:
        from_attributes = True