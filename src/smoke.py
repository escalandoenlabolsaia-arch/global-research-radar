"""Prueba rápida de los fetchers, sin agente ni ntfy:  python -m src.smoke
v3.6: suma clinicaltrials y openfda (Fase 2 biosalud).
v3.8: suma patentsview y lens (Fase 3 patentes) — sin secrets hacen skip
silencioso y muestran 0 ítems; con secrets activan la fuente real.
v3.9: suma epo_ops (EPO OPS) — ídem: sin secrets OPS_CONSUMER_KEY/
OPS_CONSUMER_SECRET hace skip silencioso y muestra 0 ítems.
"""
import logging

from src.config import load
from src.fetchers import (openalex, arxiv, rss_generic, clinicaltrials,
                          openfda, patentsview, lens, epo_ops)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load()
    for nombre, mod in [("openalex", openalex), ("arxiv", arxiv),
                        ("rss", rss_generic),
                        ("clinicaltrials", clinicaltrials),
                        ("openfda", openfda),
                        ("patentsview", patentsview),
                        ("lens", lens),
                        ("epo_ops", epo_ops)]:
        try:
            print(f"{nombre}: {len(mod.fetch(cfg))} ítems")
        except Exception as e:
            print(f"{nombre}: FALLÓ — {e}")
