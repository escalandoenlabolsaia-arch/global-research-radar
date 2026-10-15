"""Push a ntfy (manual §6): top N en ~4KB. NTFY_TOKEN opcional (topic reservado)."""
import logging
import os

import requests

log = logging.getLogger(__name__)

NTFY = "https://ntfy.sh"


def send(title: str, body: str, cfg: dict) -> bool:
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        log.warning("ntfy: NTFY_TOPIC no definido — no se envía")
        return False
    max_bytes = int(cfg.get("notify", {}).get("max_bytes", 4096))
    body = body.encode("utf-8")[:max_bytes - 200].decode("utf-8", "ignore")
    headers = {
        "Title": title,
        "Tags": "microscope",
        "Priority": "default",
    }
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
