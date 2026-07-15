"""Gemini text embeddings via the REST API (stdlib only, certifi for TLS)."""

import json
import ssl
import urllib.error
import urllib.request

from django.conf import settings

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover
    _SSL_CONTEXT = ssl.create_default_context()


def embeddings_configured():
    return bool(getattr(settings, "GEMINI_API_KEY", ""))


def embed_text(text):
    """Return the embedding vector for a single string, or None on failure."""
    if not embeddings_configured() or not text:
        return None

    url = (
        f"{settings.GEMINI_API_BASE.rstrip('/')}/models/"
        f"{settings.GEMINI_EMBED_MODEL}:embedContent?key={settings.GEMINI_API_KEY}"
    )
    payload = json.dumps({
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": settings.GEMINI_EMBED_DIM,
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "groundwork-copilot/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
        return data["embedding"]["values"]
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return None


def embed_texts(texts):
    """Embed a list of strings; returns a list of vectors (None where it failed)."""
    return [embed_text(t) for t in texts]
