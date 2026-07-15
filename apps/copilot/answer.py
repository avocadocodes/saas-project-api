"""Grounded answer generation over the combined workspace context
(projects, tasks, and document chunks)."""

import re

from . import llm

_CITE_RE = re.compile(r"\[([PTD]\d+)\]")

ABSTAIN = "I don't have information about that in your workspace."

SYSTEM_PROMPT = (
    "You are the workspace copilot for a team project-management tool. "
    "Answer the user's question STRICTLY using the provided workspace context, "
    "which contains projects [P#], tasks [T#], and document excerpts [D#]. "
    "Cite every item you rely on using its label in square brackets, e.g. [T3] "
    "or [D2]. Be concise and specific. If the context does not contain enough "
    f'information to answer, reply with EXACTLY: "{ABSTAIN}" and nothing else. '
    "Never use outside knowledge and never invent tasks, people, dates, or facts."
)


def build_context(candidates):
    return "\n".join(f"[{c['label']}] {c['text']}" for c in candidates)


def generate(question, context):
    """Return the raw answer text, or None if the LLM is unavailable."""
    if not llm.configured():
        return None
    ctx = context or "(the workspace has no projects, tasks, or documents yet)"
    return llm.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Workspace context:\n{ctx}\n\nQuestion: {question}"},
    ])


def extract_citations(answer, candidates):
    by_label = {c["label"]: c for c in candidates}
    citations, seen = [], set()
    for label in _CITE_RE.findall(answer or ""):
        if label in by_label and label not in seen:
            seen.add(label)
            c = by_label[label]
            citations.append({
                "label": label, "type": c["type"], "id": c["id"],
                "title": c["title"], "status": c.get("status"),
            })
    return citations


def is_abstention(answer):
    return ABSTAIN.lower() in (answer or "").lower()
