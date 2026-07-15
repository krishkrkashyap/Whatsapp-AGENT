from datetime import datetime, timezone, timedelta
from app.models.employee import Employee
from app.models.task import Task, Priority, TaskStatus
from app.services import ops_tools


def _emp(db, name="Krish", admin=False, dept="IT"):
    e = Employee(name=name, department=dept, role="Staff",
                 whatsapp_number=f"+9100000{len(name)}{int(admin)}", is_admin=admin)
    db.add(e); db.commit(); db.refresh(e)
    return e


def _task(db, owner_id, title, status=TaskStatus.pending, due=None):
    t = Task(title=title, priority=Priority.medium, status=status,
             assigned_by_id="admin1", assigned_to_id=owner_id,
             assigned_at=datetime.now(timezone.utc), due_date=due)
    db.add(t); db.commit(); db.refresh(t)
    return t


def test_my_pending_tasks_lists_only_own_open_tasks(db):
    me = _emp(db, "Krish")
    other = _emp(db, "Sandeep")
    _task(db, me.id, "Clean oven")
    _task(db, me.id, "Old task", status=TaskStatus.done)
    _task(db, other.id, "Not mine")
    out = ops_tools.my_pending_tasks(me, db)
    assert "Clean oven" in out
    assert "Old task" not in out      # done excluded
    assert "Not mine" not in out      # other employee excluded


def test_my_pending_tasks_empty(db):
    me = _emp(db, "Krish")
    assert "no pending" in ops_tools.my_pending_tasks(me, db).lower()


def test_task_lookup_matches_by_substring(db):
    me = _emp(db, "Krish")
    _task(db, me.id, "Send daily production report")
    out = ops_tools.task_lookup(me, db, query="production")
    assert "production report" in out.lower()
    assert "pending" in out.lower()


from app.models.sop import SOPDefinition, Frequency, SOPStatus


def _sop(db, title, owner_id, dept="Prahladnagar - Kitchen Section", start="09:00"):
    s = SOPDefinition(title=title, department=dept, frequency=Frequency.daily,
                      start_time=start, assigned_to_id=owner_id, status=SOPStatus.active)
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_who_owns_sop_names_assignee(db):
    me = _emp(db, "Krish")
    worker = _emp(db, "Narendra", dept="Prahladnagar - Kitchen Section")
    _sop(db, "Kitchen Floor Cleaning", worker.id, start="09:00")
    out = ops_tools.who_owns_sop(me, db, name="floor")
    assert "Narendra" in out
    assert "Kitchen Floor Cleaning" in out
    assert "09:00" in out


def test_who_owns_sop_not_found(db):
    me = _emp(db, "Krish")
    assert "no sop" in ops_tools.who_owns_sop(me, db, name="zzz").lower()


def test_sop_schedule_today_filters_by_dept(db):
    me = _emp(db, "Krish")
    w = _emp(db, "Narendra", dept="Prahladnagar - Kitchen Section")
    _sop(db, "Kitchen Opening", w.id, dept="Prahladnagar - Kitchen Section", start="09:00")
    _sop(db, "Shop Open", w.id, dept="Prahladnagar - Seating Area", start="08:20")
    out = ops_tools.sop_schedule_today(me, db, dept="Kitchen")
    assert "Kitchen Opening" in out
    assert "Shop Open" not in out


def test_team_status_lists_all_open_tasks(db):
    admin = _emp(db, "Aditya", admin=True)
    a = _emp(db, "Krish")
    b = _emp(db, "Sandeep")
    _task(db, a.id, "Task A")
    _task(db, b.id, "Task B")
    out = ops_tools.team_status(admin, db)
    assert "Task A" in out and "Task B" in out
    assert "Krish" in out and "Sandeep" in out


def test_overdue_tasks_lists_past_due(db):
    admin = _emp(db, "Aditya", admin=True)
    a = _emp(db, "Krish")
    past = datetime.now(timezone.utc) - timedelta(days=2)
    _task(db, a.id, "Late task", due=past)
    _task(db, a.id, "Future task", due=datetime.now(timezone.utc) + timedelta(days=2))
    out = ops_tools.overdue_tasks(admin, db)
    assert "Late task" in out
    assert "Future task" not in out


def test_staff_lookup_returns_role_dept(db):
    admin = _emp(db, "Aditya", admin=True)
    _emp(db, "Narendra", dept="Prahladnagar - Kitchen Section")
    out = ops_tools.staff_lookup(admin, db, name="Narendra")
    assert "Narendra" in out
    assert "Kitchen Section" in out


def test_dispatch_self_tool_runs(db):
    me = _emp(db, "Krish")
    _task(db, me.id, "Clean oven")
    out = ops_tools.dispatch("my_pending_tasks", {}, me, db)
    assert "Clean oven" in out


def test_dispatch_admin_tool_blocked_for_employee(db):
    me = _emp(db, "Krish")  # not admin
    out = ops_tools.dispatch("team_status", {}, me, db)
    assert "only" in out.lower() or "admin" in out.lower()


def test_dispatch_admin_tool_allowed_for_admin(db):
    admin = _emp(db, "Aditya", admin=True)
    a = _emp(db, "Krish")
    _task(db, a.id, "Task A")
    out = ops_tools.dispatch("team_status", {}, admin, db)
    assert "Task A" in out


def test_dispatch_unknown_tool_returns_empty(db):
    me = _emp(db, "Krish")
    assert ops_tools.dispatch("no_such_tool", {}, me, db) == ""


def test_dispatch_passes_args(db):
    me = _emp(db, "Krish")
    _task(db, me.id, "Send production report")
    out = ops_tools.dispatch("task_lookup", {"query": "production"}, me, db)
    assert "production" in out.lower()


def test_tool_catalog_lists_tools():
    cat = ops_tools.tool_catalog()
    assert "my_pending_tasks" in cat and "team_status" in cat
