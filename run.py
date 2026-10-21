"""Pipeline completo: FETCH → NORMALIZE → DEDUP → CAPS → EVALUATE → DIGEST
→ NTFY → PERSIST. Punto de entrada del workflow y de pruebas manuales.
v3.4: push compacto (top 5, resumen 140 chars) + header Click al informe.
v3.6: fuentes Fase 2 (biosalud) — clinicaltrials + openfda en el dispatch.
v3.8: fuentes Fase 3 (patentes) — patentsview + lens en el dispatch
(salta solos si no existen los secrets; Google News patentes vía rss).
v3.9: + epo_ops (EPO OPS, publicaciones EP+WO) en el dispatch — skip
silencioso hasta crear los secrets OPS_CONSUMER_KEY/OPS_CONSUMER_SECRET.
v3.10: + nih_reporter (NIH RePORTER, financiamiento/predicción) en el
dispatch — keyless (sin secret, patrón OpenAlex). Proyectos con inicio
FUTURO son señal de anticipación, no ruido.
"""
import logging
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from src.config import load
from src.fetchers import (openalex, arxiv, rss_generic, clinicaltrials,
                          openfda, patentsview, lens, epo_ops, nih_reporter)
from src.pipeline import normalize, dedup, caps
from src.agent import evaluator
from src.notify import ntfy

log = logging.getLogger("radar")


def _write_report(evaluados, nuevos_n, dedup_n, umbral, path="reports/"):
    hoy = date.today().isoformat()
    encima = [e for e in evaluados if e.get("score", 0) >= umbral]
    Path(path).mkdir(parents=True, exist_ok=True)
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
    Path(p).write_text("\n".join(líneas), encoding="utf-8")
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
                        ("rss", rss_generic),
                        ("clinicaltrials", clinicaltrials),
                        ("openfda", openfda),
                        ("patentsview", patentsview),
                        ("lens", lens),
                        ("epo_ops", epo_ops),
                        ("nih_reporter", nih_reporter)]:
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

    # 6-7. DIGEST + NTFY (Click: un tap en el push abre el informe del día)
    report_path, encima = _write_report(evaluados, len(nuevos), vistos, umbral)
    top_n = int(cfg.get("notify", {}).get("top_n", 10))
    if encima:
        top = encima[:top_n]
        body = "\n\n".join(
            f"[{e['score']}] {e['title']}\n{e.get('resumen_es', '')[:140]}\n{e['url']}"
            for e in top
        )
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        click = (f"https://github.com/{repo}/blob/main/{report_path}"
                 if repo else "")
        ntfy.send(f"🔬 Radar global — {len(encima)} hallazgos hoy",
                  body, cfg, click_url=click)
    else:
        log.info("nada sobre umbral — no se envía push")

    # 8. PERSIST — solo queda en memoria lo que el agente EVALUÓ de verdad.
    #    Lo que quedó fuera (caps o chunk fallido) se reintenta mañana.
    ids_eval = {e["id"] for e in evaluados}
    perdidos = [it["id"] for it in nuevos if it["id"] not in ids_eval]
    for iid in perdidos:
        seen.pop(iid, None)
    if perdidos:
        log.info("persist: %d ítems sin veredicto vuelven al radar mañana",
                 len(perdidos))
    dedup.save(dedup.prune(seen), "state/seen.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
