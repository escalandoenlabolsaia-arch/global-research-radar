"""Normalización — un esquema único + id estable para todo el radar."""
import hashlib
import re
import unicodedata

_WS = re.compile(r"\s+")
_NOACS = re.compile(r"[^a-z0-9 ]+")


def clean_text(s: str) -> str:
    return " ".join((s or "").split())


def normalize_title(title: str) -> str:
    """Minúsculas, sin acentos, sin puntuación — base del dedup fuzzy."""
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _NOACS.sub(" ", t.lower())
    return _WS.sub(" ", t).strip()


def item_id(item: dict) -> str:
    """DOI si hay; si no, SHA256 del título normalizado (regla del manual §6)."""
    if item.get("doi"):
        return f"doi:{item['doi'].lower()}"
    nt = normalize_title(item.get("title", ""))
    return "sha:" + hashlib.sha256(nt.encode("utf-8")).hexdigest()[:32]


def finalize(items: list) -> list:
    """Asigna id, limpia textos, descarta ítems sin título o sin URL."""
    out = []
    for it in items:
        it["title"] = clean_text(it.get("title", ""))
        it["summary"] = clean_text(it.get("summary", ""))[:1200]
        it["url"] = (it.get("url") or "").strip()
        if not it["title"] or not it["url"]:
            continue
        it["id"] = item_id(it)
        out.append(it)
    return out
