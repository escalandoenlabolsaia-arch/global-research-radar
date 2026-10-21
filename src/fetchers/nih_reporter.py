"""Fetcher NIH RePORTER (Fase 4 — financiamiento/predicción).

API: POST https://api.reporter.nih.gov/v2/projects/search
Keyless (sin secret, patrón OpenAlex). 1 request por corrida.

Trampas confirmadas en sondeos (2026-10-21):
  · Pedido en PascalCase, respuesta en snake_case (R11).
  · sort_field=project_start_date respeta el orden (desc = más nuevo primero).
  · fiscal_year 2027 = proyectos que arrancan desde 2026-10-01 (señal de
    anticipación: financiamiento aprobado que aún no arrancó).
  · award_amount puede venir null: tolerarlo.
"""
from __future__ import annotations

import datetime as dt

from .common import get_logger, post_json

log = get_logger("nih_reporter")

ENDPOINT = "https://api.reporter.nih.gov/v2/projects/search"

# Glosado del primer bloque del project_num (tipo de mecanismo).
# El primer dígito es el más informativo: 1 = nuevo, 5 = renovación.
_TIPO_PREFIJO = {
    "1": "nuevo",
    "2": "nuevo (suplemento)",
    "3": "renovación",
    "4": "extensión",
    "5": "renovación",
    "7": "continuación",
    "9": "otro",
}


def _glosar_tipo(project_num: str) -> str:
    """Traduce el prefijo del project_num a un tipo legible."""
    if not project_num:
        return "tipo desconocido"
    primero = project_num[0]
    return _TIPO_PREFIJO.get(primero, f"mecanismo {primero}")


def _formatear_fecha(iso: str | None) -> str:
    """YYYY-MM-DDTHH:MM:SS -> YYYY-MM-DD (o 'sin fecha')."""
    if not iso:
        return "sin fecha"
    try:
        return dt.date.fromisoformat(iso[:10]).isoformat()
    except ValueError:
        return iso[:10]


def _es_futuro(iso: str | None, hoy: dt.date) -> bool:
    """True si la fecha de inicio es posterior a hoy (proyecto que aún no arrancó)."""
    if not iso:
        return False
    try:
        return dt.date.fromisoformat(iso[:10]) > hoy
    except ValueError:
        return False


def fetch(cfg: dict, state: dict | None = None) -> list[dict]:
    """Devuelve la lista de ítems normalizados de NIH RePORTER.

    `state` se acepta por compatibilidad con el dispatch de run.py (los
    fetchers de fase 2/3 lo reciben), pero NIH no lo usa: cada corrida
    es independiente y la dedup se encarga de no repetir.
    """
    if not cfg.get("enabled", True):
        log.info("nih_reporter: deshabilitado en sources.yaml — skip")
        return []

    hoy = dt.date.today()
    anio_actual = hoy.year
    # El año fiscal N empieza el 1 de octubre de N-1. Pedimos el actual
    # y el siguiente para capturar los proyectos ya aprobados que aún
    # no arrancaron (señal de anticipación).
    fiscal_years = cfg.get("fiscal_years") or [anio_actual, anio_actual + 1]

    payload = {
        "criteria": {"fiscal_years": fiscal_years},
        "include_fields": [
            "ProjectNum",
            "ProjectTitle",
            "FiscalYear",
            "AwardAmount",
            "ProjectStartDate",
            "Organization",
        ],
        "sort_field": "project_start_date",
        "sort_order": "desc",
        "limit": int(cfg.get("max_results", 100)),
        "offset": 0,
    }

    log.info(
        "nih_reporter: POST fiscal_years=%s limit=%s",
        fiscal_years,
        payload["limit"],
    )
    data = post_json(ENDPOINT, payload, log)
    if not data:
        log.warning("nih_reporter: respuesta vacía o error — 0 ítems")
        return []

    resultados = data.get("results") or []
    total = (data.get("meta") or {}).get("total", 0)
    log.info("nih_reporter: %s resultados (total=%s)", len(resultados), total)

    items: list[dict] = []
    descartados_sin_titulo = 0
    futuros = 0
    for r in resultados:
        project_num = r.get("project_num")
        titulo = r.get("project_title")
        if not project_num or not titulo:
            descartados_sin_titulo += 1
            continue

        org = r.get("organization") or {}
        org_name = org.get("org_name") or "organización no informada"
        org_country = org.get("org_country") or "país no informado"

        fecha_iso = r.get("project_start_date")
        fecha = _formatear_fecha(fecha_iso)
        es_futuro = _es_futuro(fecha_iso, hoy)
        if es_futuro:
            futuros += 1

        award = r.get("award_amount")
        if award is None:
            monto = "monto no informado"
        else:
            monto = f"USD {award:,}"

        tipo = _glosar_tipo(project_num)
        estado_fecha = "FUTURO" if es_futuro else "en curso"
        resumen = (
            f"NIH {tipo} | {org_name} ({org_country}) | "
            f"inicio {fecha} ({estado_fecha}) | {monto} | {titulo}"
        )

        items.append(
            {
                "id": f"grant:nih:{project_num}",
                "title": titulo,
                "url": f"https://reporter.nih.gov/project-details/{project_num}",
                "summary": resumen,
                "published": fecha_iso or "",
                "source": "nih_reporter",
                "rubro": "financiamiento",
                "region": "Norteamerica",
            }
        )

    if descartados_sin_titulo:
        log.info(
            "nih_reporter: %s refs sin título/número descartadas",
            descartados_sin_titulo,
        )
    log.info(
        "nih_reporter: %s ítems (%s con inicio FUTURO)", len(items), futuros
    )
    return items
