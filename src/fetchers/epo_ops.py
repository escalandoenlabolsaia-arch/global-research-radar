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
v3.9.3 — FIX TECHO REAL (corrida 17, R11): el techo de 2000 no es
del Range sino de la QUERY ENTERA: FAQ oficial de la EPO — "If there
are more than 2 000 hits in your results list, you will have to
limit your search query to reduce the number of results". Con
86502 hits la EPO devolvió el total pero CERO documentos (ops:search-
result vacío, XSD: es opcional) — la página salió "0 ítems" sin
error. Rediseño: se sondea UNA subclase IPC al azar por corrida
(ic=<sub> and pd within "..."): tajada angosta del flujo semanal
mundial, siempre bajo el techo, muestreo honesto rotatorio (la dedup
cobra cada documento UNA vez). Hasta 4 subclases por corrida: si la
elegida da 0 resultados o supera 2000 hits, el log lo dice y se
prueba la siguiente.
v3.9.4 — FIX FORMATO REAL (corrida 18, R11): la subclase C22 dio 610
hits (el sondeo v3.9.3 funcionó: total < techo 2000) pero la página
47-146 volvió "0 ítems; 0 docs sin título" — la respuesta del search
PELO trae ops:search-result > ops:publication-reference >
document-id (mini-referencias docdb SIN título, todo como elementos
hijos), NUNCA exchange-document: el parser viejo buscaba lo que no
venía (corridas 17 y 18 con total > 0 y 0 docs visibles). Forma
correcta verificada contra la FAQ oficial de la EPO + el cliente
Python de referencia (ip-tools): el CONSTITUYENTE /biblio en el path
— published-data/search/biblio?q=... — es el que devuelve la
bibliografía completa (exchange-document con invention-title y
solicitantes). Fixes: (1) la página pide .../search/biblio; el
sondeo total sigue en el search pelado (respuesta mínima); (2) el
rango viaja por las dos puertas documentadas: query param Range
(ejemplo vivo de la EPO) y header X-OPS-Range (doc v1.0.4+ y cliente
oficial); (3) max_results capado a 25 — lote clásico de OPS, y el
caps override de epo_ops ya era 25; (4) el parser acepta AMBOS
formatos (exchange-document primero, mini-referencias de reserva);
(5) página sin ítems ya NO corta la fuente: deja el cuerpo en el log
(R11) y prueba la siguiente subclase — en la corrida 18 el "0 ítems"
feliz abortó las otras 3 subclases sin avisar.
Registro ABIERTO con mail común en developers.epo.org, gratis hasta
4 GB/semana (carta de fair-use de la EPO) y los mismos datos que
Espacenet. El índice de BÚSQUEDA de OPS es MUNDIAL (DOCDB, ~100
oficinas: incluye EP, WO/PCT y las concesiones US que PatentsView
no da — la descripción "EP+WO" correspondía al retrieval, no a
search; corrida 17 lo probó con 86502 resultados en 7 días).

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
# Constituyente biblio (FAQ oficial de la EPO + cliente ip-tools):
# misma búsqueda pero cada hit viene como exchange-document completo
# (invention-title + solicitantes), no como mini-referencia sin título.
SEARCH_BIBLIO = SEARCH + "/biblio"

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


