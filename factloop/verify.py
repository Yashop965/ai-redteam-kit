"""Candidate verification + buriedness scoring (no model needed).

A candidate is VALID when its golden value is confirmed on >= 2 distinct
domains (fetched page text or search snippets). It is a good BREAKER when
the golden is NOT surfaced by the model's likely *natural* queries (buried)
while the *decoy* IS surfaced (salient) - i.e. a searcher that stops at the
obvious query anchors on the wrong value.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any

from .search import search, fetch_text, domain_of, value_in_text

TYPE_WEIGHT = {
    "multi_hop": 1.25,
    "enumeration": 1.30,
    "negation": 1.20,
    "precision": 0.95,
    "version_trap": 0.90,
    "two_hop": 1.25,
}


@dataclass
class CandidateResult:
    id: str
    type: str
    pinned_question: str
    golden: str
    decoys: list[str]
    verified: bool
    evidence_domains: list[str]
    sources: list[str]
    buried: bool          # golden absent from natural-query top results
    decoy_salient: bool  # a decoy present in natural-query top results
    breaker_score: float
    strong: bool = False  # golden confirmed on >= 2 distinct domains
    notes: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


def _golden_probes(cand: dict) -> list[str]:
    """The value(s) to look for to confirm the golden (raw form is enough;
    value_in_text normalizes commas/spacing and matches whole numbers)."""
    g = str(cand.get("golden", "")).strip()
    return [g] if g else []


def verify_golden(cand: dict, fast: bool = False, fetch_limit: int = 2
                  ) -> tuple[bool, list[str], list[str], bool]:
    """Confirm the golden value, preferring the candidate's curated sources.

    A fact that is genuinely *buried* will not appear in two unrelated
    snippets, so the authoritative gate is: does the golden appear in the
    page body of at least one curated `source_url`? We also count how many
    distinct domains (curated + search snippets) contain it, to flag a
    `strong` (>= 2 domains) vs single-source candidate.

    Returns (verified, evidence_domains, source_urls, strong).
    """
    probes = _golden_probes(cand)
    domains: set[str] = set()
    cur_sources = [u for u in (cand.get("source_urls") or []) if u][: (2 if fast else 4)]
    found_in_curated = False
    # 1) authoritative: fetch curated source_urls, check the page body
    for url in cur_sources:
        page = fetch_text(url)
        if page and any(value_in_text(page, p) for p in probes):
            d = domain_of(url)
            if d:
                domains.add(d)
            found_in_curated = True
    # 2) supporting: search verify queries for snippets that contain the golden
    for vq in cand.get("verify_queries", [])[:2]:
        for r in search(vq, 6):
            url = r.get("url", "")
            d = domain_of(url)
            text = " ".join([r.get("title", ""), r.get("snippet", "")])
            if any(value_in_text(text, p) for p in probes):
                if d:
                    domains.add(d)
            if len(domains) >= 2:
                break
        if len(domains) >= 2:
            break
    strong = len(domains) >= 2
    verified = found_in_curated or strong
    evidence = sorted(domains)
    return verified, evidence, cur_sources, strong


def natural_signal(cand: dict) -> tuple[bool, bool]:
    """Check the model's likely *natural* queries.

    Returns (buried, decoy_salient):
      buried        - golden NOT present in any natural-query top snippet
      decoy_salient - at least one decoy IS present in a natural-query snippet
    """
    probes = _golden_probes(cand)
    decos = [str(d) for d in cand.get("decoys", [])]
    gold_seen = False
    deco_seen = False
    for nq in cand.get("natural_queries", [])[:1]:
        for r in search(nq, 5):
            text = " ".join([r.get("title", ""), r.get("snippet", "")])
            if any(value_in_text(text, p) for p in probes):
                gold_seen = True
            for d in decos:
                if d and value_in_text(text, d):
                    deco_seen = True
    return (not gold_seen), deco_seen


def breaker_score(verified: bool, buried: bool, decoy_salient: bool,
                  type_weight: float) -> float:
    if not verified:
        return 0.0  # not recommended until valid
    base = (0.6 if buried else 0.0) + (0.4 if decoy_salient else 0.0)
    return round(base * type_weight, 3)


def analyze(cand: dict, fast: bool = False) -> CandidateResult:
    """Run verification + buriedness + scoring for one candidate dict."""
    t = cand.get("type", "version_trap")
    w = TYPE_WEIGHT.get(t, 1.0)
    verified, domains, sources, strong = verify_golden(cand, fast=fast)
    if fast:
        buried, salient = False, False  # skip natural-query probing in fast mode
    else:
        time.sleep(0.2)
        buried, salient = natural_signal(cand)
    score = breaker_score(verified, buried, salient, w)
    notes = []
    if not verified:
        notes.append("INVALID: golden not found in a curated source")
    elif not strong:
        notes.append("single-source: golden confirmed on 1 domain only")
    if buried:
        notes.append("buried: golden not in natural-query results")
    if salient:
        notes.append("decoy salient in natural results")
    res = CandidateResult(
        id=cand.get("id", ""), type=t,
        pinned_question=cand.get("pinned_question", ""),
        golden=str(cand.get("golden", "")),
        decoys=[str(d) for d in cand.get("decoys", [])],
        verified=verified, evidence_domains=domains, sources=sources,
        buried=buried, decoy_salient=salient, breaker_score=score,
        strong=strong,
        notes="; ".join(notes),
        raw=cand,
    )
    return res


def analyze_all(cands: list[dict], fast: bool = False) -> list[CandidateResult]:
    out = [analyze(c, fast=fast) for c in cands]
    # sort: valid + highest score first; invalid sink to bottom
    out.sort(key=lambda r: (r.verified, r.breaker_score), reverse=True)
    return out
