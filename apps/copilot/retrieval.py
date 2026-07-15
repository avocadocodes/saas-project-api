"""Turn the org's projects and tasks into labeled documents and rank them
against a question. Lexical (keyword-overlap) retrieval — transparent and
dependency-free; the small per-org corpus doesn't need vector search."""

import re

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return set(_WORD_RE.findall((text or "").lower()))


def build_documents(projects, tasks):
    """Each project/task becomes a document with a stable citation label."""
    docs = []

    for i, p in enumerate(projects, start=1):
        text = f"Project: {p.name}. Status: {p.get_status_display()}."
        if p.description:
            text += f" {p.description}"
        docs.append({
            "label": f"P{i}",
            "type": "project",
            "id": str(p.id),
            "title": p.name,
            "status": p.status,
            "text": text.strip(),
        })

    for j, t in enumerate(tasks, start=1):
        project_name = t.project.name if t.project_id else ""
        parts = [f"Task: {t.title}."]
        if project_name:
            parts.append(f"Project: {project_name}.")
        parts.append(f"Status: {t.get_status_display()}.")
        if t.assignee:
            name = f"{t.assignee.first_name} {t.assignee.last_name}".strip() or t.assignee.email
            parts.append(f"Assignee: {name}.")
        if t.due_date:
            parts.append(f"Due: {t.due_date}.")
        if t.description:
            parts.append(t.description)
        docs.append({
            "label": f"T{j}",
            "type": "task",
            "id": str(t.id),
            "title": t.title,
            "status": t.status,
            "text": " ".join(parts).strip(),
        })

    return docs


def rank(question, docs, top_k=15):
    """Return the most relevant documents. Small workspaces pass through
    whole; larger ones are ranked by keyword overlap with the question."""
    if len(docs) <= top_k:
        return docs

    q = _tokens(question)

    def score(d):
        return len(q & _tokens(d["text"]))

    ranked = sorted(docs, key=score, reverse=True)
    with_hits = [d for d in ranked if score(d) > 0]
    return (with_hits or ranked)[:top_k]
