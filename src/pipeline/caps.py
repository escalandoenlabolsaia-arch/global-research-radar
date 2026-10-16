"""Caps — válvulas anti-inundación del manual §5.
Round-robin entre fuentes: ninguna acapara el cupo que llega al agente.
v3.6: caps.per_source_override permite fijar un cupo distinto por fuente
(p.ej. 25 para las fuentes biosalud nuevas) sin tocar el global. Sin el
bloque, el comportamiento es EXACTAMENTE el de siempre.
"""
import logging
from collections import defaultdict

log = logging.getLogger(__name__)


def apply(items: list, cfg: dict) -> list:
    caps = cfg.get("caps", {})
    per_source = int(caps.get("per_source", 50))
    total = int(caps.get("total", 300))
    overrides = caps.get("per_source_override", {}) or {}
    if per_source <= 0 or total <= 0:
        return items

    by_src = defaultdict(list)
    for it in items:
        by_src[it["source"]].append(it)

    elegidos = []
    if not overrides:
        # --- camino clásico (byte a byte el de fases 1): cero regresiones
        vuelta = 0
        while len(elegidos) < total and vuelta < per_source:
            for group in by_src.values():
                if vuelta < len(group):
                    elegidos.append(group[vuelta])
                    if len(elegidos) >= total:
                        break
            vuelta += 1
    else:
        # --- round-robin con cupo propio por fuente
        tomados = {src: 0 for src in by_src}
        while len(elegidos) < total:
            agregó = False
            for src, group in by_src.items():
                cap = int(overrides.get(src, per_source))
                if tomados[src] < min(cap, len(group)):
                    elegidos.append(group[tomados[src]])
                    tomados[src] += 1
                    agregó = True
                    if len(elegidos) >= total:
                        break
            if not agregó:
                break  # todas las fuentes agotaron su cupo

    log.info("caps: %d → %d ítems (per_source=%d, total=%d, fuentes=%d%s)",
             len(items), len(elegidos), per_source, total, len(by_src),
             f", override={overrides}" if overrides else "")
    return elegidos
