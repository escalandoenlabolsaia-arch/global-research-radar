"""Fetcher ClinicalTrials.gov API v2 — ensayos clínicos fase 2-3 recién
actualizados (~530k estudios, sponsors de todo el mundo). Sin API key,
1 request por corrida (~150 KB con `fields`).

Fase 2 (biosalud) del manual v3.6. Calibrado en vivo (sondeos 1-8):
  - filter.advanced con AREAs; el rango de fechas usa comas:
    AREA[LastUpdatePostDate]RANGE[desde,hasta]
  - los paths de `fields` van en lowercase camelCase igual que el JSON
    (con paths de módulo completos salía HTTP 400)
  - sort=LastUpdatePostDate:desc trae primero lo más fresco
"""
import logging
from datetime import date, timedelta

from src.fetchers.common import get

log = logging.getLogger(__name__)

API = "https://clinicaltrials.gov/api/v2/studies"

FIELDS = "|".join([
    "protocolSection.identificationModule.nctId",
    "protocolSection.identificationModule.briefTitle",
    "protocolSection.identificationModule.acronym",
    "protocolSection.statusModule.overallStatus",
    "protocolSection.statusModule.lastUpdatePostDateStruct",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    "protocolSection.conditionsModule.conditions",
    "protocolSection.designModule.phases",
    "protocolSection.designModule.enrollmentInfo.count",
    "protocolSection.armsInterventionsModule.interventions.name",
    "protocolSection.armsInterventionsModule.interventions.type",
    "protocolSection.contactsLocationsModule.locations.country",
])


def _resumen(ps: dict) -> str:
    """Lo que define si un ensayo importa, en ~una línea: estado,
    condición, intervención, sponsor, tamaño y países."""
    partes = []
    status = (ps.get("statusModule") or {}).get("overallStatus") or ""
    if status:
        partes.append(f"Estado: {status}")
    conds = (ps.get("conditionsModule") or {}).get("conditions") or []
    if conds:
        partes.append("Condición: " + ", ".join(str(c) for c in conds[:3]))
    interv = (ps.get("armsInterventionsModule") or {}).get("interventions") or []
    nombres = [ (iv.get("name") or "").strip() for iv in interv[:4] ]
    nombres = [n for n in nombres if n]
    if nombres:
        partes.append("Intervención: " + ", ".join(nombres))
    sponsor = ((ps.get("sponsorCollaboratorsModule") or {})
               .get("leadSponsor") or {}).get("name") or ""
    if sponsor:
        partes.append(f"Sponsor: {sponsor}")
    n = ((ps.get("designModule") or {}).get("enrollmentInfo") or {}).get("count")
    if n:
        partes.append(f"N={n}")
    paises = []
    for loc in ((ps.get("contactsLocationsModule") or {}).get("locations") or []):
        c = (loc.get("country") or "").strip()
        if c and c not in paises:
            paises.append(c)
        if len(paises) >= 6:
            break
    if paises:
        partes.append("Países: " + ", ".join(paises))
    return " · ".join(partes)[:1200]


def _to_item(st: dict):
    ps = st.get("protocolSection") or {}
    ident = ps.get("identificationModule") or {}
    nct = (ident.get("nctId") or "").strip()
    title = " ".join((ident.get("briefTitle") or "").split())
    if not nct or not title:
        return None
    fecha = ((ps.get("statusModule") or {}).get("lastUpdatePostDateStruct")
             or {}).get("date") or ""
    fases = (ps.get("designModule") or {}).get("phases") or []
    return {
        "id": f"nct:{nct}",  # id de dominio: estable aunque el título cambie
        "source": "clinicaltrials",
        "doi": None,
        "title": title,
        "url": f"https://clinicaltrials.gov/study/{nct}",
        "summary": _resumen(ps),
        "published": (fecha or "")[:10],
        "lang": "en",
        "authors": [],
        "categories": fases[:3],
    }


def fetch(cfg: dict) -> list:
    ct = cfg.get("clinicaltrials", {}) or {}
    days_back = int(ct.get("days_back", 2))
    fases = ct.get("phases") or ["PHASE2", "PHASE3"]
    max_results = int(ct.get("max_results", 100))
    if not fases:
        return []

    desde = (date.today() - timedelta(days=days_back)).isoformat()
    hasta = date.today().isoformat()
    fase_q = " OR ".join(f"AREA[Phase]{f}" for f in fases)
    adv = (f"AREA[LastUpdatePostDate]RANGE[{desde},{hasta}] AND ({fase_q})")

    params = {
        "filter.advanced": adv,
        "sort": "LastUpdatePostDate:desc",
        "pageSize": min(max_results, 200),
        "fields": FIELDS,
    }
    data = get(API, params=params, timeout=90).json()

    items = []
    for st in data.get("studies", []):
        try:
            it = _to_item(st)
            if it:
                items.append(it)
        except Exception as e:
            log.warning("clinicaltrials: estudio descartado (%s)", e)
    log.info("clinicaltrials: %d ítems (fases %s, desde %s)",
             len(items), "/".join(fases), desde)
    return items
