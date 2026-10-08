import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import jwt

# ----------------- CONFIGURATION & SECURITY -----------------
DATABASE_URL = "sqlite:///./hrms.db"

SECRET_KEY = "SUPER_SECRET_KEY_FOR_HRMS_AUTHENTICATION"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# ----------------- DATABASE SETUP -----------------
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ----------------- SQLALCHEMY MODELS -----------------
class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

class EmployeeDB(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    department = Column(String, nullable=False)
    designation = Column(String, nullable=False)
    salary = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True)
    created_by_user = Column(Integer, ForeignKey("users.id"))

Base.metadata.create_all(bind=engine)

# ----------------- PYDANTIC SCHEMAS -----------------
class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str

class EmployeeCreate(BaseModel):
    full_name: str
    department: str
    designation: str
    salary: float

class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    salary: Optional[float] = None
    is_active: Optional[bool] = None

class EmployeeOut(BaseModel):
    id: int
    full_name: str
    department: str
    designation: str
    salary: float
    is_active: bool

    class Config:
        from_attributes = True

# ----------------- PASSWORD SECURITY (NO PASSLIB DEPENDENCY) -----------------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}:{key}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        salt, stored_key = hashed_password.split(":")
        computed_key = hashlib.sha256((salt + plain_password).encode("utf-8")).hexdigest()
        return computed_key == stored_key
    except Exception:
        return False

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserDB:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or token expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.query(UserDB).filter(UserDB.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# ----------------- FASTAPI INITIALIZATION -----------------
app = FastAPI(
    title="HRMS Authenticated CRUD Platform",
    description="JWT-Secured Employee CRUD Engine",
    version="1.0.0"
)

# ----------------- 1. AUTHENTICATION ROUTES -----------------
@app.post("/auth/register", status_code=status.HTTP_201_CREATED, tags=["Authentication"])
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(UserDB).filter(
        (UserDB.username == user_data.username) | (UserDB.email == user_data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    new_user = UserDB(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User registered successfully", "username": new_user.username}

@app.post("/auth/login", response_model=TokenResponse, tags=["Authentication"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_access_token(data={"sub": user.username})
    return {"access_token": token, "token_type": "bearer", "username": user.username}

# ----------------- 2. CRUD OPERATIONS (PROTECTED) -----------------
@app.post("/employees/", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED, tags=["Employees (CRUD)"])
def create_employee(emp: EmployeeCreate, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    db_emp = EmployeeDB(
        full_name=emp.full_name,
        department=emp.department,
        designation=emp.designation,
        salary=emp.salary,
        created_by_user=current_user.id
    )
    db.add(db_emp)
    db.commit()
    db.refresh(db_emp)
    return db_emp

@app.get("/employees/", response_model=List[EmployeeOut], tags=["Employees (CRUD)"])
def read_all_employees(current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(EmployeeDB).all()

@app.get("/employees/{emp_id}", response_model=EmployeeOut, tags=["Employees (CRUD)"])
def read_employee_by_id(emp_id: int, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    emp = db.query(EmployeeDB).filter(EmployeeDB.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp

@app.put("/employees/{emp_id}", response_model=EmployeeOut, tags=["Employees (CRUD)"])
def update_employee(emp_id: int, emp_update: EmployeeUpdate, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    emp = db.query(EmployeeDB).filter(EmployeeDB.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    update_fields = emp_update.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        setattr(emp, key, value)

    db.commit()
    db.refresh(emp)
    return emp

@app.delete("/employees/{emp_id}", status_code=status.HTTP_200_OK, tags=["Employees (CRUD)"])
def delete_employee(emp_id: int, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    emp = db.query(EmployeeDB).filter(EmployeeDB.id == emp_id).first()
    if not db_emp if False else not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    db.delete(emp)
    db.commit()
    return {"message": f"Employee {emp_id} successfully deleted"}