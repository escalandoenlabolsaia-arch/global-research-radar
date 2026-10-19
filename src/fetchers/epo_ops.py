"""Fetcher EPO OPS (Open Patent Services) — publicaciones EP + WO.
La fuente global de patentes que reemplaza a Lens (v3.9, manual §10).
v3.9.1 — FIX AUTH (corrida 15, primer contacto real, R11): el POST de
token exige body form grant_type=client_credentials; con data="" la
EPO responde 400 "Required param : grant_type". Los sondeos sin
credenciales reales no lo vieron: el 401 del Basic se valida ANTES
que el body y enmascaraba el error.
v3.9.2 — FIX VENTANA VACÍA (corrida 16, primera con la auth de
v3.9.1 pasando, R11): el token entró limpio y el índice contestó
404 + fault SERVER.EntityNotFound "No results found". NO es un error:
es la forma de OPS de decir "búsqueda sin resultados" (sintaxis pd
within "aaaammdd aaaaammdd" verificada contra docs oficiales — el
índice simplemente no tenía nada en la ventana). La ventana de 2
días había caído en sábado→lunes: EP y WO publican en días fijos de
la semana (EP ~miércoles, WO ~jueves), así que varias corridas por
semana no tienen publicaciones nuevas que mostrar. Tres fixes:
(1) ese 404 se traduce a 0 resultados y la fuente termina feliz
(como openFDA en día sin carga); (2) days_back 2→7: toda corrida
pesca el boletín semanal aunque una fuente publique 1 día/semana;
(3) techo de muestreo en el registro 2000: límite duro del parámetro
Range en la EPO, y con 7 días el total lo supera siempre.
Registro ABIERTO con mail común en developers.epo.org, gratis hasta
4 GB/semana (carta de fair-use de la EPO) y los mismos datos que
Espacenet. El índice de BÚSQUEDA de OPS cubre EP (solicitudes y
concesiones europeas) + WO (PCT = el pipeline internacional de
invención); las concesiones US se cubren con Google News RSS hoy y
con PatentsView/ODP el día que USPTO las rearme.

Activación (mismo patrón que NTFY_TOKEN/GROQ_API_KEY, R15):
  cuenta en developers.epo.org → My Apps → definir app → Consumer
  Key + Consumer Secret → secrets OPS_CONSUMER_KEY y
  OPS_CONSUMER_SECRET en GitHub → la corrida siguiente la activa
  sola. Sin secrets = skip silencioso y la corrida sigue (R6).

Fase 3 (patentes) del manual v3.9. Estado: código por documentación
verificada + sondeos de endpoints en vivo (búsqueda responde 403
pidiendo credenciales, auth responde 401 pidiendo client id, portal
de registro 200) — SIN validar en vivo con credenciales reales hasta
que la cuenta se habilite. Esa primera corrida se lee con lupa (R11).

Calibración (sondeos 11-13, manual §10):
  - POST {AUTH} con Authorization: Basic base64(key:secret) y body
    form grant_type=client_credentials devuelve JSON {access_token,
    expires_in ~1200s} — es la forma literal de la doc oficial de la
    EPO (curl --data "grant_type=client_credentials"). Token fresco
    por corrida: 1 request mínimo, cero estados que pudrirse.
  - GET {SEARCH}?q=...&Range=a-b con Bearer → XML ops:world-patent-data.
  - El índice NO documenta orden por fecha ni parámetro de sort: sin
    muestreo, la página 1 devolvería siempre la misma cabeza del
    índice (la dedup los absorbería y el flujo NUNCA avanzaría).
    Solución: 2 requests — sondeo de total (Range 1-1) + página
    ALEATORIA de hasta max_results registros. Cada corrida toma una
    tajada distinta de la ventana; la dedup cobra cada publicación
    UNA vez en la vida. Mismo espíritu R12: muestreo honesto, no
    rastreo exhaustivo que el cupo caps (25) no usaría.
  - Parseo XML con comodines {*} por tag: si la EPO renombra un
    namespace, el parser no se rompe (R11).
  - La búsqueda trae bibliografía (título, solicitantes, fecha) pero
    NO el abstract (se pediría 1 request extra por documento):
    el resumen lleva jurisdicción, número, tipo de documento y
    solicitantes — suficiente para que el agente separe estrategia
    de trámite. Enriquecer con abstracts = posible v2 si el log
    en vivo muestra que hace falta.
"""
import base64
import logging
import os
import random
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from urllib.parse import quote

from src.fetchers.common import get, post

log = logging.getLogger(__name__)

