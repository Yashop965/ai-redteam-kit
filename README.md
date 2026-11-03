<div align="center">

# 🎯 factloop — AI Red-Team Kit for Web-Searching Models

**Find, verify, and score the questions that break frontier AI agents with live web access.**
Keyless, no model API required, Inspect-AI backbone, and an 830-question seed-bank recipe
(BrowseComp-Plus) that turns benchmark designers' inverse-constructed questions into your own
breaker pipeline. Battle-tested: it produced a verified confabulation failure in a
search-enabled frontier model.

`keyless search` `zero model keys` `Inspect AI` `8 hand-mined candidates` `830-question seed bank recipe`

![python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![inspect-ai](https://img.shields.io/badge/Inspect-AI-0.3%2B-24292F?labelColor=0a0a0a)
![keyless](https://img.shields.io/badge/search-keyless-FF4D4D)
![license](https://img.shields.io/badge/license-MIT-2EA043)

</div>

---

## 📦 What is this?

A complete **factuality red-teaming pipeline** for breaking models that browse the web
(Google AI Search Mode, Perplexity, Gemini Deep Research, agent harnesses, ...).

The hard part of any "make the model fail" evaluation is not writing a hard question — it is
producing a question where:

- the model **demonstrably fails** on its first response (screenshot-able),
- the golden answer is **verifiable from ≥ 2 clean text sources** (no paywalls, no JS-only
  pages, no ambiguity, timeless),
- and the failure is a **content failure** (wrong fact or confabulation), not a format refusal.

factloop generates and validates exactly that: it mines candidate questions, auto-verifies the
golden against real web pages, ranks them by how *buried* they are, and emits **paste-ready
form blocks** (prompt + golden + decoys + 2-source citations + justification). The one manual
step — typing the prompt into the model and judging the response — stays a human. Everything
around it is automated.

| Path | What it is |
|---|---|
| `factloop/` | The pipeline: keyless search layer, verification, scoring, form-block renderer, Inspect-AI task wiring |
| `cli.py` | Three commands: `author` (verify + rank + emit), `grade` (score a pasted model answer), `run` (optional model agent) |
| `candidates.json` | 8 hand-mined trap candidates (kept as reference; most are now *known-cleared* by a searcher — see field notes) |
| `scripts/mine_bcp.py` | One-shot fetch + decrypt of the 830-question BrowseComp-Plus seed bank + the form-constraint miner |
| `data/README.md` | Seed-bank provenance, credits, and the "keep it decrypted locally" policy |

Generated artifacts (`out/results.json`, `out/form_blocks.md`) land in your working dir and
are gitignored.

---

## 🚀 Quickstart

```bash
pip install -r requirements.txt          # inspect-ai, ddgs, requests
pip install pyarrow                      # only if you regenerate the seed bank

# 1) verify + rank all candidates, write out/results.json + out/form_blocks.md
python cli.py author --limit 5

# 2) iterate fast on a few ids (snippet-only; skips natural-query probing)
python cli.py author --only some_id,other_id --fast

# 3) regenerate the 830-question seed bank locally (decrypted, gitignored)
python scripts/mine_bcp.py

# 4) you pasted the model's answer from your manual test? grade it:
python cli.py grade --id some_id --answer "whatever the model actually said"
# -> verdict + prints a SUBMISSION FORM BLOCK to copy into your evaluation form
```

No search API key, no model API key. Web access is keyless via `ddgs` (maintained
DuckDuckGo client) with DDG-HTML and SearXNG fallbacks.

---

## ⚙️ How the pipeline works

```
                 ┌─────────────────────────────────────────────────────────────┐
                 │                     cli.py author                           │
                 └──────────────┬──────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────────────┐
        ▼                       ▼                               ▼
┌────────────────┐   ┌──────────────────┐   ┌──────────────────────────────┐
│ 1 SEARCH LAYER  │   │ 2 VERIFY LAYER   │   │ 3 SCORE + RANK              │
│ ddgs (retried) │──▶│ fetch curated    │──▶│ buried? × decoy-salient?    │
│ → DDG-HTML     │   │ source_urls,     │   │ × question-type weight      │
│ → SearXNG      │   │ confirm golden   │   │                            │
│ cached+throttled│   │ in PAGE BODY     │   │ breaker_score =            │
│                │   │ (not snippets!)  │   │ (0.6·buried + 0.4·decoy)·w │
└────────────────┘   └──────────────────┘   └──────────────┬──────────────┘
                                                           ▼
                    ┌──────────────────────────────────────────────────────┐
                    │ 4 FORM-BLOCK EMITTER  →  out/form_blocks.md           │
                    │ prompt + golden + decoys + 2-source URLs +            │
                    │ paste-ready justification → you test it manually,     │
                    │ then 5) grade: boundary-aware match → submission     │
                    └──────────────────────────────────────────────────────┘
```

**Layer 1 — keyless search.** `search()` tries `ddgs` first (3 retries, backoff), then the
DuckDuckGo HTML endpoint, then two SearXNG instances (short timeout, last resort). All results
are cached per-query and throttled to 1.5 s apart so you don't get soft-blocked.

**Layer 2 — verification (the part most tools get wrong).** Buried values live in *page
bodies* — census tables, demographics sections — not in search snippets. So verification
fetches each candidate's curated `source_urls` and checks the golden in the rendered text.
`verified` = golden found in ≥ 1 curated source **or** on ≥ 2 distinct domains;
`strong` = ≥ 2 domains (your "2 sources" gate for a form submission).

**Layer 3 — buriedness scoring.** We replay the queries a model would *naturally* run for the
question. If the golden is absent from those top results while a decoy is present, the
candidate scores high. Question **type** is weighted: exhaustive enumeration ×1.30,
multi-hop / two-hop ×1.25, negation ×1.20, precision ×0.95, version traps ×0.90 — the weights
encode measured behavior: searchers clear version traps, they *confabulate* on completeness
questions.

**Layer 4/5 — grading.** `grade` is fully offline: boundary-aware matching of the golden in
the pasted model answer, verdict, plus a ready-to-paste form block. `run` (optional) wraps the
candidates in an **Inspect AI** task — `MemoryDataset` of samples, a `general` agent with
`web_search` / `read_url` tools, and a type-aware scorer — for when you *do* have a model
endpoint.

**The subtle bug that matters** (fix lives in `factloop/search.py::value_in_text`): numeric
matching must strip *commas only, never spaces*. Stripping spaces fuses adjacent table cells
(`"1860 771"` → `"1860771"`) and silently rejects the exact buried values you are trying to
find. Whole digit-run comparison, thousands separators normalized, done.

---

## 🧪 Field notes: what actually breaks web-searching models

A condensed account of the search campaign this kit came out of (10+ candidate classes,
50+ questions, one search-enabled frontier model tested manually).

| Move | Class | Outcome |
|---|---|---|
| "How many X in year Y" pinned to an old version (Geneva 1949 → 18; UN 1945 → 51; US states 1900 → 45, 1800 → 16; 1789 amendments → 12; Wright patent → 821,393; 1810 census → 7,239,881) | buried exact values | ❌ **all cleared** — the searcher runs a targeted follow-up and retrieves even a 7-digit buried census total |
| "First independent sovereign state to give women vote + stand" | scope trap | ❌ disqualified: two defensible answers (Australia 1902 vs Finland 1906) → ambiguity gate |
| "How many US presidents died in office?" (= 8) | buried enumeration | ❌ cleared: it has a dedicated Wikipedia list page |
| "Population of Edison's birthplace village (Milan, OH) in the 1860 census" (= 771) | buried multi-hop | ❌ cleared: the searcher follows the village to the census table |
| **Multi-constraint reverse-lookup** (BrowseComp style): 4 scattered clues → one obscure proper noun | **confabulation** | ✅ **BREAKS it.** Clues resolve to a mountaineer (accident: National Geographic's *Torn*; "favorite color turquoise": one magazine interview; "first watch": one watch-blog retrospective). The search-enabled model answered with a *plausible celebrity + a fabricated watch + an invented plane crash*. Golden: a specific 1970s calculator watch, provable from the cited pages. |

**The turning point:** after 10 consecutive searcher successes, stop inventing facts by hand
and **steal from the benchmark designers**. BrowseComp-style questions are built by inverting
a verified fact until even GPT-4o *with browsing* fails it — exactly the failure distribution
you want for a manual test. BrowseComp-Plus (830 questions, human-verified evidence docs) is
that feed; `scripts/mine_bcp.py` fetches + decrypts it locally.

---

## 🧠 The cheat sheet (what to learn from all of this)

1. **For a web-searching model, "buried" ≠ "safe".** If a value is *indexable*, the searcher
   will follow a targeted second query and find it — including exact 7-digit census totals and
   patent numbers. Buriedness is a property of your *assumption*, not the fact.
2. **What actually breaks searchers is scattering, not depth.** A fact that resolves through
   ≥ 3 sources that never cross-reference each other has no triangulation path for a search
   loop. That is the BrowseComp construction: *hard to find, easy to verify*.
3. **Classify the failure before you submit.** Retrieval gap (model couldn't find it) vs
   confabulation (model found nothing and *invented* a confident answer) vs ambiguity
   (question has two defensible answers → a form will reject it). Confabulation is the most
   impressive to show: a wrong person plus an invented accident.
4. **Completeness beats trivia.** Enumerations ("list all X") only break a searcher when the
   set has *no* well-indexed list. "Presidents who died in office" has a Wikipedia page →
   cleared. "Watch tied to an accident survivor's memory-collecting habit" → fails.
5. **Two-source discipline is about independence, not count.** Two reposts of the same blog
   post are one source. Different institutions (watch blog + climbing magazine + National
   Geographic) are three. Verify the golden in the **page body**, not the snippet — tables and
   demographics sections don't show up in search previews.
6. **Timelessness + single-answer are hard gates.** Anything with "as of 2026", "currently",
   or two plausible readings (suffrage scope; treaty signature counts that conflict across
   ICRC/UN/Wikipedia) is dead on arrival for a form.
7. **Match numbers like a boundary-aware human.** `45` must not match inside `145`;
   `7,239,881` must equal `7239881`; and `"1860 771"` must not become `"1860771"`.
   Commas are thousands separators; spaces are cell separators.
8. **Keyless web access is enough for eval loops.** `ddgs` + HTML fallback + cache +
   1.5 s throttle survives a full multi-candidate verification run. You do not need an API key
   to build the verification half of a red-team loop.
9. **Evaluation integrity is a real threat vector.** Anthropic's BrowseComp runs showed a
   model that recognized the exam, found the answer file on GitHub, and decrypted it — which
   is why BrowseComp-Plus XOR-obfuscates its text behind a public canary. If you build grading
   tasks, assume the model can search for the grader.
10. **Never grade from memory; grade from the trace.** `grade` accepts only the model's
    *actual* pasted output plus the golden you verified against real pages. The screenshot of
    the full exchange is the evidence; the form field is its transcript.

---

## 🗄️ Data & credits

- **Seed bank (not committed):** `scripts/mine_bcp.py` downloads the 4 obfuscated parquet
  files of **Tevatron/browsecomp-plus** (ACL 2026, derived from **OpenAI BrowseComp**) and
  decrypts them with the dataset's *public* canary (same mechanism as the upstream repo's
  `decrypt_dataset.py`). Output: 830 queries + answers + human-verified evidence/gold docs.
  Decrypted files are gitignored on purpose — upstream protects them against answer scraping,
  so this repo ships the *recipe*, not the data.
- **Hand-mined traps:** the 8 reference candidates in `candidates.json` (most known-cleared
  by a searcher; kept as a scoring reference and schema demo).
- **Sibling datasets if you want more:** OpenAI **BrowseComp** (`openai/simple-evals`),
  **LiveBrowseComp** (recent long-tail facts), **MedBrowseComp** (medical, computer-use),
  Google DeepMind **DeepSearchQA**.

> [!NOTE]
> This kit is for *defensive* evaluation work: assessing models you are authorized to test
> (benchmarks, your own deployments, evaluation programs you agreed to). Do not feed
> benchmark answers back into production systems, and do not use it to game a specific live
> leaderboard.

---

## 📄 License

MIT. Benchmark datasets are credited to their original authors (OpenAI, Tevatron) and retain
their respective terms for their content.
