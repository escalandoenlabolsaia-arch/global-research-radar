"""Fetcher OpenAlex — columna vertebral (~250M trabajos, todos los países).
Sin API key. Polite pool vía mailto del config. Paginación por cursor.
"""
import logging
import time
from datetime import date, timedelta

from src.fetchers.common import get

log = logging.getLogger(__name__)

API = "https://api.openalex.org/works"

SELECT = ",".join([
    "id", "doi", "display_name", "publication_date",
    "authorships", "primary_location", "abstract_inverted_index",
    "language", "concepts",
])


def _rebuild_abstract(inv):
    """OpenAlex guarda el abstract como índice invertido: {palabra: [posiciones]}."""
    if not inv:
        return ""
    try:
        pares = [(pos, w) for w, poss in inv.items() for pos in poss]
        return " ".join(w for _, w in sorted(pares))
    except Exception:
        return ""


def _to_item(w):
    doi = (w.get("doi") or "").replace("https://doi.org/", "").lower() or None
    loc = w.get("primary_location") or {}
    url = (loc.get("landing_page_url") or "") \
        or (f"https://doi.org/{doi}" if doi else (w.get("id") or ""))
    authors = []
    for a in (w.get("authorships") or [])[:8]:
        name = (a.get("author") or {}).get("display_name") or ""
        if name:
            authors.append(name)
    cats = []
    for c in (w.get("concepts") or []):
        if c.get("score", 0) >= 0.3 and c.get("display_name"):
            cats.append(c["display_name"])
        if len(cats) >= 5:
            break
    return {
        "source": "openalex",
        "doi": doi,
        "title": (w.get("display_name") or "").strip(),
        "url": url,
        "summary": _rebuild_abstract(w.get("abstract_inverted_index"))[:1200],
        "published": (w.get("publication_date") or "")[:10],
        "lang": w.get("language") or "",
        "authors": authors,
        "categories": cats,
    }


def fetch(cfg):
    oa = cfg.get("openalex", {})
    days_back = int(oa.get("days_back", 2))
    per_page = min(int(oa.get("per_page", 100)), 200)
    max_pages = int(oa.get("max_pages", 2))
    email = cfg.get("polite_email", "")

    desde = (date.today() - timedelta(days=days_back)).isoformat()
    params = {
        "filter": f"from_publication_date:{desde}",
        "sort": "publication_date:desc",
        "select": SELECT,
        "per-page": per_page,
        "mailto": email,
    }

    items = []
    cursor = "*"
    for _ in range(max_pages):
        data = get(API, params=dict(params, cursor=cursor), timeout=60).json()
        for w in data.get("results", []):
            try:
                items.append(_to_item(w))
            except Exception as e:
                log.warning("openalex: ítem descartado (%s)", e)
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(0.2)
    log.info("openalex: %d ítems (desde %s)", len(items), desde)
    return items
