from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query, Body
from typing import Optional
from app.database import get_db
from app.services.knowledge_base import KBService
from app.routers.auth import verify_token
from app.services.audit import AuditService
from PyPDF2 import PdfReader
import io
import json

router = APIRouter()


def _get_kb_svc(db):
    return KBService(db)


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/documents")
async def list_kb_documents(
    language: Optional[str] = Query(None, description="Filter by language"),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    svc = _get_kb_svc(db)
    docs = svc.list_documents(limit=50, language=language)
    return [{
        "id": d.id, "title": d.title, "source_type": d.source_type.value,
        "language": d.language,
        "content_preview": d.content[:200],
        "created_at": str(d.created_at),
    } for d in docs]


# ── Languages ──────────────────────────────────────────────────────────────────

@router.get("/languages")
async def list_languages(db=Depends(get_db), _user=Depends(verify_token)):
    svc = _get_kb_svc(db)
    return svc.get_languages()


# ── Upload (file / raw text) ──────────────────────────────────────────────────

@router.post("/upload")
async def upload_kb(
    file: UploadFile = None,
    title: str = Form(...),
    content: str = Form(""),
    language: Optional[str] = Form(None, description="Auto-detect if empty"),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    svc = _get_kb_svc(db)
    if file:
        file_bytes = await file.read()
        if file.filename.endswith(".pdf"):
            pdf = PdfReader(io.BytesIO(file_bytes))
            content = "\n".join(
                page.extract_text() or "" for page in pdf.pages
            )
            source = "pdf"
        elif file.filename.endswith(".txt"):
            content = file_bytes.decode("utf-8")
            source = "text"
        else:
            raise HTTPException(400, "Only PDF and TXT supported")
    else:
        source = "text"

    if not content:
        raise HTTPException(400, "No content to index")

    svc.add_document(title, content, source, language=language)

    AuditService(db).log(
        action="kb.upload", resource_type="kb_document",
        actor_name=_user, details={"title": title, "chars": len(content), "language": language or "auto"},
    )

    return {"status": "indexed", "title": title, "chars": len(content), "language": language or "auto"}


# ── Search ────────────────────────────────────────────────────────────────────

@router.post("/search")
async def search_kb(
    query: str = Form(...),
    top_k: int = Form(5),
    language: Optional[str] = Form(None, description="Filter by language"),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    svc = _get_kb_svc(db)
    results = svc.search(query, top_k=top_k, language=language)
    return results


# ── Bulk Ingest (JSON body) ──────────────────────────────────────────────────

@router.post("/ingest")
async def ingest_kb(
    items: list = Body(..., description="Array of {question, answer, language?, title?}"),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    svc = _get_kb_svc(db)
    result = svc.bulk_ingest(items)
    AuditService(db).log(
        action="kb.ingest", resource_type="kb_document",
        actor_name=_user,
        details={"ingested": result["ingested"], "total": result["total"], "errors": len(result["errors"])},
    )
    return result


# ── Bulk Ingest from File ─────────────────────────────────────────────────────

@router.post("/ingest-file")
async def ingest_kb_file(
    file: UploadFile = File(...),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    svc = _get_kb_svc(db)
    file_bytes = await file.read()
    result = svc.ingest_file(file.filename, file_bytes)
    AuditService(db).log(
        action="kb.ingest_file", resource_type="kb_document",
        actor_name=_user,
        details={"filename": file.filename, "ingested": result["ingested"], "total": result["total"]},
    )
    return result


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{doc_id}")
async def delete_kb_document(doc_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    svc = _get_kb_svc(db)
    if svc.delete_document(doc_id):
        AuditService(db).log(
            action="kb.delete", resource_type="kb_document", resource_id=doc_id,
            actor_name=_user,
        )
        return {"status": "deleted"}
    raise HTTPException(404, "Document not found")