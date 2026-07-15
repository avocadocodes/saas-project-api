"""Grounded answer generation for the workspace copilot.

Mirrors the self-verifying RAG approach: the LLM answers strictly from the
retrieved workspace context, cites the items it used, and abstains when the
answer isn't present — so it won't hallucinate about your projects/tasks.
Calls any OpenAI-compatible chat endpoint (Groq by default) via stdlib.
"""

import json
import re
import ssl
import urllib.error
import urllib.request

from django.conf import settings

try:  # use certifi's CA bundle so TLS works regardless of the host's cert store
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover - fall back to the system default
    _SSL_CONTEXT = ssl.create_default_context()

_CITE_RE = re.compile(r"\[([PT]\d+)\]")

ABSTAIN = "I don't have information about that in your workspace."

SYSTEM_PROMPT = (
    "You are the workspace copilot for a team project-management tool. "
    "Answer the user's question STRICTLY using the provided workspace context, "
    "which lists the team's projects and tasks. Each item has a label like [P1] "
    "or [T3]. Cite every item you rely on using its label in square brackets, "
    "e.g. [T3]. Be concise and specific — refer to task titles, statuses, and "
    "projects. If the context does not contain enough information to answer, "
    f'reply with EXACTLY: "{ABSTAIN}" and nothing else. '
    "Never use outside knowledge and never invent tasks, people, or dates."
)


def _configured():
    return bool(
        getattr(settings, "COPILOT_LLM_API_KEY", "")
        and getattr(settings, "COPILOT_LLM_API_BASE", "")
    )


def _unavailable(msg, grounded=False, **extra):
    return {"answer": msg, "citations": [], "grounded": grounded, **extra}


def ask(question, docs):
    if not _configured():
        return _unavailable(
            "The copilot isn't configured yet — an API key is required.",
            model=None,
        )

    context = "\n".join(f"[{d['label']}] {d['text']}" for d in docs)
    if not context:
        context = "(the workspace has no projects or tasks yet)"

    payload = json.dumps({
        "model": settings.COPILOT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Workspace context:\n{context}\n\nQuestion: {question}"},
        ],
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{settings.COPILOT_LLM_API_BASE.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.COPILOT_LLM_API_KEY}",
            # some API gateways reject the default urllib User-Agent
            "User-Agent": "groundwork-copilot/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return _unavailable(
            "The copilot is temporarily unavailable. Please try again.",
            model=settings.COPILOT_MODEL,
        )

    try:
        answer = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return _unavailable(
            "The copilot is temporarily unavailable. Please try again.",
            model=settings.COPILOT_MODEL,
        )

    abstained = ABSTAIN.lower() in answer.lower()

    by_label = {d["label"]: d for d in docs}
    citations, seen = [], set()
    for label in _CITE_RE.findall(answer):
        if label in by_label and label not in seen:
            seen.add(label)
            d = by_label[label]
            citations.append({
                "label": label,
                "type": d["type"],
                "id": d["id"],
                "title": d["title"],
                "status": d["status"],
            })

    grounded = (not abstained) and len(citations) > 0
    return {
        "answer": answer,
        "citations": citations,
        "grounded": grounded,
        "abstained": abstained,
        "model": settings.COPILOT_MODEL,
    }
