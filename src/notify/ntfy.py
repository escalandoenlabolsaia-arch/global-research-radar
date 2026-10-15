"""Push a ntfy (manual §6): top N en ~4KB. NTFY_TOKEN opcional (topic reservado).
Lección corrida 6: los headers HTTP solo admiten latin-1 — un emoji en el
Title rompe el envío. Title se envía como RFC 2047 (ntfy lo soporta) y el
emoji vive en el cuerpo, que viaja UTF-8.
"""
import logging
import os
from email.header import Header

import requests

log = logging.getLogger(__name__)

NTFY = "https://ntfy.sh"


def _title_header(title: str) -> str:
    """Title apto para header: tal cual si es latin-1-safe; si hay emojis/acentos
    fuera de latin-1, RFC 2047 (=?utf-8?b?...?=) que ntfy decodifica nativamente."""
    try:
        title.encode("latin-1")
        return title
    except UnicodeEncodeError:
        try:
            return Header(title, "utf-8").encode()
        except Exception:
            return title.encode("ascii", "ignore").decode() or "Radar global"


def send(title: str, body: str, cfg: dict, click_url: str = "") -> bool:
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        log.warning("ntfy: NTFY_TOPIC no definido — no se envía")
        return False
    max_bytes = int(cfg.get("notify", {}).get("max_bytes", 4096))
    body = body.encode("utf-8")[:max_bytes - 200].decode("utf-8", "ignore")
       headers = {
        "Title": _title_header(title),
        "Tags": "microscope",
        "Priority": "default",
    }
    if click_url:
        headers["Click"] = click_url  # un tap en el push abre el informe
    token = os.environ.get("NTFY_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(f"{NTFY}/{topic}", data=body.encode("utf-8"),
                          headers=headers, timeout=30)
        r.raise_for_status()
        log.info("ntfy: enviado (%d bytes)", len(body))
        return True
    except Exception as e:
        log.warning("ntfy: falló el envío (%s) — la corrida sigue", e)
        return False
