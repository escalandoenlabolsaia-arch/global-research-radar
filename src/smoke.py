"""Prueba rápida de los 5 fetchers, sin agente ni ntfy:  python -m src.smoke
v3.6: suma clinicaltrials y openfda (Fase 2 biosalud).
"""
import logging

from src.config import load
from src.fetchers import openalex, arxiv, rss_generic, clinicaltrials, openfda

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load()
    for nombre, mod in [("openalex", openalex), ("arxiv", arxiv),
                        ("rss", rss_generic),
                        ("clinicaltrials", clinicaltrials),
                        ("openfda", openfda)]:
        try:
            print(f"{nombre}: {len(mod.fetch(cfg))} ítems")
        except Exception as e:
            print(f"{nombre}: FALLÓ — {e}")
