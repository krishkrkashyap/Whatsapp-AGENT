"""Employee service — F-2 deactivate, F-20 self-registration, F-4 departments."""
import csv
import io
import logging
from sqlalchemy import select, or_, func
from app.models.employee import Employee

logger = logging.getLogger("employee_svc")

class EmployeeService:
    def __init__(self, db):
        self.db = db

    def get_by_whatsapp(self, number: str):
        result = self.db.execute(
            select(Employee).where(
                Employee.whatsapp_number == number,
                Employee.is_active == True
            )
        )
        return result.scalar_one_or_none()

    def get_by_id(self, emp_id: str):
        result = self.db.execute(
            select(Employee).where(Employee.id == emp_id)
        )
        return result.scalar_one_or_none()

    def get_by_name_or_mention(self, text: str):
        """Resolve a name/@mention/role/department/number to a single employee.

        BUG fix: the previous broad OR-ILIKE used scalar_one_or_none(), which
        raises MultipleResultsFound whenever the term matched more than one
        active employee (common with 500 staff: "@Raj" -> Raj Patel + Rajesh,
        or any role/department word). We now resolve in order of specificity and
        always take the first match so it can never crash.
        """
        clean = text.strip().lstrip("@").lower()
        if not clean:
            return None

        # 1. Exact name match (most specific).
        exact = self.db.execute(
            select(Employee)
            .where(Employee.name.ilike(clean), Employee.is_active == True)
            .limit(1)
        ).scalars().first()
        if exact:
            return exact

        # 2. Name starts-with, then name contains (prefer the shortest name so
        #    "@raj" picks "Raj" over "Rajeshwari" when both exist).
        for pattern in (f"{clean}%", f"%{clean}%"):
            match = self.db.execute(
                select(Employee)
                .where(Employee.name.ilike(pattern), Employee.is_active == True)
                .order_by(func.length(Employee.name))
                .limit(1)
            ).scalars().first()
            if match:
                return match

        # 3. Fall back to role / department / number — crash-safe (.first()).
        return self.db.execute(
            select(Employee)
            .where(
                or_(
                    Employee.role.ilike(f"%{clean}%"),
                    Employee.department.ilike(f"%{clean}%"),
                    Employee.whatsapp_number.ilike(f"%{clean}%"),
                ),
                Employee.is_active == True,
            )
            .order_by(func.length(Employee.name))
            .limit(1)
        ).scalars().first()

    def import_csv(self, csv_content: str) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        from app.utils.helpers import normalize_phone
        for row in reader:
            num = normalize_phone(row.get("whatsapp_number", "").strip())
            if not num:
                continue
            exists = self.db.execute(
                select(Employee).where(Employee.whatsapp_number == num)
            )
            if exists.scalar_one_or_none():
                continue
            emp = Employee(
                name=row.get("name", "").strip(),
                department=row.get("department", "").strip(),
                role=row.get("role", "").strip(),
                whatsapp_number=num,
                is_admin=row.get("is_admin", "false").lower() in ("true", "yes", "1"),
                registered_via="csv",
            )
            self.db.add(emp)
            count += 1
        self.db.commit()
        return count

    def list_all(self):
        result = self.db.execute(
            select(Employee).where(Employee.is_active == True).order_by(Employee.name)
        )
        return list(result.scalars().all())

    def list_all_including_inactive(self):
        result = self.db.execute(
            select(Employee).order_by(Employee.name)
        )
        return list(result.scalars().all())

    def get_all_admins(self):
        result = self.db.execute(
            select(Employee).where(
                Employee.is_admin == True,
                Employee.is_active == True
            ).order_by(Employee.name)
        )
        return list(result.scalars().all())

    def resolve_escalation_recipients(self, task_admin=None):
        """Pick who gets an escalation alert — never the whole admin group.

        1. The task's own assigner, when the escalation is tied to a task.
        2. Else the single admin configured in the `escalation_recipient`
           setting (by WhatsApp number).
        3. Else the first admin only — a safe fallback that still avoids
           blasting every admin.
        """
        if task_admin and task_admin.is_admin and task_admin.is_active:
            return [task_admin]
        from app.routers.settings import get_str_setting
        num = get_str_setting(self.db, "escalation_recipient")
        if num:
            rec = self.get_by_whatsapp(num)
            if rec and rec.is_admin and rec.is_active:
                return [rec]
        admins = self.get_all_admins()
        return admins[:1]

    def deactivate(self, emp_id: str):
        """F-2: Deactivate an employee (soft delete)."""
        emp = self.get_by_id(emp_id)
        if emp:
            emp.is_active = False
            self.db.commit()
            return True
        return False

    def activate(self, emp_id: str):
        """Reactivate a deactivated employee."""
        emp = self.get_by_id(emp_id)
        if emp:
            emp.is_active = True
            self.db.commit()
            return True
        return False

    def update_employee(self, emp_id: str, **kwargs):
        """Update employee fields."""
        emp = self.get_by_id(emp_id)
        if not emp:
            return None
        for key, value in kwargs.items():
            if hasattr(emp, key) and value is not None:
                setattr(emp, key, value)
        self.db.commit()
        self.db.refresh(emp)
        return emp

    def get_departments(self):
        """F-4: Get list of unique departments from database."""
        result = self.db.execute(
            select(Employee.department).where(Employee.is_active == True).distinct()
        )
        return sorted([r[0] for r in result.fetchall() if r[0]])

    def get_department_stats(self):
        """Get employee count per department."""
        result = self.db.execute(
            select(Employee.department, func.count(Employee.id))
            .where(Employee.is_active == True)
            .group_by(Employee.department)
        )
        return {row[0]: row[1] for row in result.fetchall()}
