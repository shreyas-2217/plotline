# Plotline — a story engine for CSVs

Drop a CSV. Get a scroll-driven data story where **every claim shows its receipt**.

## The idea

Dashboards are where insight goes to die. Plotline turns a tabular file into a
readable, scroll-animated narrative — built around one rule:

> **The LLM never does math.** The engine computes every number into a stats
> ledger (stable ids like `category__top`). Narrative sentences can only cite
> ids that exist in the ledger. Anything else is dropped before render.

Click any amber-highlighted sentence and a **claim receipt** slides out: the
stat id, the value, how it was computed, and a `VERIFIED — NOT LLM-GENERATED`
stamp. The final frame is always *"What this can't tell you"* — the tool ends
by stating its own limits on screen.

## What it detects

- Column types: numeric / date / categorical / identifier / mixed — pure stdlib, no pandas
- Money-like columns get priority as the story's subject
- Identifier columns (emails, phones, IDs) are **excluded from the narrative**
- Files under 20 rows get a refusal, not a story: *"12 rows isn't enough to support claims"*
- Significance is reported as an approximation (Welch t-test, normal approx)
  with sample sizes shown — never a bare claim of significance

## Stack

Python stdlib profiler + stats ledger (`server/`), Vercel Python function
(`api/story.py`), vanilla JS + hand-rolled SVG charts, IntersectionObserver
scroll reveals. Deployed on Vercel.

## Local dev

```bash
python tests/make_samples.py     # generate the sample CSVs
python tests/local_server.py     # http://localhost:8787
```

## Status

Prototype. Known limits: CSV/TSV only, up to 100k rows, no persistence —
reload and the story is gone (by design: uploaded files are never stored).
