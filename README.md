# City Launch Scout

Automated venue scouting and vetting for Timeleft's city launches — built as an
application project for the Automation Engineer role.

**See a sample report:** [docs/sample_report.html](docs/sample_report.html) —
generated from synthetic Lisbon data in mock mode (no real venues, no API
calls). Download it and open it in a browser.

## The problem

When Timeleft opens a new city, someone has to find restaurants that work for
six strangers sharing a table for two hours: a room quiet enough to hear each
other, a menu with a real vegetarian option, a layout that can seat a group
who've never met. Doing that by hand means reading through dozens of Google
listings and reviews per neighbourhood — most of which won't qualify.

City Launch Scout automates the first pass. Give it a city and a
neighbourhood; it comes back with a ranked, evidence-backed shortlist and a
draft outreach email for each venue worth contacting. It doesn't decide and it
doesn't send anything — it turns sixty candidates into ten a human actually
needs to look at.

## How it works

```
discover  →  hard filters  →  score  →  outreach drafts  →  report
(Places)     (pure Python)    (LLM)      (LLM)              (JSON + HTML)
```

1. **Discover** — pull candidate venues from Google Places for the target zone.
2. **Hard filters** — reject on rating, review count, price band, distance,
   operational status. Deterministic, in code, no LLM involved.
3. **Score** — an LLM reads review text and scores the things that need
   judgement: conversation fit, dietary range, group-friendliness. Every score
   comes with a justification.
4. **Outreach** — draft a first-contact email for each shortlisted venue.
5. **Report** — a self-contained HTML file, JSON, and markdown, all timestamped
   per run.

## Key engineering decisions

**Deterministic filters, judgement-based scoring.** Anything with a right
answer — a 4.3 rating threshold, a review-count floor — runs in plain Python,
not an LLM. A model asked to apply a threshold will *mostly* get it right,
which is worse than reliably right, because the failures are invisible and
unauditable. The LLM is reserved for calls that genuinely require reading
review text, where there's no clean numeric threshold to write.

**Two-model cost strategy.** Scoring runs once per venue (high volume, lower
stakes per call) and uses Haiku. Outreach only runs for the 2–5 shortlisted
venues per run, where quality matters more than cost, and uses Sonnet. Cost is
tracked per model and surfaced in every run's summary — not a single blended
estimate.

**Parallelised scoring.** Venues are scored concurrently via a thread pool
rather than sequentially, so a run of 20 venues doesn't take 20x as long as a
run of one.

**Observability by default.** Every run tracks timings per stage, token usage,
API call counts, and cost — printed to the terminal and embedded in the HTML
report. Rejected venues are kept and shown with their rejection reason, never
silently dropped, so a city manager (or a reviewer of this project) can audit
any decision in seconds rather than trusting a black box.

## Quickstart

```bash
pip install -r requirements.txt
python3 -m src.run --mock     # offline demo against synthetic data, no API keys needed
```

Opens a full shortlist report (`out/*.html`) with fake data in seconds. For a
real run against live Google Places and Anthropic APIs — getting API keys,
finding coordinates, everything — see **[SETUP.md](SETUP.md)**.

## Outputs

| File | For |
|---|---|
| `out/*.html` | Ranked shortlist, evidence behind every score. Single file, no server. |
| `out/*.json` | Feeds Sheets, Notion, or the eval harness. |
| `out/*.md` | Draft outreach emails, one per shortlisted venue — drafts only, never sent automatically. |

## Technical details

<details>
<summary>Rubric-driven config, failure handling, and evaluation</summary>

**Config, not code.** Both filter thresholds and scoring dimensions/weights
live in `config/rubric.yaml`, tunable without touching Python — a 150-review
floor that's right for Lisbon is too aggressive for a city that opened last
month.

**Failure handling**

| Failure | Behaviour |
|---|---|
| Places API 429/5xx | Three retries with backoff, then a clear error. 4xx is not retried. |
| Model call fails on one venue | Marked `error`, run continues — one bad venue doesn't lose the rest. |
| Model returns prose around its JSON | Fences stripped, outermost object extracted. |
| No evidence for a dimension | Returns `null` rather than guessing; too many nulls flags the venue `review` instead of scoring it low. |
| Nothing passes the filters | Says so, and says which filter to loosen. Never relaxes thresholds on its own. |

**Measuring accuracy.** The scorer is judged against hand-written labels in
`eval/labels.csv`:

```bash
python eval/run_eval.py --run out/shortlist.json
```

Reports dimension agreement (does it pick the same 0–3 as a human) and verdict
agreement (does it reach the same shortlist/backup/reject call) separately —
verdict agreement is the number that changes what someone does.

**As a Skill.** `skill/SKILL.md` wraps the whole pipeline so a non-technical
city manager can ask for it in plain language via Claude Desktop, rather than
running a CLI.

**Data.** All bundled fixture data is synthetic — no real venue data, no
scraped reviews. Live runs use the official Google Places API within its
terms. Nothing in this repo sends an email, writes to a CRM, or takes any
action in the world; it produces drafts and a shortlist, and a person decides.

</details>

## Known limitations

- Google returns ~8 reviews per venue, chosen by *its* relevance ranking, not
  ours — a venue with 700 reviews is scored on 8. Reviews are further
  truncated to 80 words each.
- `eval/labels.csv` is synthetic. The baseline against the keyword stub was
  53% dimension exact-match, 56% verdict agreement — those numbers mean little
  until real venues are hand-labelled.
- `places.py` uses Text Search, not the newer Nearby Search (New). Swap is
  pending.
- Claude Desktop's default MCP timeout is 60s; this repo's config sets it to
  600s to accommodate a full scouting run.