AUTH = "https://ops.epo.org/3.2/auth/accesstoken"
SEARCH = "https://ops.epo.org/3.2/rest-services/published-data/search"

# Código de kind (DOCDB) → qué es, para el resumen del agente
KIND = {
    "A0": "publicación de solicitud", "A1": "publicación de solicitud con informe de búsqueda",
    "A2": "publicación de solicitud", "A3": "informe de búsqueda aislado",
    "A4": "búsqueda suplementaria", "A8": "solicitud corregida", "A9": "solicitud republicada",
    "B0": "patente concedida", "B1": "patente concedida",
    "B2": "patente concedida modificada", "B3": "patente concedida (nueva)",
    "B8": "concesión corregida", "B9": "concesión republicada",
    "T1": "traducción publicada", "T2": "traducción publicada", "T3": "traducción publicada",
    "U1": "modelo de utilidad", "U": "modelo de utilidad",
}


class VentanaVacia(Exception):
    """404 + SERVER.EntityNotFound = la búsqueda no matcheó ninguna
    publicación. Es la respuesta ESTÁNDAR de OPS para un resultado
    vacío (visto en vivo en la corrida 16 tras auth correcta; docs
    oficiales confirman que la sintaxis era válida). No debe
    reintentarse ni marcar la fuente como caída (R6)."""


def _get_busqueda(params: dict, headers: dict, intentos: int = 2):
    """GET al índice distinguiendo 'ventana vacía' de error real.
    Usa common.get con retries=1: el reintento genérico quemaría 3
    intentos + 7s en un 404 de ventana vacía, que es PERMANENTE, no
    transitorio. Los reintentos propios son solo para fallos que SÍ
    pueden ser transitorios (red, 5xx, 429)."""
    for intento in range(1, intentos + 1):
        try:
            return get(SEARCH, params=params, timeout=60, retries=1,
                       headers=headers)
        except Exception as e:  # noqa: BLE001 — se inspecciona el mensaje
            msg = str(e)
            if "404" in msg and ("EntityNotFound" in msg
                                 or "No results found" in msg):
                raise VentanaVacia(
                    "0 publicaciones en la ventana (fault estándar de OPS)") from e
            if intento == intentos:
                raise
            time.sleep(2 ** (intento - 1))


def _pagina_aleatoria(total: int, max_results: int) -> tuple:
    """Página aleatoria dentro del techo DURO de la EPO: el parámetro
    Range no puede pasar del registro 2000 (con la ventana de 7 días
    el total lo supera siempre). Muestreo honesto dentro de lo que la
    API deja ver; la dedup cobra cada publicación UNA vez en la vida."""
    techo = min(max(total, 1), 2000)
    if techo <= max_results:
        return 1, techo
    inicio = random.randint(1, techo - max_results + 1)
    return inicio, min(inicio + max_results - 1, techo)


def _token(key: str, secret: str) -> str:
    basic = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("ascii")
    # OAuth exige el grant_type en el BODY form-encoded (no en la
    # query, no en JSON — RFC 6749). Corrida 15: data="" → 400
    # "Required param : grant_type" con credenciales reales. requests
    # form-encodea el dict y setea el Content-Type correcto solo.
    r = post(AUTH, data={"grant_type": "client_credentials"},
             timeout=30, headers={"Authorization": f"Basic {basic}"})
    tok = (r.json() or {}).get("access_token", "").strip()
    if not tok:
        raise RuntimeError("ops auth sin access_token en la respuesta")
    return tok


def _parsear_biblio(resp) -> tuple:
    """XML → (total_result_count, lista de dicts crudos). Comodines {*}
    para no casarnos con los namespaces exactos (R11)."""
    raiz = ET.fromstring(resp.content)
    biblio = raiz.find("{*}biblio-search")
    if biblio is None:
        raise RuntimeError("ops search: respuesta sin biblio-search (R11: "
                           "loguear cuerpo y revisar esquema)")
    total = int(biblio.get("total-result-count") or 0)
    docs = []
    for doc in biblio.findall(".//{*}exchange-document"):
        cc = (doc.get("country") or "").strip()
        num = (doc.get("doc-number") or "").strip()
        kind = (doc.get("kind") or "").strip()
        bd = doc.find("{*}bibliographic-data")
        fecha, titulo, titulos_alt = "", "", []
        solicitantes = []
        if bd is not None:
            did = bd.find("{*}publication-reference/{*}document-id")
            if did is not None:
                fecha = (did.findtext("{*}date") or "")[:10]
            for t in bd.findall("{*}invention-title"):
                txt = " ".join((t.text or "").split())
                if not txt:
                    continue
                if (t.get("lang") or "").lower() == "en":
                    titulo = txt
                    break
                titulos_alt.append(txt)
            for n in bd.findall(".//{*}applicant-name/{*}name"):
                v = " ".join((n.text or "").split())
                if v and v not in solicitantes:
                    solicitantes.append(v)
        docs.append({"cc": cc, "num": num, "kind": kind, "fecha": fecha,
                     "titulo": titulo or (titulos_alt[0] if titulos_alt else ""),
                     "solicitantes": solicitantes[:6]})
    return total, docs


