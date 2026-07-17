"""Self-verifying faithfulness check.

After the copilot drafts an answer, each sentence (claim) is checked against
the retrieved evidence by an LLM acting as an entailment judge. Claims the
evidence doesn't support are flagged - the anti-hallucination guard, carried
over from the RAG project but done without a local NLI model.
"""

import json
import re

from . import llm

_SENT_RE = re.compile(r"(?<=[.!?])\s+")

VERIFY_SYSTEM = (
    "You are a strict fact-checker. You are given EVIDENCE and a list of CLAIMS. "
    "For each claim, decide if it is directly supported by the evidence. "
    "Respond with ONLY a JSON array, one object per claim in order, like "
    '[{"supported": true}, {"supported": false}]. A claim is supported only if '
    "the evidence clearly states or implies it; otherwise it is not supported."
)


def split_claims(answer):
    return [s.strip() for s in _SENT_RE.split((answer or "").strip()) if len(s.strip()) > 3]


def verify(answer, evidence):
    """Return {claims: [{text, supported}], faithful: bool, checked: bool}."""
    claims = split_claims(answer)
    if not claims:
        return {"claims": [], "faithful": True, "checked": False}

    numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
    content = llm.chat(
        [
            {"role": "system", "content": VERIFY_SYSTEM},
            {"role": "user", "content": f"EVIDENCE:\n{evidence}\n\nCLAIMS:\n{numbered}"},
        ],
        temperature=0.0,
    )
    if not content:
        return {"claims": [{"text": c, "supported": None} for c in claims],
                "faithful": True, "checked": False}

    verdicts = _parse(content, len(claims))
    result_claims = [
        {"text": c, "supported": v} for c, v in zip(claims, verdicts)
    ]
    faithful = all(v is not False for v in verdicts)
    return {"claims": result_claims, "faithful": faithful, "checked": True}


def _parse(content, n):
    """Best-effort parse of the judge's JSON array into n booleans."""
    try:
        start = content.index("[")
        end = content.rindex("]") + 1
        arr = json.loads(content[start:end])
        verdicts = [bool(item.get("supported")) for item in arr][:n]
    except (ValueError, AttributeError, TypeError, KeyError):
        verdicts = []
    while len(verdicts) < n:
        verdicts.append(None)  # unknown if the judge under-answered
    return verdicts
