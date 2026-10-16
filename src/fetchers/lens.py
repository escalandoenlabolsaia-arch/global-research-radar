"""Fetcher Lens.org — patentes de 100+ jurisdicciones (la fuente más
global de la fase 3). API: POST https://api.lens.org/patent/search con
header `Authorization: Bearer <token>`. El token es GRATIS para uso no
comercial (se pide desde tu perfil de Lens, manual §13) y se activa
creando el secret LENS_API_TOKEN en el repo — patrón NTFY_TOKEN: sin
secret, skip silencioso y la corrida sigue (R6).

Fase 3 (patentes) del manual v3.8. Estado: código por documentación
verificada (docs.api.lens.org) — SIN validar en vivo hasta tener token.
Cuando lo actives, mirar el log de esa corrida (R11).

Calibración (sondeos 1-10):
  - Sin token la respuesta es 401 limpio ("Missing/Incorrect Authorization
    Header") — por eso el skip por env y no un intento a ciegas.
  - Documentación oficial: 404 = "Empty Result for supplied queries" —
    día vacío, NO error (mismo trato que openFDA).
  - Rate limiting por headers x-rate-limit-*; 429 = esperar (common.py
    ya reintenta con backoff; 1 request por corrida es el ritmo seguro).
  - date_published es yyyy-MM-dd; lens_id es el identificador global
    estable (ideal como id de dominio).
"""
import logging
import os
from datetime import date, timedelta

from src.fetchers.common import post

log = logging.getLogger(__name__)

API = "https://api.lens.org/patent/search"

INCLUDE = ("/lens_id,/title,/abstract,/date_published,"
           "/jurisdiction,/doc_number,/applicant")


def _applicant_names(rec: dict) -> list:
    out = []
    for a in (rec.get("applicant") or [])[:6]:
        if isinstance(a, dict):
            n = (a.get("name") or "").strip()
            if n:
                out.append(n)
    return out


def _to_item(rec: dict):
    lens_id = (rec.get("lens_id") or "").strip()
    title = " ".join((rec.get("title") or "").split())
    if not lens_id or not title:
        return None
    fecha = (rec.get("date_published") or "")[:10]
    jur = (rec.get("jurisdiction") or "").strip()
    doc = (rec.get("doc_number") or "").strip()
    solicitantes = _applicant_names(rec)
    partes = []
    if jur or doc:
        partes.append(f"Patente publicada en {jur or '?'}"
                      f"{f' ({doc})' if doc else ''}{f' el {fecha}' if fecha else ''}.")
    if solicitantes:
        partes.append("Solicitante: " + ", ".join(solicitantes[:4]) + ".")
    abstract = " ".join((rec.get("abstract") or "").split())
    if abstract:
        partes.append(abstract[:700])
    return {
        "id": f"patent:lens:{lens_id}",  # id de dominio global estable
        "source": "lens",
        "doi": None,
        "title": title[:300],
        "url": f"https://www.lens.org/lens/patent/{lens_id}",
        "summary": " ".join(partes)[:1200],
        "published": fecha,
        "lang": "en",
        "authors": solicitantes[:3],
        "categories": [x for x in [jur] if x],
    }


def fetch(cfg: dict) -> list:
    ln = cfg.get("lens", {}) or {}
    if ln.get("enabled", True) is False:
        return []
    token = os.environ.get("LENS_API_TOKEN", "").strip()
    if not token:
        log.info("lens: sin LENS_API_TOKEN — skip (la fuente se activa sola "
                 "al crear el secret; token gratis, manual §13)")
        return []

    days_back = int(ln.get("days_back", 7))
    max_results = int(ln.get("max_results", 100))
    desde = (date.today() - timedelta(days=days_back)).isoformat()
    hasta = date.today().isoformat()

    body = {
        "query": {"bool": {"must": [
            {"range": {"date_published": {"gte": desde, "lte": hasta}}},
        ]}},
        "sort": [{"date_published": "desc"}],
        "include": INCLUDE,
        "size": min(max_results, 100),
        "from": 0,
    }
    try:
        data = post(API, json=body, timeout=90,
                    headers={"Authorization": f"Bearer {token}"}).json()
    except Exception as e:
        s = str(e)
        if "404" in s:
            # doc oficial: 404 = resultado vacío de la query → día sin nada
            log.info("lens — 0 patentes en la ventana (%s → %s)", desde, hasta)
            return []
        raise

    items = []
    for rec in (data.get("data") or []):
        try:
            it = _to_item(rec)
            if it:
                items.append(it)
        except Exception as e:
            log.warning("lens: registro descartado (%s)", e)
    log.info("lens: %d ítems (%s → %s, total=%s)",
             len(items), desde, hasta, data.get("total"))
    return items
