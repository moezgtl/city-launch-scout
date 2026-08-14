# CLAUDE.md

Instructions for Claude Code when working in this repository.

## What this project is

City Launch Scout finds and vets candidate restaurants for Timeleft dinners
(6 strangers, one table). It discovers venues via Google Places, filters them
deterministically in code, scores them against a rubric using an LLM, and
drafts outreach emails for the shortlist.

Built as a job-application project for an Automation Engineer role at Timeleft.
Author is a beginner programmer — explain changes plainly, avoid jargon.

## Pipeline

```
discover (Google Places)  →  hard filters (pure Python)  →  score (LLM)  →  outreach (LLM)  →  report
```

The split matters: **anything objective and checkable happens in code, not in
the LLM.** Rating thresholds, review counts, price level, distance — all in
`hard_filters.py`. The LLM only makes judgement calls that require reading
review text.

## Entry points

There are **two** code paths. Changes often need to be made in both.

| Path | File | Used by |
|---|---|---|
| CLI | `src/run.py` | `python3 -m src.run ...` in Terminal |
| MCP | `mcp_server/server.py` | Claude Desktop natural-language calls |

**This has caused real bugs.** `server.py` builds its own payload dict rather
than calling `run.py`. When adding anything to the run metadata (cost, stats,
new fields), update both or the MCP path silently omits it.

## Layout

```
config/rubric.yaml        hard filters + scored dimensions + weights + thresholds
prompts/                  editable prompt templates (venue_score.md, outreach_email.md)
src/config.py             rubric loader, .env reader
src/places.py             Venue/Zone, FixtureBackend (offline) + PlacesBackend (live)
src/hard_filters.py       deterministic filtering, keeps rejects with reasons
src/llm.py                AnthropicLLM + StubLLM, MODEL_PRICING table, Usage tracking
src/score.py              rubric scoring, verdicts, parallelised via ThreadPoolExecutor
src/outreach.py           email drafting (auto-detects local language from city)
src/report.py             payload builder + JSON/HTML/markdown writers
src/stats.py              RunStats — timings, counts, tokens, cost
src/templates/report.html the report UI (traffic-light verdicts, observability panel)
eval/                     labels.csv + run_eval.py accuracy harness
mcp_server/               MCP server + Claude Desktop setup docs
out/                      generated reports, one set per run
```

## Model strategy

- **Scoring** → Haiku (`DEFAULT_SCORING_MODEL`). Runs once per venue, high volume.
- **Outreach** → Sonnet (`DEFAULT_MODEL`). Only 2–5 emails per run, quality matters.

Costs are tracked **per model**. `MODEL_PRICING` in `llm.py` holds list prices
(verified July 2026). An unknown model falls back to Sonnet pricing and prints
a warning. Anthropic has no pricing API — this table must be updated by hand,
and the Anthropic console is the source of truth.

## Testing

**Always use mock mode during development. It is free and instant.**

```bash
python3 -m src.run --mock
```

Mock uses `StubLLM` (keyword heuristics) and a synthetic Lisbon fixture. It
validates pipeline logic, filenames, report rendering, and MCP connectivity.
It does *not* validate scoring quality or real Places results.

Only run live after a feature works in mock, and prefer `--max-results 5`
to keep costs down.

## Known limitations

- Google returns ~8 reviews per venue chosen by *its* relevance ranking, not
  ours. A venue with 700 reviews is scored on 8. Reviews are further truncated
  to 80 words each (`review_text(max_words_per_review=80)`).
- `eval/labels.csv` is synthetic. Baseline against the keyword stub was 53%
  dimension exact-match, 56% verdict agreement — those numbers mean little
  until real venues are hand-labelled.
- `places.py` uses Text Search, not Nearby Search (New). Swap is pending.
- Claude Desktop's default MCP timeout is 60s; this repo's config sets 600s.

## Conventions

- Prompts live in `prompts/*.md`, never inline in Python. Changing a prompt is
  a tracked change — say why in the commit message.
- Business logic (thresholds, weights) lives in `config/rubric.yaml`, not code.
- Reports are timestamped per run: `{city}_{zone}_{YYYYMMDD_HHMMSS}.{ext}`.
  Never overwrite previous runs.
- `.env` is gitignored and must stay that way.

## Before considering a change done

1. `python3 -m src.run --mock` passes
2. If it touches run metadata, **both** `run.py` and `server.py` are updated
3. If it touches scoring, `eval/run_eval.py` doesn't regress
4. If Claude Desktop is involved, note that a full Cmd+Q restart is required —
   the MCP server loads code once at startup

## Decisions log

`DECISIONS.md` records *why* a choice was made, not just what changed —
commit messages already cover the "what". If you make a non-trivial
implementation choice with a real alternative (a library, an architecture
change, a tradeoff between cost/speed/quality, etc.), **stop and ask the
user whether to add an entry to DECISIONS.md** before finishing the task.
Don't write the entry yourself without asking — the reasoning should be
confirmed by the user, not inferred.

## Decisions log

`DECISIONS.md` at the repo root records *why* a choice was made, not just
what changed — commit messages already cover the "what."

If you (Claude Code) make a non-trivial implementation choice with a real
alternative on the table — a library, an algorithm, a tradeoff between
cost/speed/quality, a data format — **don't write the entry yourself.**
Instead, tell the user what the choice was and why, and ask them to log it
in DECISIONS.md, or offer to draft an entry for them to review before it's
added. The reasoning usually lives in conversation, not in the diff, so a
self-written entry from git history alone tends to be thin. A short prompt
back to the user is enough:

> This involved choosing X over Y because Z — worth a DECISIONS.md entry?

Trivial changes (typos, formatting, one obvious bug fix) don't need this.