def _get_busqueda(params: dict, headers: dict, intentos: int = 2,
                  url: str = SEARCH):
    """GET al índice distinguiendo 'ventana vacía' de error real.
    url=SEARCH_BIBLIO (v3.9.4) pide la página con el constituyente
    biblio: la respuesta trae exchange-document CON título. El sondeo
    de total usa el search pelado (mini-referencias, respuesta
    mínima). Usa common.get con retries=1: el reintento genérico
    quemaría 3 intentos + 7s en un 404 de ventana vacía, que es
    PERMANENTE, no transitorio. Los reintentos propios son solo para
    fallos que SÍ pueden ser transitorios (red, 5xx, 429)."""
    for intento in range(1, intentos + 1):
        try:
            return get(url, params=params, timeout=60, retries=1,
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


def _encabezados(bearer: dict, rango: str) -> dict:
    """El rango viaja por las DOS puertas documentadas: query param
    Range (forma del ejemplo vivo de la EPO) y header X-OPS-Range
    (forma de la doc v1.0.4+ y del cliente Python de referencia).
    Mismo valor en ambas: si la EPO muda una, la otra sigue."""
    return {**bearer, "X-OPS-Range": rango}


# Subclases IPC candidatas (nivel de 4 caracteres, válido según CQL:
# ic=H04W — ejemplos del cliente Go oficial de referencia). Tajada
# angosta = siempre bajo el techo de 2000. Las súper hot (A61 medicina,
# G06 computación, H01/H04 electrónica/telecom) entran IGUAL: si el
# sondeo da >2000 hits el log lo dice y se prueba la siguiente —
# preferimos que la EPO decida, no nuestra estimación.
SUBCLASES_IPC = (
    "A01", "A23", "A24", "A41", "A43", "A45", "A47", "A61", "A62", "A63",
    "B01", "B05", "B08", "B21", "B23", "B25", "B27", "B29", "B32", "B33",
    "B41", "B60", "B62", "B63", "B64", "B65", "B81", "B82",
    "C02", "C05", "C07", "C08", "C09", "C11", "C12", "C14", "C21", "C22",
    "C23", "C25", "C30",
    "E02", "E04", "E21", "F01", "F03", "F04", "F15", "F16", "F17", "F21",
    "F24", "F28", "F41", "F42",
    "G01", "G02", "G03", "G05", "G06", "G08", "G10", "G15", "G16", "G21",
    "H01", "H02", "H03", "H04", "H05", "H10",
)
INTENTOS_SUBCLASE = 4  # sondeos máximos por corrida (rota al azar)


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


def _doc_a_dict(doc) -> dict:
    """exchange-document (respuesta del constituyente biblio) → dict
    crudo. cc/num/kind como atributos; título EN preferido; hasta 6
    solicitantes."""
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
    return {"cc": cc, "num": num, "kind": kind, "fecha": fecha,
            "titulo": titulo or (titulos_alt[0] if titulos_alt else ""),
            "solicitantes": solicitantes[:6]}


def _parsear_biblio(resp) -> tuple:
    """XML → (total_result_count, lista de dicts crudos). Comodines {*}
    para no casarnos con los namespaces exactos (R11).

    DOS formatos reales (corrida 18 + FAQ de la EPO): el search PELO
    trae ops:search-result > ops:publication-reference > document-id
    (mini-referencias docdb SIN título, campos como ELEMENTOS hijos);
    el search CON el constituyente /biblio trae exchange-documents >
    exchange-document con bibliographic-data (título + solicitantes).
    Se aceptan ambos: primero exchange-document (la página pide
    /search/biblio); si no hay, mini-referencias (sondeo y reserva —
    quedan sin título y _to_item los descarta)."""
    raiz = ET.fromstring(resp.content)
    biblio = raiz.find("{*}biblio-search")
    if biblio is None:
        raise RuntimeError("ops search: respuesta sin biblio-search (R11: "
                           "loguear cuerpo y revisar esquema)")
    total = int(biblio.get("total-result-count") or 0)
    docs = [_doc_a_dict(doc)
            for doc in biblio.findall(".//{*}exchange-document")]
    if not docs:  # search pelado: mini-referencias sin título
        for did in biblio.findall(
                ".//{*}publication-reference/{*}document-id"):
            docs.append({
                "cc": (did.findtext("{*}country") or "").strip(),
                "num": (did.findtext("{*}doc-number") or "").strip(),
                "kind": (did.findtext("{*}kind") or "").strip(),
                "fecha": (did.findtext("{*}date") or "")[:10],
                "titulo": "", "solicitantes": []})
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
    # v3.9.4: lote clásico de OPS. La FAQ habla de lotes de hasta 100,
    # pero 25 es el default documentado y el caps override de epo_ops
    # ya era 25 — pedir más sería descartarlo en caps de todos modos.
    max_results = min(int(ep.get("max_results", 25)), 25)
    desde = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    hasta = date.today().strftime("%Y%m%d")
    bearer = {"Authorization": f"Bearer {_token(key, secret)}"}

    # La query pd-only de 7 días pisa el techo de 2000 hits (86502 en
    # la corrida 17) y la EPO NO sirve documentos por encima (FAQ
    # oficial). v3.9.3: una subclase IPC al azar = tajada angosta y
    # honesta del flujo semanal, siempre bajo el techo.
    elegidas = random.sample(SUBCLASES_IPC, INTENTOS_SUBCLASE)
    motivos, ultimo_q = [], ""
    for sub in elegidas:
        q = f'ic={sub} and pd within "{desde} {hasta}"'
        ultimo_q = q
        try:
            total, _ = _parsear_biblio(
                _get_busqueda({"q": q, "Range": "1-1"},
                              _encabezados(bearer, "1-1")))
        except VentanaVacia:
            motivos.append(f"{sub}: 0 publicaciones esta semana")
            continue
        except Exception as e:  # noqa: BLE001 — red/4xx: probar otra subclase
            log.warning("epo_ops — sondeo %s falló (%s) — pruebo otra "
                        "subclase", sub, str(e)[:160])
            motivos.append(f"{sub}: error")
            continue
        if total <= 0:
            motivos.append(f"{sub}: 0 publicaciones esta semana")
            continue
        if total > 2000:
            log.info("epo_ops — %s: %d resultados supera el techo de 2000 "
                     "hits de la EPO; pruebo otra subclase", sub, total)
            motivos.append(f"{sub}: {total} > 2000")
            continue
        time.sleep(1.0)  # ritmo polido entre requests (R3)

        inicio, fin = _pagina_aleatoria(total, max_results)
        rango = f"{inicio}-{fin}"
        try:
            resp = _get_busqueda({"q": q, "Range": rango},
                                 _encabezados(bearer, rango),
                                 url=SEARCH_BIBLIO)
        except VentanaVacia:
            # Carrera ínfima: el índice se movió entre los 2 requests.
            motivos.append(f"{sub}: página {inicio}-{fin} vacía")
            continue
        _, docs = _parsear_biblio(resp)
        items = []
        sin_titulo = 0
        for d in docs:
            it = _to_item(d)
            if it:
                items.append(it)
            else:
                sin_titulo += 1
        if not items:
            # Lección corrida 18: el "0 ítems feliz" abortaba el resto
            # de las subclases sin avisar. Página sin fruto = señal, no
            # final: el cuerpo queda en el log (R11) y se prueba la
            # siguiente subclase.
            cuerpo = " ".join((resp.text or "").split())[:400]
            log.warning("epo_ops — %s: %d hits, página %d-%d sin ítems "
                        "(%d docs parseados, %d sin título); cuerpo: %s",
                        sub, total, inicio, fin, len(docs), sin_titulo,
                        cuerpo)
            motivos.append(f"{sub}: página sin ítems ({total} hits)")
            continue
        log.info("epo_ops: %d ítems (subclase IPC %s, página %d-%d de %d "
                 "en %s → %s; %d refs sin título descartadas)",
                 len(items), sub, inicio, fin, total, desde, hasta,
                 sin_titulo)
        return items

    if any(m.endswith("error") for m in motivos):
        # Error de red/HTTP en TODOS los intentos: que se vea como
        # falla de fuente (run.py lo loguea R6 y la corrida sigue).
        raise RuntimeError(
            f"epo_ops sin subclase viable en {INTENTOS_SUBCLASE} intentos "
            f"(última query: {ultimo_q}) — motivos: {'; '.join(motivos)}")
    log.info("epo_ops — sin subclase con ítems esta corrida (%s): "
             "NORMAL, mañana rota otra (ventana %s → %s)",
             "; ".join(motivos), desde, hasta)
    return []
