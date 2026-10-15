"""Caps — válvulas anti-inundación del manual §5.
Round-robin entre fuentes: ninguna acapara el cupo que llega al agente.
"""
import logging
from collections import defaultdict

log = logging.getLogger(__name__)


def apply(items: list, cfg: dict) -> list:
    caps = cfg.get("caps", {})
    per_source = int(caps.get("per_source", 50))
    total = int(caps.get("total", 300))
    if per_source <= 0 or total <= 0:
        return items

    by_src = defaultdict(list)
    for it in items:
        by_src[it["source"]].append(it)

    elegidos = []
    vuelta = 0
    while len(elegidos) < total and vuelta < per_source:
        for group in by_src.values():
            if vuelta < len(group):
                elegidos.append(group[vuelta])
                if len(elegidos) >= total:
                    break
        vuelta += 1

    log.info("caps: %d → %d ítems (per_source=%d, total=%d, fuentes=%d)",
             len(items), len(elegidos), per_source, total, len(by_src))
    return elegidos
