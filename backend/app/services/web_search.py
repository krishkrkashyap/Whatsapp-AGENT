"""Keyless web search via DuckDuckGo's HTML endpoint.

Used to answer general/current questions the LLM cannot know (Groq has no
browsing). Result URLs are fetched only after passing nlu._is_safe_url, so the
SSRF protection of the existing webfetch path applies here too.
"""
import re
import logging
from urllib.parse import quote_plus, unquote, urlparse, parse_qs
import httpx

logger = logging.getLogger("web_search")

_ENDPOINT = "https://html.duckduckgo.com/html/"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Matches each result anchor and the following snippet anchor.
_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html)).strip()


def _real_url(href: str) -> str:
    """Decode DuckDuckGo's /l/?uddg=<encoded> redirect wrapper."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        q = parse_qs(parsed.query)
        if "uddg" in q:
            return unquote(q["uddg"][0])
    return href


def search(query: str, max_results: int = 3) -> list:
    """Return up to max_results [{title,url,snippet}] for the query. [] on error."""
    try:
        resp = httpx.get(
            f"{_ENDPOINT}?q={quote_plus(query)}",
            headers={"User-Agent": _UA}, timeout=6, follow_redirects=True,
        )
        if resp.status_code != 200:
            return []
        anchors = _RESULT_RE.findall(resp.text)
        snippets = _SNIPPET_RE.findall(resp.text)
        out = []
        for i, (href, title) in enumerate(anchors[:max_results]):
            out.append({
                "title": _strip(title),
                "url": _real_url(href),
                "snippet": _strip(snippets[i]) if i < len(snippets) else "",
            })
        return out
    except Exception as e:
        logger.warning("DuckDuckGo search failed: %s", e)
        return []


def answer(query: str, language: str = "english") -> str:
    """Search + summarize. Fetches the top 1-2 SSRF-safe results and asks the LLM
    to answer in the user's language. Returns '' when nothing usable."""
    from app.services.nlu import nlu_service
    results = search(query, max_results=3)
    if not results:
        return ""
    parts = []
    fetched = 0
    for r in results:
        parts.append(f"{r['title']}: {r['snippet']}")
        if fetched < 2 and r["url"] and nlu_service._is_safe_url(r["url"]):
            try:
                page = nlu_service.webfetch(r["url"])
                if page and not page.startswith("❌"):
                    parts.append(page[:1500])
                    fetched += 1
            except Exception:
                pass
    context = "\n\n".join(parts).strip()
    if not context:
        return ""
    try:
        return nlu_service.ask(query, context=context, language=language)
    except Exception:
        return ""
