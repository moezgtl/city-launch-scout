# Decisions Log

Why we built things the way we did — not just what changed (that's what
commit messages and CHANGELOG are for). Add an entry whenever a choice
was made between real alternatives, especially if a future reader might
reasonably ask "why not X instead?"

---

## 2026-07-28 — Two-model strategy: Haiku for scoring, Sonnet for outreach

**Decision:** Score venues with Claude Haiku, draft outreach emails with Claude Sonnet.

**Why:** Scoring runs once per venue (high volume, ~20/run). Haiku is 3x
cheaper than Sonnet and rubric matching against review text doesn't need
Sonnet-level reasoning. Outreach only drafts for 2-5 shortlisted venues,
where email quality matters more and the cost difference is negligible.

**Alternative considered:** Single model (Sonnet) for everything — simpler,
but ~3x more expensive for no measurable quality gain on the scoring step.

---

## 2026-07-28 — Parallelised venue scoring

**Decision:** Score all venues concurrently with ThreadPoolExecutor instead
of sequentially.

**Why:** Sequential scoring of 20 venues took ~5 minutes and exceeded
Claude Desktop's MCP timeout. Anthropic's rate limits (1000 RPM on Start
tier) are nowhere near the ~20 concurrent calls a typical run makes, so
there's no real risk in parallelising fully rather than capping workers.

---

## 2026-07-28 — Timestamped output filenames

**Decision:** Every run writes `{city}_{zone}_{timestamp}.{ext}` instead of
overwriting `shortlist.html`.

**Why:** Original version overwrote the previous run's report. Once we
started scouting multiple cities, that meant losing prior results with no
way to compare across runs or across time.

---

## 2026-08-11 — CLAUDE.md over re-explaining context each session

**Decision:** Added a CLAUDE.md at repo root documenting the pipeline, the
two entry points (CLI vs MCP server), and known gotchas.

**Why:** The `server.py` / `run.py` split caused a real bug — a cost fix
was made in one file but not the other, and it wasn't caught until a real
run. A file Claude Code reads automatically at the start of every session
reduces the chance of repeating that class of mistake.

---

<!-- Add new entries above this line, most recent first -->
