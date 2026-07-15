"""One-time cleanup: normalize existing employee phone numbers and merge the
duplicate rows that the old inconsistent normalization created.

Background
----------
Three import paths used to normalize numbers differently — CSV import and the
webhook prepended a bare '+', while the XLSX/SOP import added the '91' country
code. So the same person was stored twice, e.g.:

    Balram   +919794164362 (Logistic)         <- xlsx import
    Balram   +9794164362   (Factory Operations) <- csv import

The code now routes every entry point through app.utils.helpers.normalize_phone,
so NEW imports won't duplicate. This script fixes the rows already in the DB:

  1. compute the canonical number for every employee
  2. group employees that share a canonical number
  3. in each group, pick one PRIMARY row, repoint all foreign keys
     (tasks, conversation logs, escalations, SOPs, SOP executions) from the
     duplicates to the primary, delete the duplicates, and set the primary's
     number to the canonical form

Usage
-----
    python -m scripts.dedupe_employees          # dry run — prints the plan, no writes
    python -m scripts.dedupe_employees --apply   # perform the merge

Run from the backend/ directory with the same env (.env / DATABASE_URL) the app
uses. BACK UP THE DATABASE before --apply: the merge deletes rows.
"""
import argparse
import sys
from collections import defaultdict

from sqlalchemy import select, update, delete, func

from app.database import SessionLocal
from app.utils.helpers import normalize_phone
from app.models.employee import Employee
from app.models.task import Task
from app.models.conversation import ConversationLog
from app.models.escalation import EscalationTicket
from app.models.sop import SOPDefinition, SOPExecution

# (model, column) pairs that reference employees.id
_FK_REFS = [
    (Task, "assigned_to_id"),
    (Task, "assigned_by_id"),
    (ConversationLog, "employee_id"),
    (EscalationTicket, "employee_id"),
    (EscalationTicket, "assigned_to_id"),
    (SOPDefinition, "assigned_to_id"),
    (SOPDefinition, "admin_id"),
    (SOPExecution, "assigned_to_id"),
]


def _task_count(db, emp_id: str) -> int:
    return db.execute(
        select(func.count()).select_from(Task.__table__).where(
            (Task.assigned_to_id == emp_id) | (Task.assigned_by_id == emp_id)
        )
    ).scalar() or 0


def _pick_primary(db, group):
    """Choose the row to keep. Prefer admins, then active rows, then the row
    with the most task references, then the oldest (most established)."""
    return sorted(
        group,
        key=lambda e: (
            0 if e.is_admin else 1,
            0 if e.is_active else 1,
            -_task_count(db, e.id),
            str(e.created_at) if e.created_at else "9999",
        ),
    )[0]


def main(apply: bool):
    db = SessionLocal()
    try:
        employees = list(db.execute(select(Employee)).scalars().all())
        groups = defaultdict(list)
        for e in employees:
            canon = normalize_phone(e.whatsapp_number)
            if not canon:
                print(f"  ! SKIP (unparseable number): {e.name} [{e.whatsapp_number}]")
                continue
            groups[canon].append(e)

        merges = {k: v for k, v in groups.items() if len(v) > 1}
        renames = {
            k: v[0] for k, v in groups.items()
            if len(v) == 1 and v[0].whatsapp_number != k
        }

        print(f"\nEmployees: {len(employees)} | canonical numbers: {len(groups)} | "
              f"duplicate groups: {len(merges)} | plain renumbers: {len(renames)}\n")

        for canon, group in merges.items():
            primary = _pick_primary(db, group)
            dups = [e for e in group if e.id != primary.id]
            print(f"MERGE {canon}")
            print(f"  keep: {primary.name} | {primary.department}/{primary.role} | "
                  f"{primary.whatsapp_number} | admin={primary.is_admin}")
            for d in dups:
                print(f"  drop: {d.name} | {d.department}/{d.role} | "
                      f"{d.whatsapp_number} | tasks={_task_count(db, d.id)}")
                if apply:
                    for model, col in _FK_REFS:
                        db.execute(
                            update(model).where(getattr(model, col) == d.id).values({col: primary.id})
                        )
                    db.execute(delete(Employee).where(Employee.id == d.id))
            if apply:
                db.execute(
                    update(Employee).where(Employee.id == primary.id).values(whatsapp_number=canon)
                )

        for canon, emp in renames.items():
            print(f"RENUMBER {emp.name}: {emp.whatsapp_number} -> {canon}")
            if apply:
                db.execute(
                    update(Employee).where(Employee.id == emp.id).values(whatsapp_number=canon)
                )

        if apply:
            db.commit()
            print("\n✅ Applied. Duplicates merged and numbers normalized.")
        else:
            print("\n(DRY RUN — no changes written. Re-run with --apply to commit.)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize + dedupe employee phone numbers.")
    parser.add_argument("--apply", action="store_true", help="commit the merge (default: dry run)")
    args = parser.parse_args()
    main(args.apply)
    sys.exit(0)
