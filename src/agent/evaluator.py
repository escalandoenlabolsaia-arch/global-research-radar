"""Agente evaluador — UN agente para todo el radar (manual §6).
Anti-rotación de catálogos: cada corrida consulta el catálogo REAL de
cada proveedor y elige el mejor modelo disponible. Nada se rompe cuando
un modelo cambia de nombre o se retira.
  Proveedor 1: Groq (GROQ_API_KEY — clave probada del usuario)
  Proveedor 2: GitHub Models (GITHUB_TOKEN, models: read — $0)
Salida SIEMPRE en español: score 0-100 + rubro + región + resumen_es.
"""
import json
import logging
import os
import time

from src.fetchers.common import get, post

log = logging.getLogger(__name__)

GROQ_BASE = "https://api.groq.com/openai/v1"
GH_BASE = "https://models.github.ai"

# Preferencia de modelos: primero que exista en el catálogo gana.
PREF_GROQ = ["llama-3.3-70b", "gpt-oss-120b", "maverick", "kimi-k2", "70b",
             "120b", "qwen3-32b", "scout", "llama-3.1-8b", "8b"]
PREF_GH = ["gpt-4.1-mini", "gpt-4o-mini", "mini", "gpt-oss", "4.1", "4o"]

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


def _pick_available(ids: list, prefs: list, override: str = "") -> str:
    """Override del config > primera preferencia presente > primero del catálogo."""
    if override:
        return override
    for p in prefs:
        for i in ids:
            if p and p.lower() in i.lower():
                return i
    return ids[0] if ids else ""


def _groq_models(key: str) -> list:
    try:
        r = get(f"{GROQ_BASE}/models", timeout=30,
                headers={"Authorization": f"Bearer {key}"})
        data = r.json().get("data", [])
        ids = [m.get("id", "") for m in data if m.get("id")]
        log.info("groq: catálogo OK — %d modelos disponibles", len(ids))
        return ids
    except Exception as e:
        log.warning("groq: no pude listar catálogo (%s)", e)
        return []


def _gh_models(token: str) -> list:
    try:
        r = get(f"{GH_BASE}/catalog", timeout=30,
                headers={"Authorization": f"Bearer {token}"})
        data = r.json()
        if isinstance(data, dict):
            data = data.get("models", data.get("data", []))
        ids = []
        for m in data:
            mid = m.get("id") if isinstance(m, dict) else str(m)
            if mid:
                ids.append(mid)
        log.info("github models: catálogo OK — %d modelos disponibles", len(ids))
        return ids
    except Exception as e:
        log.warning("github models: no pude listar catálogo (%s)", e)
        return []


def _chat(url, model, token, messages, timeout=180):
    """POST al endpoint de chat. Diagnóstico total: URL final tras redirects,
    status y fragmento del cuerpo en el error."""
    r = post(url,
             json={"model": model, "messages": messages, "temperature": 0.2},
             headers={"Authorization": f"Bearer {token}",
                      "Accept": "application/json",
                      "Content-Type": "application/json"},
             timeout=timeout)
    body = (r.text or "")[:300].replace("\n", " ")
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"HTTP {r.status_code} no-JSON (url final: {r.url}): "
                           f"{body!r}") from e
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"HTTP {r.status_code} JSON sin 'choices' "
                           f"(url final: {r.url}): {body!r}") from e


def _call_llm(user_msg: str, cfg: dict) -> str:
    agent_cfg = cfg.get("agent", {}) or {}
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_msg}]

    # 1) GROQ (primario — clave probada)
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key:
        ids = _groq_models(groq_key)
        model = _pick_available(ids, PREF_GROQ, agent_cfg.get("groq_model", ""))
        if model:
            try:
                out = _chat(f"{GROQ_BASE}/chat/completions", model, groq_key,
                            messages)
                log.info("agente servido por Groq (%s)", model)
                return out
            except Exception as e:
                log.warning("Groq (%s) falló: %s", model, e)

    # 2) GITHUB MODELS (fallback — $0 con GITHUB_TOKEN)
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if gh_token:
        ids = _gh_models(gh_token)
        model = _pick_available(ids, PREF_GH, agent_cfg.get("github_model", ""))
        if model:
            try:
                out = _chat(f"{GH_BASE}/inference/chat/completions", model,
                            gh_token, messages)
                log.info("agente servido por GitHub Models (%s)", model)
                return out
            except Exception as e:
                log.warning("GitHub Models (%s) falló: %s", model, e)

    raise RuntimeError("ningún proveedor LLM pudo responder "
                       "(Groq y GitHub Models fallaron)")


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


def _verdicts_for_chunk(chunk: list, cfg: dict) -> dict:
    payload = "\n".join(
        f'- id: {it["id"]} | fuente: {it["source"]} | fecha: {it["published"]} | '
        f'título: {it["title"]} | resumen: {it["summary"][:300]}'
        for it in chunk
    )
    out = _call_llm(USER_TMPL.format(payload=payload), cfg)
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
            vdict = _verdicts_for_chunk(chunk, cfg)
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
