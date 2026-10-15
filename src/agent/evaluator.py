"""Agente evaluador — UN agente para todo el radar (manual §6).
Primario: GitHub Models (GITHUB_TOKEN, permiso models:read — $0).
Fallback: Groq (secret GROQ_API_KEY, opcional — si no existe, se ignora).
Salida SIEMPRE en español, agrupada por rubro y región.
"""
import json
import logging
import os
import time

from src.fetchers.common import get

log = logging.getLogger(__name__)

GH_URL = "https://models.github.ai/inference/chat/completions"
GH_MODEL = "openai/gpt-4o-mini"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

CHUNK = 60          # ítems por llamada al LLM
SLEEP_BETWEEN = 2   # segundos entre chunks (rate limit amable)

SYSTEM = """Sos el evaluador de un radar global de investigación científica, \
patentes, salud y tecnología. Recibís ítems nuevos del día (de cualquier país \
e idioma) y los calificás. Priorizá: novedad real, impacto potencial, \
credibilidad de la fuente, interés transversal. Descartá ruido, \
reciclados de prensa y auto-promoción. Pensás en la lengua que sea, \
pero tu salida es SIEMPRE en español."""
