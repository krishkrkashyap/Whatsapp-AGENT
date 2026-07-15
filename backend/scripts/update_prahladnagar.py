"""One-off update: enrich existing Prahladnagar Outlet SOPs from the v2 sheet.

The v2 'Prahladnagar Outlet details (1).xlsx' adds a real *Description* column and
'NEED PHOTO' notes the original import never had. This script MATCHES the SOPs that
already exist (by department + title + start time) and updates:
  - description      (full text from the sheet; cadence note re-appended for
                      weekly/monthly/hourly rows so scheduling context survives)
  - requires_attachment  (True when a 'NEED PHOTO' note is present)
  - attachment_checklist (N-item list when the note says '(N photos)')

It NEVER creates/deletes SOPs and never touches schedule/assignee — enrichment only.
Unmatched sheet rows and unmatched existing SOPs are reported, not guessed.

Usage:  python -m scripts.update_prahladnagar /tmp/prahlad_v2.xlsx [--apply]
"""
import sys
import io
import re
import json
import openpyxl
from sqlalchemy import select
from app.database import get_db_context
from app.models.sop import SOPDefinition
from app.services.sop_service import SOPService

DEPT_PREFIX = "Prahladnagar - "


def _section_to_dept(section: str) -> str:
    return DEPT_PREFIX + section.strip().title()


def _norm_title(t: str) -> str:
    # Drop punctuation (trailing '.', commas) so 'condition .' == 'condition'.
    cleaned = re.sub(r"[^\w\s]", " ", (t or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _photo_info(note_cells) -> tuple:
    """(requires_attachment, photo_count) from the trailing NEED PHOTO notes."""
    blob = " ".join(SOPService._cell_str(c) for c in note_cells).upper()
    if "PHOTO" not in blob:
        return False, 1
    m = re.search(r"\((\d+)\s*PHOTOS?\)", blob)
    return True, (int(m.group(1)) if m else 1)


def run(path: str, apply: bool):
    wb = openpyxl.load_workbook(io.BytesIO(open(path, "rb").read()), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

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
        "desc": col("description", "task details", "details"),
        "start": col("start"),
        "end": col("end"),
        "person": col("assigned person", "assigned"),
        "number": col("whatsapp", "number", "mobile"),
        "worktype": col("work type", "frequency", "type"),
    }
    # Trailing note columns = everything after the work-type column.
    note_start = (ix["worktype"] or 0) + 1

    def get(cells, key):
        i = ix[key]
        if i is None or i >= len(cells):
            return None
        return cells[i]

    # Parse sheet into enrichment records.
    section = None
    records = []  # dict(dept,title,start,desc,req,count,freq)
    for ri, raw in enumerate(rows[hdr_i + 1:], start=hdr_i + 2):
        cells = list(raw)
        title = SOPService._cell_str(get(cells, "name"))
        person = SOPService._cell_str(get(cells, "person"))
        number = SOPService._normalize_number(get(cells, "number"))
        if title and not person and not number:
            section = title          # section header
            continue
        if not title or not person:
            continue
        start = SOPService._normalize_time(get(cells, "start"))
        desc = SOPService._cell_str(get(cells, "desc")) or ""
        worktype = SOPService._cell_str(get(cells, "worktype")).lower()
        req, count = _photo_info(cells[note_start:])

        # Re-append a cadence note for non-clock cadences so context isn't lost.
        raw_start = SOPService._cell_str(get(cells, "start"))
        if not start and raw_start:
            desc = (desc + " | " if desc else "") + f"Cadence: {raw_start}"
        if "week" in worktype:
            desc = (desc + " | " if desc else "") + "Weekly"
        elif "month" in worktype:
            desc = (desc + " | " if desc else "") + "Monthly"

        records.append({
            "dept": _section_to_dept(section or "General"),
            "title": title, "start": start, "desc": desc.strip(),
            "req": req, "count": count,
        })

    with get_db_context() as db:
        existing = db.execute(
            select(SOPDefinition).where(SOPDefinition.department.like(DEPT_PREFIX + "%"))
        ).scalars().all()
        # Index by (dept, norm title) -> list (handles duplicate titles via start).
        idx = {}
        for s in existing:
            idx.setdefault((s.department, _norm_title(s.title)), []).append(s)

        matched, unmatched_rows = [], []
        used = set()
        for rec in records:
            cands = idx.get((rec["dept"], _norm_title(rec["title"])), [])
            cands = [c for c in cands if id(c) not in used]
            if not cands:
                unmatched_rows.append(rec)
                continue
            target = None
            if len(cands) > 1 and rec["start"]:
                target = next((c for c in cands if c.start_time == rec["start"]), None)
            target = target or cands[0]
            used.add(id(target))
            matched.append((rec, target))

        unmatched_existing = [s for s in existing if id(s) not in used]

        print(f"Sheet rows: {len(records)} | Existing SOPs: {len(existing)} | "
              f"Matched: {len(matched)}")
        print("\n--- UPDATES ---")
        for rec, s in matched:
            chk = f" +{rec['count']}photos" if (rec["req"] and rec["count"] > 1) else (" +photo" if rec["req"] else "")
            print(f"  [{s.department}] {s.title} @{s.start_time}{chk}")
            print(f"      desc<- {rec['desc'][:70]}")
        if unmatched_rows:
            print("\n--- SHEET ROWS WITH NO MATCH (skipped) ---")
            for rec in unmatched_rows:
                print(f"  [{rec['dept']}] {rec['title']} @{rec['start']}")
        if unmatched_existing:
            print("\n--- EXISTING SOPs NOT IN SHEET (left unchanged) ---")
            for s in unmatched_existing:
                print(f"  [{s.department}] {s.title} @{s.start_time}")

        if not apply:
            print("\nDRY RUN — pass --apply to write.")
            return

        n = 0
        for rec, s in matched:
            if rec["desc"]:
                s.description = rec["desc"]
            if rec["req"]:
                s.requires_attachment = True
                if rec["count"] > 1:
                    s.attachment_checklist = json.dumps(
                        [f"Photo {i+1}" for i in range(rec["count"])])
            n += 1
        db.commit()
        print(f"\n✅ Updated {n} SOPs.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "/tmp/prahlad_v2.xlsx"
    run(path, apply="--apply" in sys.argv)
