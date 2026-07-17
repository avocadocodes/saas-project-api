"""Retrieval for the copilot.

Two sources, combined (hybrid):
  - projects & tasks  -> lexical (keyword) ranking over structured records
  - document chunks   -> vector (cosine) ranking over Gemini embeddings

The per-org corpus is small, so cosine is computed in Python - no vector
extension required, and it runs identically on SQLite and Postgres.
"""

import math
import re

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return set(_WORD_RE.findall((text or "").lower()))


# ── projects & tasks (lexical) ───────────────────────────────────────────────

def build_documents(projects, tasks):
    docs = []
    for i, p in enumerate(projects, start=1):
        text = f"Project: {p.name}. Status: {p.get_status_display()}."
        if p.description:
            text += f" {p.description}"
        docs.append({
            "label": f"P{i}", "type": "project", "id": str(p.id),
            "title": p.name, "status": p.status, "text": text.strip(),
        })
    for j, t in enumerate(tasks, start=1):
        parts = [f"Task: {t.title}."]
        if t.project_id:
            parts.append(f"Project: {t.project.name}.")
        parts.append(f"Status: {t.get_status_display()}.")
        if t.assignee:
            name = f"{t.assignee.first_name} {t.assignee.last_name}".strip() or t.assignee.email
            parts.append(f"Assignee: {name}.")
        if t.due_date:
            parts.append(f"Due: {t.due_date}.")
        if t.description:
            parts.append(t.description)
        docs.append({
            "label": f"T{j}", "type": "task", "id": str(t.id),
            "title": t.title, "status": t.status, "text": " ".join(parts).strip(),
        })
    return docs


def rank_lexical(question, docs, top_k):
    if len(docs) <= top_k:
        return docs
    q = _tokens(question)
    ranked = sorted(docs, key=lambda d: len(q & _tokens(d["text"])), reverse=True)
    with_hits = [d for d in ranked if q & _tokens(d["text"])]
    return (with_hits or ranked)[:top_k]


# ── document chunks (vector) ─────────────────────────────────────────────────

def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def rank_chunks(question_vector, chunks, top_k, min_score=0.30):
    """chunks: iterable of DocumentChunk. Returns labeled doc candidates."""
    if not question_vector:
        return []
    scored = []
    for c in chunks:
        score = cosine(question_vector, c.embedding)
        if score >= min_score:
            scored.append((score, c))
    scored.sort(key=lambda s: s[0], reverse=True)
    out = []
    for n, (score, c) in enumerate(scored[:top_k], start=1):
        out.append({
            "label": f"D{n}", "type": "document", "id": str(c.document_id),
            "title": c.document.title, "status": None, "text": c.text,
            "score": round(score, 3),
        })
    return out