def _to_item(d: dict):
    num_completo = f"{d['cc']}{d['num']}{d['kind']}"
    if not d["cc"] or not d["num"] or not d["titulo"]:
        return None  # normalize exige título y url; sin título no hay ítem
    que = KIND.get(d["kind"], "publicación oficial")
    partes = [f"Patente publicada en {d['cc']} ({num_completo}, documento "
              f"{que}) el {d['fecha'] or 'fecha no informada'}."]
    if d["solicitantes"]:
        partes.append("Solicitante: " + ", ".join(d["solicitantes"][:4]) + ".")
    partes.append("Texto completo en Espacenet.")
    return {
        "id": f"patent:ops:{num_completo}",  # id de dominio estable
        "source": "epo_ops",
        "doi": None,
        "title": d["titulo"][:300],
        "url": ("https://worldwide.espacenet.com/patent/search?q="
                + quote(f"pn={num_completo}")),
        "summary": " ".join(partes)[:1200],
        "published": d["fecha"],
        "lang": "en",
        "authors": d["solicitantes"][:3],
        "categories": [x for x in [d["cc"]] if x],
    }


def fetch(cfg: dict) -> list:
    ep = cfg.get("epo_ops", {}) or {}
    if ep.get("enabled", True) is False:
        return []
    key = os.environ.get("OPS_CONSUMER_KEY", "").strip()
    secret = os.environ.get("OPS_CONSUMER_SECRET", "").strip()
    if not key or not secret:
        log.info("epo_ops: sin OPS_CONSUMER_KEY/OPS_CONSUMER_SECRET — skip "
                 "(la fuente se activa sola al crear los secrets; registro "
                 "abierto en developers.epo.org, manual §13)")
        return []

    days_back = int(ep.get("days_back", 7))
    max_results = min(int(ep.get("max_results", 100)), 100)
    desde = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    hasta = date.today().strftime("%Y%m%d")
    q = f'pd within "{desde} {hasta}"'
    bearer = {"Authorization": f"Bearer {_token(key, secret)}"}

    # Request 1 — sondeo barato del total del índice en la ventana.
    # 404 EntityNotFound = 0 publicaciones: termina feliz (v3.9.2).
    try:
        total, _ = _parsear_biblio(
            _get_busqueda({"q": q, "Range": "1-1"}, bearer))
    except VentanaVacia:
        log.info("epo_ops — 0 publicaciones en la ventana (%s → %s): "
                 "NORMAL, no error (como openFDA en día sin carga)",
                 desde, hasta)
        return []
    if total <= 0:
        log.info("epo_ops — 0 publicaciones en la ventana (%s → %s): "
                 "NORMAL, no error", desde, hasta)
        return []
    time.sleep(1.0)  # ritmo polido entre requests (R3)

    # Request 2 — página aleatoria dentro del techo de la EPO (2000)
    inicio, fin = _pagina_aleatoria(total, max_results)
    try:
        _, docs = _parsear_biblio(
            _get_busqueda({"q": q, "Range": f"{inicio}-{fin}"}, bearer))
    except VentanaVacia:
        # Carrera ínfima: el índice se movió entre los 2 requests.
        # Nada entró a memoria: no hay nada que perder ni rescatar.
        log.warning("epo_ops — la página %d-%d volvió vacía (la ventana "
                    "se movió entre requests); sigue la corrida", inicio, fin)
        return []
    items = []
    sin_titulo = 0
    for d in docs:
        it = _to_item(d)
        if it:
            items.append(it)
        else:
            sin_titulo += 1
    de = str(total) if total <= 2000 else (
        f"{total} — muestreo dentro de los primeros 2000: techo de la EPO")
    log.info("epo_ops: %d ítems (página %d-%d de %s en %s → %s; %d docs sin "
             "título descartados)", len(items), inicio, fin, de, desde,
             hasta, sin_titulo)
    return items
