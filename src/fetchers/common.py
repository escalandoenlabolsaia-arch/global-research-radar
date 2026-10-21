"""Utilidades HTTP: GET/POST con reintentos, backoff y diagnóstico
(loguea un fragmento del body cuando un endpoint falla — clave para
distinguir rate limit / auth / error real)."""
import logging
import time

import requests

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "global-research-radar/1.0 (polite pool; contacto en config)"}


def _con_reintentos(metodo, url, kwargs, retries):
    last_exc = None
    for attempt in range(retries):
        r = None
        detalle = ""
        try:
            r = requests.request(metodo, url, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            if r is not None:
                detalle = " | body: " + (r.text or "")[:200].replace("\n", " ")
            log.warning("%s %s intento %d/%d falló (%s)%s — espero %ds",
                        metodo, url[:80], attempt + 1, retries, e, detalle,
                        2 ** attempt)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{metodo} {url[:120]} agotó {retries} intentos: "
                       f"{last_exc}{detalle}") from last_exc


def get(url, params=None, timeout=30, retries=3, headers=None):
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    return _con_reintentos("GET", url,
                           dict(params=params, headers=h, timeout=timeout),
                           retries)


def post(url, json=None, data=None, timeout=60, retries=3, headers=None):
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    return _con_reintentos("POST", url,
                           dict(json=json, data=data, headers=h, timeout=timeout),
                           retries)


def post_json(url, payload, logger=None, timeout=60, retries=3, headers=None):
    """POST con body JSON y parseo tolerante de la respuesta.

    Devuelve el dict/list parseado, o None si la respuesta no es JSON
    (loguea un fragmento del body para diagnóstico — R4).
    Pensado para NIH RePORTER (POST-only, respuesta JSON en snake_case).
    """
    lg = logger or log
    try:
        r = post(url, json=payload, timeout=timeout, retries=retries,
                 headers=headers)
    except RuntimeError as e:
        lg.warning("post_json %s agotó reintentos: %s", url[:80], e)
        return None
    try:
        return r.json()
    except ValueError:
        cuerpo = (r.text or "")[:300].replace("\n", " ")
        lg.warning("post_json %s: respuesta no-JSON | body: %s",
                   url[:80], cuerpo)
        return None


def get_logger(nombre: str) -> logging.Logger:
    """Logger nombrado para los fetchers (evita depender del root logger)."""
    return logging.getLogger(nombre)



def post_json(url, payload, logger=None, timeout=60, retries=3, headers=None):
    """POST con body JSON y parseo tolerante de la respuesta.

    Devuelve el dict/list parseado, o None si la respuesta no es JSON
    (loguea un fragmento del body para diagnóstico — R4).
    Pensado para NIH RePORTER (POST-only, respuesta JSON en snake_case).
    """
    lg = logger or log
    try:
        r = post(url, json=payload, timeout=timeout, retries=retries,
                 headers=headers)
    except RuntimeError as e:
        lg.warning("post_json %s agotó reintentos: %s", url[:80], e)
        return None
    try:
        return r.json()
    except ValueError:
        cuerpo = (r.text or "")[:300].replace("\n", " ")
        lg.warning("post_json %s: respuesta no-JSON | body: %s",
                   url[:80], cuerpo)
        return None


def get_logger(nombre: str) -> logging.Logger:
    """Logger nombrado para los fetchers (evita depender del root logger)."""
    return logging.getLogger(nombre)
