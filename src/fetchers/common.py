"""Utilidades HTTP compartidas: GET con reintentos y backoff exponencial."""
import logging
import time

import requests

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "global-research-radar/1.0 (polite pool; contacto en config)"}


def get(url, params=None, timeout=30, retries=3, headers=None):
    """Lanza la última excepción si agota los reintentos (el runner la captura)."""
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            wait = 2 ** attempt
            log.warning("GET %s intento %d/%d falló (%s) — espero %ds",
                        url[:80], attempt + 1, retries, e, wait)
            time.sleep(wait)
    raise last
