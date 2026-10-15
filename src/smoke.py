"""Prueba rápida de los 3 fetchers, sin agente ni ntfy:  python -m src.smoke"""
import logging

from src.config import load
from src.fetchers import openalex, arxiv, rss_generic

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load()
    for nombre, mod in [("openalex", openalex), ("arxiv", arxiv), ("rss", rss_generic)]:
        try:
            print(f"{nombre}: {len(mod.fetch(cfg))} ítems")
        except Exception as e:
            print(f"{nombre}: FALLÓ — {e}")
