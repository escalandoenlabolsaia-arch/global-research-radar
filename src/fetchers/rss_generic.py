"""Fetcher RSS genérico — cualquier instituto/revista = 1 línea en sources.yaml.
Un feed caído NUNCA frena la corrida: se loguea y se sigue.
"""
import logging
import re
from email.utils import parsedate_to_datetime
from html import unescape

import feedparser

from src.fetchers.common import get

log = logging.getLogger(__name__)

_TAGS = re.compile(r"<[^>]+>")


def _iso(raw):
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except Exception:
        return raw[:10]


def _clean_summary(s):
    return " ".join(_TAGS.sub(" ", unescape(s or "")).split())


def fetch(cfg):
    feeds = cfg.get("rss", {}).get("feeds", [])
    items = []
    for f in feeds:
        name, url = f.get("name", "rss"), (f.get("url") or "").strip()
        if not url:
            continue
        try:
            resp = get(url, timeout=30)
            feed = feedparser.parse(resp.content)
            n = 0
            for e in feed.entries:
                title = " ".join((e.get("title") or "").split())
                if not title:
                    continue
                items.append({
                    "source": f"rss:{name}",
                    "doi": None,
                    "title": title,
                    "url": e.get("link", ""),
                    "summary": _clean_summary(e.get("summary", ""))[:1200],
                    "published": _iso(e.get("published") or e.get("updated")),
                    "lang": f.get("lang", "en"),
                    "authors": [e.get("author", "")] if e.get("author") else [],
                    "categories": [t.get("term", "") for t in e.get("tags", [])][:5],
                })
                n += 1
            log.info("rss:%s → %d ítems", name, n)
        except Exception as ex:
            log.warning("rss:%s falló (%s) — la corrida sigue", name, ex)
    return items
