from pydantic import BaseModel

class EmployeeCreate(BaseModel):
    name: str
    department: str
    role: str
    whatsapp_number: str
    is_admin: bool = False

class EmployeeOut(BaseModel):
    id: str
    name: str
    department: str
    role: str
    whatsapp_number: str
    is_admin: bool
    is_active: bool

    class Config:
        from_attributes = True
