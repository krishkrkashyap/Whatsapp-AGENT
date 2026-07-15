"""Replace Thol Factory SOPs from the v2 roster sheet.

The v2 sheet ('Krish AiEngineer Bot Data ... .xlsx') is flat with an explicit
Department column (role names: Production Manager, Quality Supervisor, ...) and a
Require-Attachment YES/NO column. Frequency is encoded in the task name
("Daily ...", "Weekly ...", "Every Wedensday ...").

This script:
  1. DELETES every SOP (and its executions) in the OLD Thol Factory departments
     (HOT/COLD SECTION, KITCHEN SECTION, Logistic).
  2. INSERTS the sheet's SOPs namespaced as "Thol Factory - <Role>" so they group
     under the Thol Factory card (the SOPs page uses a 'Thol Factory - ' prefix).

Idempotent on re-import of the NEW depts: aborts insert if "Thol Factory - " SOPs
already exist (delete them first to re-run).

Usage:  python -m scripts.import_thol_v2 /tmp/thol_v2.xlsx [--apply]
"""
import sys
import io
import re
import openpyxl
from sqlalchemy import select, func, text as sql_text
from app.database import get_db_context
from app.models.sop import SOPDefinition
from app.services.sop_service import SOPService

NEW_PREFIX = "Thol Factory - "
OLD_THOL_DEPTS = ["HOT/COLD SECTION", "KITCHEN SECTION", "Logistic"]

# Weekday name -> bitmask bit (Mon=bit0 ... Sun=bit6). Includes the sheet's
# 'wedensday' typo. Order matters only for substring scan; all distinct.
_WEEKDAY_BITS = [
    ("monday", 0), ("tuesday", 1), ("wednesday", 2), ("wedensday", 2),
    ("thursday", 3), ("friday", 4), ("saturday", 5), ("sunday", 6),
]


def _day_bit(name: str):
    low = (name or "").lower()
    for word, idx in _WEEKDAY_BITS:
        if word in low:
            return 1 << idx
    return None


def _frequency(name: str):
    """(frequency, days_of_week|None) inferred from the task name. Weeklies pick up
    a named weekday anywhere in the title (e.g. '... (Thursday)'); default Monday
    when 'weekly' is present but no day is named."""
    low = (name or "").lower()
    if "weekly" in low or "every wed" in low or "wedensday" in low:
        return "weekly", (_day_bit(name) or (1 << 0))
    if "daily" in low:
        return "daily", None
    return "daily", None


def run(path: str, apply: bool):
    wb = openpyxl.load_workbook(io.BytesIO(open(path, "rb").read()), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    # Header row with 'task name'.
    hdr_i = None
    for i, r in enumerate(rows):
        if any("task name" in SOPService._cell_str(c).lower() for c in r):
            hdr_i = i
            break
    if hdr_i is None:
        print("ERROR: no 'Task Name' header row found")
        return
    header = [SOPService._cell_str(c).lower() for c in rows[hdr_i]]

    def col(*needles):
        for i, h in enumerate(header):
            if any(n in h for n in needles):
                return i
        return None

    ix = {
        "name": col("task name"),
        "details": col("task details", "details"),
        "start": col("start"),
        "end": col("end"),
        "attach": col("require attachment", "attachment"),
        "person": col("assigned person", "assigned"),
        "dept": col("department"),
        "number": col("whatsapp", "whasapp", "number", "mobile"),
    }

    def get(cells, key):
        i = ix[key]
        return cells[i] if (i is not None and i < len(cells)) else None

    # Canonical number per person name (first non-empty wins) — the sheet has a
    # few incremented/typo numbers for the same person on weekly rows.
    canonical = {}
    for raw in rows[hdr_i + 1:]:
        nm = SOPService._cell_str(get(list(raw), "person"))
        num = SOPService._normalize_number(get(list(raw), "number"))
        if nm and num and nm not in canonical:
            canonical[nm] = num

    plan = []
    for ri, raw in enumerate(rows[hdr_i + 1:], start=hdr_i + 2):
        cells = list(raw)
        title = SOPService._cell_str(get(cells, "name"))
        person = SOPService._cell_str(get(cells, "person"))
        role = SOPService._cell_str(get(cells, "dept")) or "Staff"
        if not title or not person:
            continue
        number = canonical.get(person) or SOPService._normalize_number(get(cells, "number"))
        if not number:
            print(f"  SKIP R{ri} ('{title[:30]}'): no number for {person}")
            continue
        details = SOPService._cell_str(get(cells, "details")) or None
        start = SOPService._normalize_time(get(cells, "start"))
        interval, end = SOPService._parse_end(get(cells, "end"))
        if not start:
            start = "09:00"
        attach = SOPService._cell_str(get(cells, "attach")).strip().lower().startswith("y")
        freq, dow = _frequency(title)
        dept = NEW_PREFIX + role.strip().title()

        plan.append({
            "person": person, "number": number, "role": role.strip(),
            "payload": {
                "title": title, "description": details, "department": dept,
                "frequency": freq, "days_of_week": dow, "day_of_month": None,
                "start_time": start, "end_time": end, "interval_hours": interval,
                "requires_attachment": attach, "priority": "medium",
            },
        })

    # Report
    from collections import Counter
    by_dept = Counter(p["payload"]["department"] for p in plan)
    print(f"Parsed {len(plan)} SOP rows to insert:")
    for d, c in sorted(by_dept.items()):
        print(f"  {d}: {c}")
    print(f"Attachment-required: {sum(1 for p in plan if p['payload']['requires_attachment'])}")
    print(f"Weekly: {sum(1 for p in plan if p['payload']['frequency'] == 'weekly')}")

    with get_db_context() as db:
        old_count = db.execute(
            select(func.count()).select_from(SOPDefinition)
            .where(SOPDefinition.department.in_(OLD_THOL_DEPTS))
        ).scalar()
        new_exists = db.execute(
            select(func.count()).select_from(SOPDefinition)
            .where(SOPDefinition.department.like(NEW_PREFIX + "%"))
        ).scalar()
        print(f"\nOLD Thol SOPs to DELETE ({', '.join(OLD_THOL_DEPTS)}): {old_count}")
        print(f"Existing '{NEW_PREFIX}' SOPs: {new_exists}")

        if new_exists:
            print(f"ABORT: {new_exists} '{NEW_PREFIX}' SOPs already exist. Delete them first to re-run.")
            return

        if not apply:
            print("\nDRY RUN — pass --apply to delete old + insert new.")
            return

        # 1. Delete old Thol SOPs (+ executions).
        old = db.execute(
            select(SOPDefinition).where(SOPDefinition.department.in_(OLD_THOL_DEPTS))
        ).scalars().all()
        for sop in old:
            db.execute(sql_text("DELETE FROM sop_executions WHERE sop_id=:i"), {"i": sop.id})
            db.delete(sop)
        db.commit()
        print(f"Deleted {len(old)} old Thol SOPs.")

        # 2. Insert new.
        svc = SOPService(db)
        created = 0
        for p in plan:
            emp, _ = svc._upsert_employee(p["person"], p["number"], p["role"], p["payload"]["department"])
            p["payload"]["assigned_to_id"] = emp.id
            svc.create(p["payload"])
            created += 1
        print(f"Inserted {created} new Thol Factory SOPs.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "/tmp/thol_v2.xlsx"
    run(path, apply="--apply" in sys.argv)
