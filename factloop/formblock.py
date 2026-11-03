"""Render paste-ready assessment form blocks from a candidate + result."""
from __future__ import annotations

from .verify import CandidateResult


def _golden_line(res: CandidateResult, cand: dict) -> str:
    g = res.golden
    items = cand.get("golden_items")
    if items:
        return g + " -> " + "; ".join(items)
    return g


def _wrong_lines(res: CandidateResult) -> str:
    d = res.decoys
    if not d:
        return "(no decoy listed)"
    return " / ".join(d)


def form_block(res: CandidateResult) -> str:
    """Return the full paste-ready block for one candidate.

    Uses raw candidate fields (sources, justification, golden_items) via
    res.raw, plus computed evidence from res.
    """
    c = res.raw
    golden = _golden_line(res, c)
    just = c.get("justification") or (
        f"The golden answer is {res.golden}. "
        + ("Confirmed on " + ", ".join(res.evidence_domains) + "." if res.evidence_domains else "")
    )
    srcs = c.get("source_urls") or res.sources or []
    block = f"""## {res.id} ({res.type})

**Prompt to type verbatim:**
```
{res.pinned_question}
```
**Golden answer:** {golden}
**Likely wrong (decoys):** {_wrong_lines(res)}

**Source URLs:**
```
{chr(10).join(srcs) if srcs else "(see justification)"}
```

**Justification (paste-ready):**
```
{just}
"""
    if res.evidence_domains:
        block += f"\n**Verified on:** {', '.join(res.evidence_domains)}\n"
    block += "```\n"
    return block


def ranked_markdown(results: list[CandidateResult]) -> str:
    """Full report: ranked table + form blocks for the valid top candidates."""
    lines = ["# factloop ranked candidates\n",
             "| rank | id | type | golden | verified | strong | buried | decoy? | score |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {r.id} | {r.type} | {r.golden} | {r.verified} "
            f"| {r.strong} | {r.buried} | {r.decoy_salient} | {r.breaker_score} |")
    lines.append("\n---\n\n## Form blocks (valid candidates, best first)\n")
    valid = [r for r in results if r.verified]
    for r in valid:
        lines.append(form_block(r) + "\n")
    if not valid:
        lines.append("(no candidates verified yet - widen verify_queries/sources)\n")
    return "\n".join(lines)
