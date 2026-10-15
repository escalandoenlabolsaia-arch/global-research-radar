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
