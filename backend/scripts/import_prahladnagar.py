"""One-off import: Prahladnagar Outlet SOP roster.

Tailored to 'Prahladnagar Outlet details.xlsx' whose layout differs from the
generic importer: row 0 is a merged outlet title (not the header), and a
'Work Type' column carries Daily/Weekly/Monthly (the generic importer ignores
frequency). Departments are namespaced 'Prahladnagar - <Section>' so they group
under the Prahladnagar Outlet card and never collide with Thol's KITCHEN SECTION.

Idempotent: aborts if Prahladnagar SOPs already exist (re-run safe).
Usage:  python -m scripts.import_prahladnagar /tmp/prahlad.xlsx [--apply]
"""
import sys
import io
import re
import openpyxl
from sqlalchemy import select, func
from app.database import get_db_context
from app.models.sop import SOPDefinition
from app.services.sop_service import SOPService

DEPT_PREFIX = "Prahladnagar - "

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _section_to_dept(section: str) -> str:
    return DEPT_PREFIX + section.strip().title()


def _weekday_bit(details: str):
    """Return (bitmask|None, matched_day_name|None) from a details string."""
    low = (details or "").lower()
    for name, idx in _WEEKDAYS.items():
        if name in low:
            return (1 << idx), name.title()
    return None, None


def run(path: str, apply: bool):
    wb = openpyxl.load_workbook(io.BytesIO(open(path, "rb").read()), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    # Find the real header row (the one containing 'task name').
    hdr_i = None
    for i, r in enumerate(rows):
        cells = [SOPService._cell_str(c).lower() for c in r]
        if any("task name" in c for c in cells):
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
        "person": col("assigned person", "assigned"),
        "number": col("whatsapp", "number", "mobile"),
        "worktype": col("work type", "frequency", "type"),
    }

    def get(cells, key):
        i = ix[key]
        if i is None or i >= len(cells):
            return None
        return cells[i]

    with get_db_context() as db:
        existing = db.execute(
            select(func.count()).select_from(SOPDefinition)
            .where(SOPDefinition.department.like(DEPT_PREFIX + "%"))
        ).scalar()
        if existing:
            print(f"ABORT: {existing} Prahladnagar SOPs already exist. Delete them first to re-import.")
            return

        svc = SOPService(db)
        section = None
        plan = []  # (dept, payload) for dry-run print

        for ri, raw in enumerate(rows[hdr_i + 1:], start=hdr_i + 2):
            cells = list(raw)
            title = SOPService._cell_str(get(cells, "name"))
            person = SOPService._cell_str(get(cells, "person"))
            number = SOPService._normalize_number(get(cells, "number"))
            start = SOPService._normalize_time(get(cells, "start"))
            details = SOPService._cell_str(get(cells, "details")) or None
            worktype = SOPService._cell_str(get(cells, "worktype")).lower()

            # Section header: title only, no assignee/number.
            if title and not person and not number:
                section = title
                continue
            if not title and not person:
                continue
            if not person or not number:
                print(f"  SKIP R{ri} ('{title}'): missing assignee/number")
                continue

            dept = _section_to_dept(section or "General")

            # Frequency from Work Type, with day extraction from details.
            freq = "daily"
            days_of_week = None
            day_of_month = None
            desc = details
            if "week" in worktype:
                freq = "weekly"
                bit, day_name = _weekday_bit(details)
                days_of_week = bit if bit is not None else (1 << 0)  # default Monday
                # details held the schedule word (e.g. 'Monday'); fold into note.
                desc = f"Weekly: {day_name or 'Monday'}"
            elif "month" in worktype:
                freq = "monthly"
                # 'Last Monday' has no fixed day-of-month; keep human note, leave
                # day_of_month unset (admin can pin a date in the UI later).
                desc = f"Monthly: {details}" if details else "Monthly"

            # Start time + interval handling.
            interval, end = SOPService._parse_end(get(cells, "end"))
            raw_start = SOPService._cell_str(get(cells, "start"))
            if not start:
                # 'Every Hour' / irregular cadence -> interval SOP anchored at 09:00.
                m = re.search(r"every\s*(\d+(?:\.\d+)?)?\s*hour", raw_start.lower())
                if "every hour" in raw_start.lower() or (m and m.group(0)):
                    interval = interval or (float(m.group(1)) if (m and m.group(1)) else 1.0)
                    start = "09:00"
                    desc = (desc + " | " if desc else "") + f"Cadence: {raw_start}"
                elif end:
                    start = end       # e.g. attendance row has only an end time
                    end = None
                else:
                    start = "09:00"
                    if raw_start:
                        desc = (desc + " | " if desc else "") + f"Cadence: {raw_start}"

            payload = {
                "title": title,
                "description": desc,
                "department": dept,
                "frequency": freq,
                "days_of_week": days_of_week,
                "day_of_month": day_of_month,
                "start_time": start,
                "end_time": end,
                "interval_hours": interval,
                "requires_attachment": False,
                "priority": "medium",
            }
            plan.append((person, number, section, payload))

        # Report
        print(f"Parsed {len(plan)} SOP rows across sections:")
        depts = {}
        for _, _, sec, p in plan:
            depts.setdefault(p["department"], 0)
            depts[p["department"]] += 1
        for d, c in depts.items():
            print(f"  {d}: {c}")
        print("\nDetail:")
        for person, number, sec, p in plan:
            print(f"  [{p['department']}] {p['title']} | {p['frequency']}"
                  f"{'/dow='+str(p['days_of_week']) if p['days_of_week'] else ''}"
                  f"{' /every '+str(p['interval_hours'])+'h' if p['interval_hours'] else ''}"
                  f" | {p['start_time']}->{p['end_time']} | {person} {number}")

        if not apply:
            print("\nDRY RUN — pass --apply to insert.")
            return

        created = 0
        for person, number, sec, p in plan:
            role = sec or "Staff"
            emp, _ = svc._upsert_employee(person, number, role, p["department"])
            p["assigned_to_id"] = emp.id
            svc.create(p)
            created += 1
        print(f"\n✅ Inserted {created} SOPs.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "/tmp/prahlad.xlsx"
    run(path, apply="--apply" in sys.argv)
