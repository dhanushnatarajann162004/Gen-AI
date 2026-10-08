from datetime import datetime, date
from typing import List, Optional
from uuid import UUID, uuid4
from enum import Enum
from pydantic import BaseModel, EmailStr, Field
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="HRMS Core API",
    description="Backend API for Employee Directory, Attendance, and Leave Management",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ---
class RoleEnum(str, Enum):
    ADMIN = "ADMIN"
    HR = "HR"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"

class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    HALF_DAY = "HALF_DAY"
    ABSENT = "ABSENT"

class LeaveType(str, Enum):
    CASUAL = "CASUAL"
    SICK = "SICK"
    EARNED = "EARNED"

class EmployeeCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    department: str
    designation: str
    role: RoleEnum = RoleEnum.EMPLOYEE
    base_salary: float = Field(..., gt=0)

class EmployeeResponse(BaseModel):
    id: UUID
    employee_code: str
    first_name: str
    last_name: str
    email: EmailStr
    department: str
    designation: str
    role: RoleEnum
    is_active: bool

class AttendanceRecord(BaseModel):
    user_id: UUID
    work_date: date
    check_in_time: datetime
    check_out_time: Optional[datetime] = None
    active_hours: float = 0.0
    status: AttendanceStatus

class LeaveRequestCreate(BaseModel):
    user_id: UUID
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str


db_employees: dict[UUID, dict] = {}
db_attendance: list[AttendanceRecord] = []
db_leaves: list[dict] = []


@app.get("/")
def health_check():
    return {"status": "online", "system": "HRMS Core Engine"}

@app.post("/employees", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
def create_employee(emp: EmployeeCreate):
    emp_id = uuid4()
    code = f"EMP-{len(db_employees) + 101}"
    record = emp.model_dump()
    record.update({"id": emp_id, "employee_code": code, "is_active": True})
    db_employees[emp_id] = record
    return record

@app.get("/employees", response_model=List[EmployeeResponse])
def list_employees():
    return list(db_employees.values())

@app.post("/attendance/check-in/{user_id}", response_model=AttendanceRecord)
def check_in(user_id: UUID):
    if user_id not in db_employees:
        raise HTTPException(status_code=404, detail="Employee not found")

    today = date.today()
    for record in db_attendance:
        if record.user_id == user_id and record.work_date == today:
            raise HTTPException(status_code=400, detail="Already checked in today")

    new_record = AttendanceRecord(
        user_id=user_id,
        work_date=today,
        check_in_time=datetime.now(),
        status=AttendanceStatus.PRESENT
    )
    db_attendance.append(new_record)
    return new_record

@app.post("/attendance/check-out/{user_id}", response_model=AttendanceRecord)
def check_out(user_id: UUID):
    today = date.today()
    record = next((r for r in db_attendance if r.user_id == user_id and r.work_date == today), None)
    
    if not record:
        raise HTTPException(status_code=400, detail="No active check-in record found for today")
    if record.check_out_time is not None:
        raise HTTPException(status_code=400, detail="Already checked out today")

    record.check_out_time = datetime.now()
    duration_seconds = (record.check_out_time - record.check_in_time).total_seconds()
    record.active_hours = round(duration_seconds / 3600.0, 2)

    if record.active_hours >= 8.0:
        record.status = AttendanceStatus.PRESENT
    elif record.active_hours >= 4.5:
        record.status = AttendanceStatus.HALF_DAY
    else:
        record.status = AttendanceStatus.ABSENT

    return record

@app.post("/leaves/apply", status_code=status.HTTP_201_CREATED)
def apply_leave(leave: LeaveRequestCreate):
    if leave.user_id not in db_employees:
        raise HTTPException(status_code=404, detail="Employee not found")
    if leave.start_date > leave.end_date:
        raise HTTPException(status_code=400, detail="start_date cannot be after end_date")

    leave_id = uuid4()
    days = (leave.end_date - leave.start_date).days + 1
    leave_data = leave.model_dump()
    leave_data.update({
        "leave_id": leave_id,
        "total_days": days,
        "status": "PENDING"
    })
    db_leaves.append(leave_data)
    return {"message": "Leave application submitted", "leave_id": leave_id, "days": days}