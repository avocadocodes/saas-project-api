"""Shared client for the OpenAI-compatible chat endpoint (Groq by default)."""

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


def configured():
    return bool(
        getattr(settings, "COPILOT_LLM_API_KEY", "")
        and getattr(settings, "COPILOT_LLM_API_BASE", "")
    )


def chat(messages, temperature=0.1):
    """Return the assistant message content, or None on any failure."""
    if not configured():
        return None

    payload = json.dumps({
        "model": settings.COPILOT_MODEL,
        "messages": messages,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        f"{settings.COPILOT_LLM_API_BASE.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.COPILOT_LLM_API_KEY}",
            "User-Agent": "groundwork-copilot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError):
        return None
