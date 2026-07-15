"""Knowledge Base service — BUG-7 fix + F-11 multi-provider embeddings + language-aware ingest/search."""
import re
import csv
import json
import io
import math
import logging
from typing import Optional, List
from sqlalchemy import select, text
from app.models.kb_document import KBDocument, SourceType
from app.services.nlu import nlu_service
from app.config import settings

logger = logging.getLogger("knowledge_base")

class KBService:
    def __init__(self, db):
        self.db = db

    # ── Embeddings ──────────────────────────────────────────────────────────

    @staticmethod
    def _embeddings_enabled() -> bool:
        """True only when a provider that actually has an embeddings API is
        configured. Groq/Anthropic have none — under them _get_embedding would
        return an all-zero vector, giving NaN cosine similarity so KB search never
        clears the threshold (KB effectively dead). In that case we fall back to
        keyword search and store docs with a NULL embedding instead of junk."""
        if not settings.llm_api_key:
            return False
        prov = (getattr(settings, "embedding_provider", "") or settings.llm_provider or "").lower()
        return prov in ("openai", "voyage", "voyageai", "cohere")

    def _get_embedding(self, input_text: str):
        if not settings.llm_api_key:
            logger.info(f"[DEV] Would embed: {input_text[:50]}")
            return [0.0] * 1536

        provider = getattr(settings, 'embedding_provider', settings.llm_provider)

        try:
            if provider in ("voyage", "voyageai"):
                import voyageai
                client = voyageai.Client(api_key=settings.llm_api_key)
                result = client.embed([input_text], model="voyage-2")
                emb = result.embeddings[0]
            elif provider in ("cohere",):
                import cohere
                client = cohere.Client(settings.llm_api_key)
                result = client.embed(texts=[input_text], model="embed-english-v3.0", input_type="search_document")
                emb = result.embeddings[0]
            else:
                import openai
                client = openai.OpenAI(api_key=settings.llm_api_key)
                response = client.embeddings.create(
                    model="text-embedding-3-small", input=input_text,
                )
                emb = response.data[0].embedding
            # BUG-C3 fix: Ensure embedding is exactly 1536 dims (pad or truncate)
            # This handles Voyage (1024) and Cohere (1024) providers storing into Vector(1536)
            if len(emb) < 1536:
                emb = list(emb) + [0.0] * (1536 - len(emb))
            elif len(emb) > 1536:
                emb = emb[:1536]
            return emb
        except Exception as e:
            logger.warning(f"Embedding failed ({provider}): {e}")
            return [0.0] * 1536

    # ── Chunking ────────────────────────────────────────────────────────────

    def _chunk_text(self, text: str, chunk_size: int = 512):
        """Split text into chunks at sentence boundaries (fallback to word split)."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = []
        current_len = 0
        for s in sentences:
            wc = len(s.split())
            if current_len + wc > chunk_size and current:
                chunks.append(" ".join(current))
                current = [s]
                current_len = wc
            else:
                current.append(s)
                current_len += wc
        if current:
            chunks.append(" ".join(current))
        return chunks if chunks else [text]

    def _chunk_qa(self, q: str, a: str, chunk_size: int = 300) -> List[str]:
        """Chunk a Q&A pair — keep Q&A together if small, else split Q and A separately."""
        content = f"Q: {q}\nA: {a}"
        if len(content.split()) <= chunk_size:
            return [content]
        # Split oversized pairs
        parts = []
        if q:
            parts.append(f"Q: {q}")
        for a_chunk in self._chunk_text(a, chunk_size):
            parts.append(f"Q: {q[:60]}...\nA: {a_chunk}")
        return parts

    # ── Document CRUD ───────────────────────────────────────────────────────

    def add_document(self, title: str, content: str, source_type: str,
                     language: Optional[str] = None, question: Optional[str] = None):
        """Add document with optional language tag. Auto-detect language if not given."""
        if not language:
            language = nlu_service._detect_language(content)
        chunks = self._chunk_text(content, 512)
        emb_on = self._embeddings_enabled()
        for i, chunk in enumerate(chunks):
            embedding = self._get_embedding(chunk) if emb_on else None
            suffix = f" (part {i+1}/{len(chunks)})" if len(chunks) > 1 else ""
            doc_title = f"{question[:80] or title}{suffix}" if question else f"{title}{suffix}"
            doc = KBDocument(
                title=doc_title,
                source_type=SourceType(source_type),
                content=chunk,
                embedding=embedding,
                language=language,
            )
            self.db.add(doc)
        self.db.commit()

    def add_past_resolution(self, question: str, answer: str, language: Optional[str] = None):
        """Store a Q&A resolution with language auto-detect."""
        if not language:
            combined = f"{question} {answer}"
            language = nlu_service._detect_language(combined)
        title = f"Auto-resolved: {question[:80]}"
        content = f"Q: {question}\nA: {answer}"
        self.add_document(title, content, "text", language=language, question=question)

    # ── Bulk Ingest ─────────────────────────────────────────────────────────

    def bulk_ingest(self, items: list) -> dict:
        """Ingest list of Q&A pairs.
        Each item: {"question": str, "answer": str, "language": str (optional), "title": str (optional)}
        Returns summary dict.
        """
        count = 0
        errors = []
        for i, item in enumerate(items):
            try:
                q = item.get("question", "").strip()
                a = item.get("answer", "").strip()
                lang = item.get("language") or None
                title = item.get("title") or f"Bulk import #{i+1}: {q[:60]}"
                if not q or not a:
                    errors.append(f"Item {i+1}: missing question or answer")
                    continue
                content = f"Q: {q}\nA: {a}"
                self.add_document(title, content, "text", language=lang, question=q)
                count += 1
            except Exception as e:
                errors.append(f"Item {i+1}: {e}")
        return {"ingested": count, "errors": errors, "total": len(items)}

    def _parse_csv(self, text_data: str) -> list:
        """Parse CSV string. Expected columns: question, answer [, language [, title]]."""
        reader = csv.DictReader(io.StringIO(text_data))
        items = []
        for row in reader:
            q = row.get("question", "").strip()
            a = row.get("answer", "").strip()
            if not q or not a:
                continue
            item = {"question": q, "answer": a}
            if row.get("language"):
                item["language"] = row["language"].strip()
            if row.get("title"):
                item["title"] = row["title"].strip()
            items.append(item)
        return items

    def _parse_json(self, text_data: str) -> list:
        """Parse JSON string. Expects array of {question, answer, language?, title?}."""
        data = json.loads(text_data)
        if isinstance(data, dict):
            data = [data]
        items = []
        for item in data:
            q = item.get("question", "").strip()
            a = item.get("answer", "").strip()
            if not q or not a:
                continue
            cleaned = {"question": q, "answer": a}
            if item.get("language"):
                cleaned["language"] = item["language"].strip()
            if item.get("title"):
                cleaned["title"] = item["title"].strip()
            items.append(cleaned)
        return items

    def ingest_file(self, filename: str, file_bytes: bytes) -> dict:
        """Ingest a CSV or JSON file. Auto-detect format from filename."""
        text_data = file_bytes.decode("utf-8-sig")
        if filename.lower().endswith(".csv"):
            items = self._parse_csv(text_data)
        elif filename.lower().endswith(".json"):
            items = self._parse_json(text_data)
        else:
            return {"ingested": 0, "errors": ["Unsupported format. Use .csv or .json"], "total": 0}
        if not items:
            return {"ingested": 0, "errors": ["No valid Q&A pairs found in file"], "total": 0}
        return self.bulk_ingest(items)

    # ── Language-aware Search ───────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5, language: Optional[str] = None):
        """Search KB. If language given, prefer docs in that language (vector + language filter).
        When vector embeddings unavailable, fallback to ILIKE with language filter.
        """
        if not self._embeddings_enabled():
            return self._keyword_search(query, top_k, language)

        query_emb = self._get_embedding(query)
        emb_str = str(query_emb)

        if language and language != "english":
            # Filter by language AND boost language matches in vector search
            sql = text("""
                SELECT id, title, content, language,
                       1 - (embedding <=> :query_emb) AS similarity
                FROM kb_documents
                WHERE embedding IS NOT NULL AND language = :lang
                ORDER BY similarity DESC
                LIMIT :top_k
            """)
            rows = self.db.execute(sql, {"query_emb": emb_str, "lang": language, "top_k": top_k}).fetchall()
            # If few results in target language, supplement with cross-language results
            if len(rows) < min(top_k, 3):
                existing_ids = [r[0] for r in rows]
                # BUG-C2 fix: Use ANY() with array parameter instead of broken NOT IN :exclude
                if existing_ids:
                    sql2 = text("""
                        SELECT id, title, content, language,
                               1 - (embedding <=> :query_emb) * 0.85 AS similarity
                        FROM kb_documents
                        WHERE embedding IS NOT NULL AND id != ALL(:exclude)
                        ORDER BY similarity DESC
                        LIMIT :fill
                    """)
                    fill = self.db.execute(sql2, {
                        "query_emb": emb_str, "exclude": existing_ids,
                        "fill": top_k - len(rows)
                    }).fetchall()
                else:
                    sql2 = text("""
                        SELECT id, title, content, language,
                               1 - (embedding <=> :query_emb) * 0.85 AS similarity
                        FROM kb_documents
                        WHERE embedding IS NOT NULL
                        ORDER BY similarity DESC
                        LIMIT :fill
                    """)
                    fill = self.db.execute(sql2, {
                        "query_emb": emb_str,
                        "fill": top_k - len(rows)
                    }).fetchall()
                rows.extend(fill)
        else:
            sql = text("""
                SELECT id, title, content, language,
                       1 - (embedding <=> :query_emb) AS similarity
                FROM kb_documents
                WHERE embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT :top_k
            """)
            rows = self.db.execute(sql, {"query_emb": emb_str, "top_k": top_k}).fetchall()

        return [
            {"id": r[0], "title": r[1], "content": r[2], "language": r[3],
             "similarity": 0.0 if math.isnan(float(r[4])) else float(r[4])}
            for r in rows
        ]

    def _keyword_search(self, query: str, top_k: int = 5, language: Optional[str] = None) -> list:
        """Fallback keyword search (when no embedding API key)."""
        safe_query = re.sub(r"[%_\\]", lambda m: "\\" + m.group(), query)
        if language and language != "english":
            result = self.db.execute(
                select(KBDocument)
                .where(KBDocument.content.ilike(f"%{safe_query}%", escape="\\"))
                .where(KBDocument.language == language)
                .limit(top_k)
            )
        else:
            result = self.db.execute(
                select(KBDocument)
                .where(KBDocument.content.ilike(f"%{safe_query}%", escape="\\"))
                .limit(top_k)
            )
        rows = result.scalars().all()
        return [{"id": r.id, "title": r.title, "content": r.content,
                 "language": r.language, "similarity": 0.5} for r in rows]

    # ── Utility ─────────────────────────────────────────────────────────────

    def list_documents(self, limit: int = 50, language: Optional[str] = None):
        query = select(KBDocument).order_by(KBDocument.created_at.desc())
        if language:
            query = query.where(KBDocument.language == language)
        result = self.db.execute(query.limit(limit))
        return list(result.scalars().all())

    def get_languages(self) -> list:
        """Return list of languages present in KB with doc counts."""
        sql = text("""
            SELECT language, COUNT(*) as count
            FROM kb_documents
            GROUP BY language
            ORDER BY count DESC
        """)
        rows = self.db.execute(sql).fetchall()
        return [{"language": r[0], "count": r[1]} for r in rows]

    def delete_document(self, doc_id: str):
        result = self.db.execute(select(KBDocument).where(KBDocument.id == doc_id))
        doc = result.scalar_one_or_none()
        if doc:
            self.db.delete(doc)
            self.db.commit()
            return True
        return False