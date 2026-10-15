"""Agente evaluador — UN agente para todo el radar (manual §6).
Anti-rotación Y anti rate-limit: consulta el catálogo real de cada
proveedor, elige el mejor modelo disponible y dosifica las llamadas
para respetar el TPM del free tier (8k tokens/min en Groq).
  Proveedor 1: Groq (GROQ_API_KEY)
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
PREF_GROQ = ["120b", "maverick", "kimi-k2", "70b", "qwen3-32b", "scout", "8b"]
PREF_GH = ["gpt-4.1-mini", "gpt-4o-mini", "mini", "gpt-oss", "4.1", "4o"]
GH_BLIND = ["openai/gpt-4.1-mini", "openai/gpt-4o-mini"]  # si /catalog no responde

CHUNK = 20           # ítems por llamada (~2.5k tokens — cabe en TPM free)
SUMMARY_CHARS = 200  # resumen recortado en el payload
MAX_TOKENS_OUT = 3000
SLEEP_BETWEEN = 40   # seg entre chunks: 1 llamada/40s ≈ 3.7k tokens/min < 8k TPM
RATE_LIMIT_WAIT = 65 # seg extra al recibir 429 (ventana de un minuto)

SYSTEM = ("Sos el evaluador de un radar global de investigación científica, "
          "patentes, salud y tecnología. Recibís ítems nuevos del día (de "
          "cualquier país e idioma) y los calificás. Priorizá: novedad real, "
          "impacto potencial, credibilidad de la fuente, interés transversal. "
          "Descartá ruido, reciclados de prensa y auto-promoción. Pensás en "
          "la lengua que sea, pero tu salida es SIEMPRE en español.")

USER_TMPL = """Calificá cada ítem del 0 al 100. Devolvé SOLO un array JSON \
válido, sin texto antes ni después, sin markdown ni ``` , un objeto por ítem, \
usando EXACTAMENTE el mismo "id" que te paso:

[{{"id":"...","score":0-100,"rubro":"...","region":"...","resumen_es":"..."}}]

Reglas:
- "rubro": uno de investigacion | preprint | descubrimiento | patente | \
salud | tech | financiamiento | otro
- "region": una de America Latina | Norteamerica | Europa | Asia | Africa | \
Oceania | Global
- "resumen_es": 1-2 frases en español claro (máx 40 palabras) que digan qué es \
y por qué importa
- Score 70+ = merece leerlo alguien que sigue ciencia y tech a diario.
- Descartado = score bajo. No inventes ítems.

ÍTEMS:
{payload}
"""


def _ranked(ids: list, prefs: list) -> list:
    """Ordena el catálogo según preferencia; sin match, al final."""
    def clave(i):
        for pos, p in enumerate(prefs):
            if p and p.lower() in i.lower():
                return pos
        return len(prefs)
    return sorted([i for i in ids if i], key=clave)


def _groq_models(key: str) -> list:
    try:
        r = get(f"{GROQ_BASE}/models", timeout=30,
                headers={"Authorization": f"Bearer {key}"})
        ids = [m.get("id", "") for m in r.json().get("data", []) if m.get("id")]
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
        ids = [m.get("id") if isinstance(m, dict) else str(m) for m in data]
        ids = [i for i in ids if i]
        log.info("github models: catálogo OK — %d modelos", len(ids))
        return ids
    except Exception as e:
        log.warning("github models: catálogo no disponible (%s) — uso candidatos "
                    "conocidos", e)
        return []


def _chat(url, model, token, messages, timeout=180):
    """POST al chat con manejo de 429 TPM-aware: espera 65s y reintenta.
    retries=1 en la capa HTTP (el backoff corto no sirve contra límites
    por minuto — acá se maneja a mano)."""
    last = None
    for intento in range(3):
        try:
            r = post(url,
                     json={"model": model, "messages": messages,
                           "temperature": 0.2, "max_tokens": MAX_TOKENS_OUT},
                     headers={"Authorization": f"Bearer {token}",
                              "Accept": "application/json",
                              "Content-Type": "application/json"},
                     timeout=timeout, retries=1)
            body = (r.text or "")[:300].replace("\n", " ")
            try:
                data = r.json()
            except Exception as e:
                raise RuntimeError(f"HTTP {r.status_code} no-JSON "
                                   f"(url final: {r.url}): {body!r}") from e
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            last = e
            if "429" in str(e) or "Rate limit" in str(e):
                log.warning("429 rate limit (%s) — espero %ds y reintento "
                            "(intento %d/3)", model, RATE_LIMIT_WAIT, intento + 1)
                time.sleep(RATE_LIMIT_WAIT)
                continue
            raise
    raise last


def _call_llm(user_msg: str, cfg: dict) -> str:
    agent_cfg = cfg.get("agent", {}) or {}
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_msg}]
    errores = []

    # 1) GROQ — prueba hasta 3 modelos del catálogo (el TPM es POR MODELO:
    #    si uno está agotado, el siguiente puede responder al instante)
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key:
        if agent_cfg.get("groq_model"):
            candidatos = [agent_cfg["groq_model"]]
        else:
            candidatos = _ranked(_groq_models(groq_key), PREF_GROQ)[:3]
        for m in candidatos:
            try:
                out = _chat(f"{GROQ_BASE}/chat/completions", m, groq_key, messages)
                log.info("agente servido por Groq (%s)", m)
                return out
            except Exception as e:
                errores.append(f"groq/{m}: {e}")
                log.warning("Groq (%s) falló: %s", m, e)

    # 2) GITHUB MODELS — catálogo si responde; si no, candidatos a ciegas
    gh = os.environ.get("GITHUB_TOKEN", "")
    if gh:
        if agent_cfg.get("github_model"):
            candidatos = [agent_cfg["github_model"]]
        else:
            candidatos = _ranked(_gh_models(gh), PREF_GH)[:2] or GH_BLIND
        for m in candidatos:
            try:
                out = _chat(f"{GH_BASE}/inference/chat/completions", m, gh, messages)
                log.info("agente servido por GitHub Models (%s)", m)
                return out
            except Exception as e:
                errores.append(f"gh/{m}: {e}")
                log.warning("GitHub Models (%s) falló: %s", m, e)

    raise RuntimeError("ningún proveedor LLM pudo responder — "
                       + " | ".join(errores[-3:]))


def _extract_json(text: str):
    """Limpia fences ``` y extrae el array JSON de la respuesta."""
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
        f'título: {it["title"][:150]} | resumen: {it["summary"][:SUMMARY_CHARS]}'
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
    """Enriquece cada ítem con score/rubro/region/resumen_es, ordena por score.
    Dosificación: 1 llamada cada ~40s — 220 ítems ≈ 11 chunks ≈ 12-15 min."""
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
