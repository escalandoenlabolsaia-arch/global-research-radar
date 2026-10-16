"""Fetcher openFDA — eventos regulatorios reales de la FDA, sin API key.
3 entradas configurables en sources.yaml, cada una con su `source` propio
(caps round-robin separados):
  farmacos        -> drug/drugsfda  (aprobaciones ORIG con estado AP)
  dispositivos_510k -> device/510k  (autorizaciones 510(k))
  dispositivos_pma  -> device/pma   (aprobaciones PMA y suplementos)

Fase 2 (biosalud) del manual v3.6. Calibrado en vivo (sondeos 1-8):
  - Rangos de fecha con ESPACIOS: [AAAA-MM-DD TO AAAA-MM-DD] (el '+' en el
    valor rompe el parser de openFDA; requests codifica espacios y listo).
  - drugsfda: el campo de fecha es submissions.submission_status_date en
    formato YYYYMMDD y los estados son códigos (AP = Approved, TA = Tentative
    Approval) — no la palabra "Approved". El esquema cambió el 14/10/2026
    sin aviso (lección R11): el fetcher usa solo campos verificados en vivo.
  - 0 resultados = HTTP 404 "No matches found!" -> día vacío, no error:
    devuelve [] y la corrida sigue.
  - 510k/PMA: los datasets se cargan ~1 vez por mes (meta.last_updated).
    days_back 35 garantiza cazar cada carga; la dedup hace que cada
    decisión entre UNA sola vez al radar.
  - drugsfda: solo submission_type ORIG — los suplementos (SUPPL) son
    ruido administrativo; ORIG incluye NDA/BLA (nuevos fármacos) y ANDA
    (genéricos, el agente los puntúa bajo el umbral).
"""
import logging
from datetime import date, timedelta

from src.fetchers.common import get

log = logging.getLogger(__name__)

API = "https://api.fda.gov/"


def _query(path: str, q: str, limit: int) -> list:
    """GET con manejo de 404-vacío: día sin eventos = [], no excepción."""
    try:
        r = get(f"{API}{path}.json", params={"search": q, "limit": limit},
                timeout=90)
        return r.json().get("results", [])
    except Exception as e:
        s = str(e)
        if "404" in s or "No matches" in s:
            log.info("openfda:%s — 0 eventos en la ventana", path)
            return []
        raise


def _first(v):
    if isinstance(v, list):
        return (v[0] or "") if v else ""
    return v or ""


def _iso(yyyymmdd: str) -> str:
    f = (yyyymmdd or "").strip()
    if len(f) == 8 and f.isdigit():
        return f"{f[:4]}-{f[4:6]}-{f[6:8]}"
    return _first(f)[:10]


