"""Dedup — memoria permanente en state/seen.json (regla del manual §6).
Doble filtro: id exacto (DOI o SHA del título) + fuzzy >92 con rapidfuzz.
También deduplica DENTRO de la misma corrida (dos fuentes, misma noticia).
"""
import json
import logging
from datetime import date
from pathlib import Path

from rapidfuzz import fuzz

from src.pipeline.normalize import normalize_title

log = logging.getLogger(__name__)

FUZZ_THRESHOLD = 92
MAX_SEEN = 100_000  # recorte para que seen.json no crezca infinito


def load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        log.warning("seen.json ilegible — arranco con memoria vacía")
        return {}


def _today() -> str:
    return date.today().isoformat()


def _is_fuzzy_dup(nt: str, seen_titles: list) -> bool:
    if not nt:
        return False
    for prev in seen_titles:
        if prev and fuzz.ratio(nt, prev, score_cutoff=FUZZ_THRESHOLD):
            return True
    return False


def split_new(items: list, seen: dict):
    """Devuelve (nuevos, vistos). Actualiza `seen` en memoria (persiste el runner)."""
    seen_titles = [v.get("nt", "") for v in seen.values()]
    nuevos, vistos = [], 0
    for it in items:
        iid = it["id"]
        nt = normalize_title(it["title"])
        if iid in seen or _is_fuzzy_dup(nt, seen_titles):
            vistos += 1
            continue
        nuevos.append(it)
        seen[iid] = {"nt": nt, "ts": _today()}
        if nt:
            seen_titles.append(nt)
    log.info("dedup: %d nuevos / %d ya vistos (memoria: %d)", len(nuevos), vistos, len(seen))
    return nuevos, vistos


def prune(seen: dict) -> dict:
    if len(seen) <= MAX_SEEN:
        return seen
    recientes = sorted(seen.items(), key=lambda kv: kv[1].get("ts", ""), reverse=True)
    log.info("prune: %d → %d registros en seen.json", len(seen), MAX_SEEN)
    return dict(recientes[:MAX_SEEN])


def save(seen: dict, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
