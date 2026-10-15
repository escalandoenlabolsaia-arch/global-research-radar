"""Pipeline completo: FETCH → NORMALIZE → DEDUP → CAPS → EVALUATE → DIGEST
→ NTFY → PERSIST. Punto de entrada del workflow y de pruebas manuales.
"""
import logging
import sys
from collections import defaultdict
from datetime import date, timezone
import datetime as dt

from src.config import load
from src.fetchers import openalex, arxiv, rss_generic
from src.pipeline import normalize, dedup, caps
from src.agent import evaluator
from src.notify import ntfy

log = logging.getLogger("radar")


def _write_report(evaluados, nuevos_n, dedup_n, umbral, path="reports/"):
    hoy = date.today().isoformat()
    encima = [e for e in evaluados if e.get("score", 0) >= umbral]
    p = f"{path}{hoy}.md"
    líneas = [
        f"# Radar global — {hoy}",
        "",
        f"- Nuevos hoy: **{nuevos_n}** · deduplicados: {dedup_n}",
        f"- Al agente: {len(evaluados)} · sobre umbral ({umbral}): **{len(encima)}**",
        "",
    ]
    if not encima:
        líneas += ["_Sin hallazgos sobre el umbral en esta corrida._"]
    por_rubro = defaultdict(list)
    for e in encima:
        por_rubro[e.get("rubro", "otro")].append(e)
    for rubro in sorted(por_rubro, key=lambda r: -len(por_rubro[r])):
        líneas += [f"## {rubro} ({len(por_rubro[rubro])})", ""]
        for e in sorted(por_rubro[rubro], key=lambda x: -x["score"]):
            líneas += [
                f"- **[{e['score']}] {e['title']}**",
                f"  - {e.get('region','Global')} · {e['source']} · "
                f"{e['published']} — {e.get('resumen_es','')}",
                f"  - <{e['url']}>",
                "",
            ]
    open(p, "w", encoding="utf-8").write("\n".join(líneas))
    log.info("reporte escrito: %s", p)
    return p, encima


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    cfg = load()
    umbral = int(cfg.get("threshold", 70))

    # 1. FETCH — una fuente caída no frena la corrida
    raw = []
    for nombre, mod in [("openalex", openalex), ("arxiv", arxiv),
                        ("rss", rss_generic)]:
        try:
            raw += mod.fetch(cfg)
        except Exception as e:
            log.warning("%s falló (%s) — la corrida sigue", nombre, e)
    log.info("fetch total: %d ítems", len(raw))

    # 2-3. NORMALIZE + DEDUP (memoria permanente)
    items = normalize.finalize(raw)
    seen = dedup.load("state/seen.json")
    nuevos, vistos = dedup.split_new(items, seen)
    if not nuevos:
        log.info("sin ítems nuevos — solo persisto estado")
        dedup.save(dedup.prune(seen), "state/seen.json")
        return 0

    # 4. CAPS
    lote = caps.apply(nuevos, cfg)

    # 5. EVALUATE
    evaluados = evaluator.evaluate(lote, cfg)
    if not evaluados:
        log.error("el agente no devolvió veredictos — seen NO se guarda, "
                  "mañana se reintenta el mismo lote")
        return 1

    # 6-7. DIGEST + NTFY
    _, encima = _write_report(evaluados, len(nuevos), vistos, umbral)
    top_n = int(cfg.get("notify", {}).get("top_n", 10))
    if encima:
        top = encima[:top_n]
        body = "\n".join(f"[{e['score']}] {e['title']}\n{e['url']}" for e in top)
        ntfy.send(f"🔬 Radar global — {len(encima)} hallazgos hoy", body, cfg)
    else:
        log.info("nada sobre umbral — no se envía push")

    # 8. PERSIST
    dedup.save(dedup.prune(seen), "state/seen.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