def _solo_digitos(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


# ---------------------------------------------------------------- fármacos
def _farmacos(o: dict) -> list:
    c = o.get("farmacos", {}) or {}
    if c.get("enabled", True) is False:
        return []
    days_back = int(c.get("days_back", 3))
    limit = int(c.get("limit", 100))
    desde = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    hasta = date.today().strftime("%Y%m%d")
    q = ("submissions.submission_status_date:[" + desde + " TO " + hasta + "] "
         "AND submissions.submission_status:AP "
         "AND submissions.submission_type:ORIG")
    recs = _query("drug/drugsfda", q, limit)

    items = []
    for rec in recs:
        try:
            app = (rec.get("application_number") or "").strip()
            if not app:
                continue
            sponsor = (rec.get("sponsor_name") or "").strip()
            prods = rec.get("products") or []
            prod = prods[0] if prods else {}
            brand = (prod.get("brand_name") or "").strip()
            ings = prod.get("active_ingredients") or []
            ing = ""
            if ings and isinstance(ings[0], dict):
                ing = (ings[0].get("name") or "").strip()
            marcas = ", ".join(sorted({(p.get("brand_name") or "").strip()
                                       for p in prods
                                       if p.get("brand_name")}))[:90]
            tipo = ("BLA" if app.startswith("BLA")
                    else "ANDA" if app.startswith("ANDA")
                    else "NDA" if app.startswith("NDA") else "ORIG")
            for sub in rec.get("submissions", []):
                if (sub.get("submission_status") != "AP"
                        or sub.get("submission_type") != "ORIG"):
                    continue
                f_iso = _iso(sub.get("submission_status_date"))
                if not desde <= f_iso.replace("-", "") <= hasta:
                    continue  # por si el índice trae submissions viejas
                nombre = brand or ing or app
                title = f"FDA aprueba {nombre}"
                if ing and brand and ing.lower() != brand.lower():
                    title += f" ({ing})"
                title += f" — {sponsor} [{tipo}]"
                items.append({
                    "id": (f"fda:drug:{app}:ORIG-"
                           f"{sub.get('submission_number', '')}"),
                    "source": "openfda-farmacos",
                    "doi": None,
                    "title": " ".join(title.split())[:300],
                    "url": ("https://www.accessdata.fda.gov/scripts/cder/daf/"
                            f"index.cfm?event=overview.process&ApplNo="
                            f"{_solo_digitos(app)}"),
                    "summary": (f"Aprobación FDA (ORIG {f_iso}) de {nombre} "
                                f"por {sponsor}. Vía: "
                                f"{(prod.get('route') or '').lower()}, "
                                f"{(prod.get('dosage_form') or '').lower()}. "
                                f"{('Marcas: ' + marcas) if marcas else ''}"
                                ).strip()[:1200],
                    "published": f_iso,
                    "lang": "en",
                    "authors": [sponsor] if sponsor else [],
                    "categories": [tipo, (prod.get("marketing_status") or "")],
                })
        except Exception as e:
            log.warning("openfda:farmacos — registro descartado (%s)", e)
    log.info("openfda-farmacos: %d ítems (ORIG/AP, %s→%s)",
             len(items), desde, hasta)
    return items


# -------------------------------------------------------------- dispositivos
def _510k(o: dict) -> list:
    c = o.get("dispositivos_510k", {}) or {}
    days_back = int(c.get("days_back", 35))
    limit = int(c.get("limit", 100))
    desde = (date.today() - timedelta(days=days_back)).isoformat()
    hasta = date.today().isoformat()
    recs = _query("device/510k",
                  f"decision_date:[{desde} TO {hasta}]", limit)

    items = []
    for rec in recs:
        try:
            k = (rec.get("k_number") or "").strip()
            if not k:
                continue
            device = ((rec.get("device_name") or "").strip()
                      or _first((rec.get("openfda") or {})
                                .get("device_name")).strip()
                      or f"producto {rec.get('product_code', '?')}")
            applicant = (rec.get("applicant") or "").strip()
            fecha = _first(rec.get("decision_date"))[:10]
            code = (rec.get("decision_code") or "").strip()
            code_txt = {"SESE": "sustancialmente equivalente",
                        "SESK": "sustancialmente equivalente"}.get(code, code)
            esp = (rec.get("advisory_committee_description") or "").strip()
            supp = (rec.get("supplement_number") or "").strip()
            titulo = f"FDA 510(k) {code}: {device} — {applicant}"
            items.append({
                "id": f"fda:510k:{k}:{supp or '0'}:{fecha}",
                "source": "openfda-510k",
                "doi": None,
                "title": " ".join(titulo.split())[:300],
                "url": ("https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/"
                        f"cfpmn/pmn.cfm?ID={k}"),
                "summary": (f"Autorización 510(k){' ' + supp if supp else ''} "
                            f"({fecha}) para {device} de {applicant}. "
                            f"{('Especialidad: ' + esp + '. ') if esp else ''}"
                            f"{('Resultado: ' + code_txt + '. ') if code_txt else ''}"
                            ).strip()[:1200],
                "published": fecha,
                "lang": "en",
                "authors": [applicant] if applicant else [],
                "categories": [x for x in [rec.get("product_code", ""), esp]
                               if x],
            })
        except Exception as e:
            log.warning("openfda:510k — registro descartado (%s)", e)
    log.info("openfda-510k: %d ítems (%s → %s)", len(items), desde, hasta)
    return items


def _pma(o: dict) -> list:
    c = o.get("dispositivos_pma", {}) or {}
    days_back = int(c.get("days_back", 35))
    limit = int(c.get("limit", 100))
    desde = (date.today() - timedelta(days=days_back)).isoformat()
    hasta = date.today().isoformat()
    recs = _query("device/pma",
                  f"decision_date:[{desde} TO {hasta}]", limit)

    items = []
    for rec in recs:
        try:
            pma = (rec.get("pma_number") or "").strip()
            if not pma:
                continue
            supp = (rec.get("supplement_number") or "").strip()
            applicant = (rec.get("applicant") or "").strip()
            nombre = ((rec.get("trade_name") or "").strip()
                      or (rec.get("device_name") or "").strip()
                      or f"dispositivo {rec.get('product_code', '?')}")
            fecha = _first(rec.get("decision_date"))[:10]
            esp = (rec.get("advisory_committee_description") or "").strip()
            kind = f"PMA {supp}" if supp else "PMA original"
            titulo = f"FDA {kind}: {nombre} — {applicant}"
            items.append({
                "id": f"fda:pma:{pma}:{supp or 'orig'}:{fecha}",
                "source": "openfda-pma",
                "doi": None,
                "title": " ".join(titulo.split())[:300],
                "url": ("https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/"
                        f"cfpma/pma.cfm?id={pma}{supp}"),
                "summary": (f"Aprobación FDA {kind} ({fecha}) para {nombre} "
                            f"de {applicant}. "
                            f"{('Especialidad: ' + esp + '. ') if esp else ''}"
                            f"{('Estado: ' + str(rec.get('decision_code')) + '. ') if rec.get('decision_code') else ''}"
                            ).strip()[:1200],
                "published": fecha,
                "lang": "en",
                "authors": [applicant] if applicant else [],
                "categories": [x for x in [rec.get("product_code", ""), esp]
                               if x],
            })
        except Exception as e:
            log.warning("openfda:pma — registro descartado (%s)", e)
    log.info("openfda-pma: %d ítems (%s → %s)", len(items), desde, hasta)
    return items


# ------------------------------------------------------------------- fetch
def fetch(cfg: dict) -> list:
    o = cfg.get("openfda", {}) or {}
    items = []
    for entrada, fn in [("farmacos", _farmacos),
                        ("dispositivos_510k", _510k),
                        ("dispositivos_pma", _pma)]:
        try:
            items += fn(o)
        except Exception as e:
            # R6: una entrada caída NUNCA frena las otras ni la corrida
            log.warning("openfda:%s falló (%s) — sigo con las demás", entrada, e)
    log.info("openfda: %d ítems en total", len(items))
    return items
