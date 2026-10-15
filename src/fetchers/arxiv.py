"""Fetcher arXiv — preprints de física/CS/mate/bio cuantitativa.
API Atom pública, 1 request por corrida.
"""
import logging

import feedparser

from src.fetchers.common import get

log = logging.getLogger(__name__)

API = "https://export.arxiv.org/api/query"


def fetch(cfg):
    ax = cfg.get("arxiv", {})
    cats = ax.get("categories", [])
    max_results = int(ax.get("max_results", 100))
    if not cats:
        return []

    params = {
        "search_query": " OR ".join(f"cat:{c}" for c in cats),
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    resp = get(API, params=params, timeout=90)
    feed = feedparser.parse(resp.text)

    items = []
    for e in feed.entries:
        doi = None
        for l in e.get("links", []):
            if l.get("title") == "doi" and l.get("href"):
                doi = l["href"].replace("https://doi.org/", "").lower()
        items.append({
            "source": "arxiv",
            "doi": doi,
            "title": " ".join((e.get("title") or "").split()),
            "url": e.get("link", ""),
            "summary": " ".join((e.get("summary") or "").split())[:1200],
            "published": (e.get("published") or "")[:10],
            "lang": "en",
            "authors": [a.get("name", "") for a in e.get("authors", [])][:8],
            "categories": [t.get("term", "") for t in e.get("tags", [])][:5],
        })
    log.info("arxiv: %d ítems (%s)", len(items), ", ".join(cats))
    return items
