"""Agente evaluador — UN agente para todo el radar (manual §6).
Primario: GitHub Models (GITHUB_TOKEN del workflow, permiso models: read — $0).
Fallback: Groq (secret GROQ_API_KEY, opcional — si no existe, se ignora).
Salida SIEMPRE en español: score 0-100 + rubro + región + resumen_es.
"""
import json
import logging
import os
import time

from src.fetchers.common import post

log = logging.getLogger(__name__)

GH_URL = "https://models.github.ai/inference/chat/completions"
GH_MODEL = "openai/gpt-4o-mini"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

CHUNK = 60          # ítems por llamada al LLM
SLEEP_BETWEEN = 2   # pausa entre chunks (rate limit amable)

SYSTEM = ("Sos el evaluador de un radar global de investigación científica, "
          "patentes, salud y tecnología. Recibís ítems nuevos del día (de "
          "cualquier país e idioma) y los calificás. Priorizá: novedad real, "
          "impacto potencial, credibilidad de la fuente, interés transversal. "
          "Descartá ruido, reciclados de prensa y auto-promoción. Pensás en "
          "la lengua que sea, pero tu salida es SIEMPRE en español.")

USER_TMPL = """Calificá cada ítem del 0 al 100. Devolvé SOLO un array JSON \
válido, sin texto antes ni después, un objeto por ítem, usando EXACTAMENTE \
el mismo "id" que te paso:

[{{"id":"...","score":0-100,"rubro":"...","region":"...","resumen_es":"..."}}]

Reglas:
- "rubro": uno de investigacion | preprint | descubrimiento | patente | \
salud | tech | financiamiento | otro
- "region": una de America Latina | Norteamerica | Europa | Asia | Africa | \
Oceania | Global
- "resumen_es": 1-2 frases en español claro que digan qué es y por qué importa
- Score 70+ = merece leerlo alguien que sigue ciencia y tech a diario.
- Descartado = score bajo. No inventes ítems.

ÍTEMS:
{payload}
"""


def _post_chat(url, model, token, messages, timeout=180):
    """POST al endpoint de chat. Si la respuesta no es JSON de OpenAI,
    el error INCLUYE status + fragmento del cuerpo (diagnóstico exacto)."""
    r = post(url,
             json={"model": model, "messages": messages, "temperature": 0.2},
             headers={"Authorization": f"Bearer {token}",
                      "Accept": "application/json",
                      "Content-Type": "application/json"},
             timeout=timeout)
    cuerpo = (r.text or "")[:300].replace("\n", " ")
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"respuesta no-JSON (HTTP {r.status_code}): "
                           f"{cuerpo!r}") from e
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"JSON sin 'choices' (HTTP {r.status_code}): "
                           f"{cuerpo!r}") from e


def _call_llm(user_msg: str) -> str:
    """GitHub Models primero; si falla y existe GROQ_API_KEY, Groq."""
    try:
        return _post_chat(GH_URL, GH_MODEL, os.environ["GITHUB_TOKEN"], [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ])
    except Exception as e:
        log.warning("GitHub Models falló (%s) — pruebo Groq", e)
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        raise RuntimeError("GitHub Models falló y no hay GROQ_API_KEY de respaldo")
    return _post_chat(GROQ_URL, GROQ_MODEL, groq_key, [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_msg},
    ])


def _extract_json(text: str):
    """Los LLM a veces envuelven el JSON en ```json ... ``` — se limpia."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t.split("\n", 1)[-1] if "\n" in t else t
    for a, b in (("[", "]"), ("{", "}")):
        i, j = t.find(a), t.rfind(b)
        if i != -1 and j > i:
            try:
                data = json.loads(t[i:j + 1])
                return data if isinstance(data, list) else data.get("items", [])
            except json.JSONDecodeError:
                continue
    raise ValueError("respuesta del agente sin JSON parseable")


def _verdicts_for_chunk(chunk: list) -> dict:
    payload = "\n".join(
        f'- id: {it["id"]} | fuente: {it["source"]} | fecha: {it["published"]} | '
        f'título: {it["title"]} | resumen: {it["summary"][:300]}'
        for it in chunk
    )
    out = _call_llm(USER_TMPL.format(payload=payload))
    verdicts = {}
    for v in _extract_json(out):
        if isinstance(v, dict) and v.get("id"):
            try:
                score = int(v.get("score", 0) or 0)
            except (TypeError, ValueError):
                score = 0
            verdicts[v["id"]] = {
                "score": score,
                "rubro": str(v.get("rubro", "otro")),
                "region": str(v.get("region", "Global")),
                "resumen_es": str(v.get("resumen_es", "")).strip(),
            }
    return verdicts


def evaluate(items: list, cfg: dict) -> list:
    """Enriquece cada ítem con score/rubro/region/resumen_es, ordena por score."""
    results = []
    n_chunks = (len(items) + CHUNK - 1) // CHUNK
    for i in range(0, len(items), CHUNK):
        chunk = items[i:i + CHUNK]
        try:
            vdict = _verdicts_for_chunk(chunk)
        except Exception as e:
            log.warning("chunk %d/%d falló (%s) — esos ítems se reintentan mañana",
                        i // CHUNK + 1, n_chunks, e)
            continue
        for it in chunk:
            v = vdict.get(it["id"])
            if v:
                it.update(v)
                results.append(it)
        log.info("agente: chunk %d/%d → %d/%d veredictos",
                 i // CHUNK + 1, n_chunks, len(vdict), len(chunk))
        if i + CHUNK < len(items):
            time.sleep(SLEEP_BETWEEN)
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    log.info("agente: %d de %d ítems evaluados", len(results), len(items))
    return results
