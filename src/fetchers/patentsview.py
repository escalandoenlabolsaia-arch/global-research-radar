"""Fetcher PatentsView (USPTO) — concesiones de patentes de EE.UU.
API nuevo (PatentSearch): POST https://search.patentsview.org/api/v1/patent/
con header X-Api-Key. La key es GRATIS (Service Desk de PatentsView,
manual §13) y se activa creando el secret PATENTSVIEW_API_KEY en el repo
— patrón idéntico a NTFY_TOKEN/GROQ_API_KEY: sin secret, el fetcher hace
skip silencioso y la corrida sigue (R6).

Fase 3 (patentes) del manual v3.8. Estado: código por documentación
verificada (ropensci + snippets públicos) — SIN validar en vivo hasta
tener key. Cuando la actives, mirar el log de esa corrida antes de
confiar (R11: los esquemas cambian sin aviso).

Calibración (sondeos 1-10):
  - El API VIEJO (api.patentsview.org/patents/query) está MUERTO: hoy
    sirve la UI HTML del Open Data Portal detrás de un AWS WAF. No usar.
  - El API nuevo exige key en TODAS las requests (X-Api-Key).
  - patent_number pasó a llamarse patent_id en el API nuevo.
  - El USPTO concede patentes los MARTES (~4-5k/semana): days_back 7
    garantiza cazar cada ola semanal; la dedup cobra cada una UNA vez.
"""
import logging
import os
import re
from datetime import date, timedelta

from src.fetchers.common import post

log = logging.getLogger(__name__)

API = "https://search.patentsview.org/api/v1/patent/"

CAMPOS = [
    "patent_id", "patent_title", "patent_abstract", "patent_date",
    "patent_type", "inventors", "assignees",
]

_NOALNUM = re.compile(r"[^A-Z0-9]")


def _limpiar_num(pid: str) -> str:
    return _NOALNUM.sub("", (pid or "").upper())


def _nombres(lista, claves) -> list:
    """Extrae nombres de arrays anidados (inventors/assignees) sin asumir
    el esquema exacto: junta los valores string de las claves que aparezcan."""
    out = []
    for it in (lista or [])[:8]:
        if not isinstance(it, dict):
            continue
        partes = []
        for k, v in it.items():
            if isinstance(v, str) and any(c in k for c in claves) and v.strip():
                partes.append(v.strip())
        if partes:
            out.append(" ".join(partes))
    return out


def _to_item(p: dict):
    pid = _limpiar_num(str(p.get("patent_id") or ""))
    title = " ".join((p.get("patent_title") or "").split())
    if not pid or not title:
        return None
    num = pid if pid.startswith("US") else f"US{pid}"
    fecha = (p.get("patent_date") or "")[:10]
    titulares = _nombres(p.get("assignees"),
                         ("organization", "assignee", "name"))
    inventores = _nombres(p.get("inventors"),
                          ("name", "inventor"))
    partes = [f"Patente concedida por USPTO ({fecha})."]
    if titulares:
        partes.append("Titular: " + ", ".join(titulares[:4]) + ".")
    if inventores:
        partes.append("Inventores: " + ", ".join(inventores[:5]) + ".")
    resumen_txt = " ".join((p.get("patent_abstract") or "").split())
    if resumen_txt:
        partes.append(resumen_txt[:700])
    return {
        "id": f"patent:{num}",  # id de dominio: estable aunque cambie el título
        "source": "patentsview",
        "doi": None,
        "title": title[:300],
        "url": f"https://patents.google.com/patent/{num}/en",
        "summary": " ".join(partes)[:1200],
        "published": fecha,
        "lang": "en",
        "authors": titulares[:3] or inventores[:3],
        "categories": [x for x in [p.get("patent_type") or ""] if x],
    }


def fetch(cfg: dict) -> list:
    pv = cfg.get("patentsview", {}) or {}
    if pv.get("enabled", True) is False:
        return []
    key = os.environ.get("PATENTSVIEW_API_KEY", "").strip()
    if not key:
        log.info("patentsview: sin PATENTSVIEW_API_KEY — skip (la fuente se "
                 "activa sola al crear el secret; key gratis, manual §13)")
        return []

    days_back = int(pv.get("days_back", 7))
    max_results = int(pv.get("max_results", 100))
    desde = (date.today() - timedelta(days=days_back)).isoformat()

    body = {
        "q": {"_gte": {"patent_date": desde}},
        "f": CAMPOS,
        "o": {
            "size": min(max_results, 100),
            "pagination": {"page": 1},
            "sort": [{"patent_date": "desc"}],
        },
    }
    data = post(API, json=body, timeout=90,
                headers={"X-Api-Key": key}).json()

    items = []
    for p in data.get("patents", []):
        try:
            it = _to_item(p)
            if it:
                items.append(it)
        except Exception as e:
            log.warning("patentsview: patente descartada (%s)", e)
    log.info("patentsview: %d ítems (desde %s, total_index=%s)",
             len(items), desde, data.get("total_patent_count"))
    return items
