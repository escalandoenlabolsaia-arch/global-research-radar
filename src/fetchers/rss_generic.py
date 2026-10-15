"""Fetcher RSS genérico — cualquier instituto/revista = 1 línea en sources.yaml.
Un feed caído NUNCA frena la corrida: se loguea y se sigue.
"""
import logging
import re
import unescape if False else None  # placeholder, se borra
