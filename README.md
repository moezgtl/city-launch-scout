# City Launch Scout

Finds and vets candidate restaurants for Timeleft dinners in a given
neighbourhood, scores them against a written rubric, and drafts a first-contact
email for each one worth approaching.

```bash
pip install -r requirements.txt
make demo     # runs offline against synthetic data, no API keys needed
make eval     # scores that run against human labels
```

---

## For the team: what this is, when it runs, who to call

**What it does.** You give it a city and a neighbourhood. It comes back with a
ranked shortlist of restaurants that would suit a Timeleft table — six strangers,
one table, two hours on a weeknight — with a reason for every score and a draft
email for the ones worth contacting.

**What it does not do.** It does not contact anybody. Every email is a draft
that a person reads and sends. It does not make the final call on a venue; it
makes the first pass so you spend your time on the ten that might work instead
of the sixty that won't.

**When it runs.** On demand, when a city or neighbourhood is being opened. It is
not scheduled — venue scouting happens in bursts, and a nightly run would just
produce noise.

**What it costs.** Roughly a cent or two of model spend and a couple of minutes
per neighbourhood, plus Google Places calls. Every run prints its own token
count and runtime.

**When it breaks.** The two likely failures are an expired Google Places key
(you'll see `Places search failed after 3 attempts`) and an empty shortlist. An
empty shortlist usually is not a bug — it means the neighbourhood genuinely has
few venues clearing a 4.3 rating with 150+ reviews in the €€–€€€ band. Widen the
radius or lower the review floor in `config/rubric.yaml` and rerun.

**Who to call.** [your name / your Slack handle]

---

## How it works

```
discover  →  hard filters  →  scoring  →  outreach drafts  →  report
(Places)     (pure Python)    (Claude)     (Claude)           (JSON + HTML)
```

The important design decision is the split between stages two and three.

**Hard filters run in code.** Rating, review count, price band, distance from
the zone centre, operational status. These have right answers. A language model
asked to apply a 4.3 threshold will mostly get it right, which is worse than
always getting it right, because the failures are invisible. And when a city
manager asks why a venue was rejected, the answer needs to be
`rating 4.1 below 4.3`, not a paragraph.

**The rubric is scored by judgement.** Whether six people can hear each other,
whether a vegetarian has a real main course, whether the room welcomes a group
who have never met. There is no threshold for these. Every score comes back with
a justification and the evidence it rests on, so a rejection can be audited in
ten seconds.

Both stages read `config/rubric.yaml`. Thresholds and weights live there so they
can be tuned without touching Python — a 150-review floor is right for Lisbon
and much too aggressive for a city that opened last month.

Rejected venues are kept and shown, never silently dropped. A tool that throws
things away without saying so is a tool nobody trusts twice.

## Outputs

| File | For |
|---|---|
| `out/shortlist.html` | The thing a city manager actually opens. Ranked cards, evidence behind every score, accept/pass buttons, exports decisions as JSON. Single file, no server. |
| `out/shortlist.json` | Feeds Sheets, Notion, or the eval harness. |
| `out/outreach_drafts.md` | Draft emails, one per shortlisted venue. Drafts only. |

## Measuring it

The scorer is judged against hand-written labels in `eval/labels.csv`:

```bash
python eval/run_eval.py --run out/shortlist.json
```

Two numbers, and they are not the same. **Dimension agreement** is how often the
scorer picks the same 0–3 as a human. **Verdict agreement** is how often it
reaches the same shortlist/backup/reject call — the one that changes what
somebody does, and the one to quote.

False shortlists are tracked separately from missed venues, because they cost
different amounts. A missed good venue costs nothing much; you had sixty
candidates. A false shortlist costs an outreach email and possibly a real dinner
in a room where six people cannot hear each other.

### Baseline

The offline stub is a keyword heuristic, not a model. It exists so the pipeline
runs with no keys, and it doubles as the baseline worth beating:

```
                    exact    ±1   mean err
ALL                   53%   89%      0.58
Verdict agreement:  5/9 = 56%
False shortlists:   2
```

Its failures are the classic bag-of-words ones and they are worth looking at
before you write your prompt:

- **Casa da Carne** — a steakhouse where the only vegetarian option is a side of
  grilled vegetables — scores 2/3 on dietary range, because the word
  "vegetarian" appears in a review complaining about the lack of it.
- **Adega Familiar** scores 0/3 on conversation fit because a review says the
  tiled room "echoes a little when full" — and the same sentence says "but never
  uncomfortable".

Both are failures of reading rather than of knowledge, which is exactly the gap
a model closes. Run the same eval live and the delta is your result.

## Live runs

```bash
cp .env.example .env    # add ANTHROPIC_API_KEY and GOOGLE_PLACES_API_KEY
python -m src.run --city "Lisbon" --zone "Principe Real" --lat 38.7167 --lng -9.15
```

Useful flags: `--query "wine bar"` to bias discovery, `--max-results`,
`--no-outreach`, `--sender "Your Name"`.

## Failure modes and what happens

| Failure | Behaviour |
|---|---|
| Places API 429 or 5xx | Three retries with backoff, then a clear error. 4xx is not retried — that's our bug, and retrying burns quota. |
| Model call fails on one venue | That venue is marked `error` and the run continues. One bad venue does not lose the other nineteen. |
| Model returns prose around its JSON | Fences stripped, outermost object extracted. |
| No evidence for a dimension | Returns `null` rather than guessing. Too many nulls and the venue is flagged `review` for a human instead of being silently scored low. |
| Missing price level | Not disqualifying. Flagged in the report rather than dropping a venue that might be perfect. |
| Nothing passes the filters | Says so, and says which filter to loosen. Never relaxes thresholds on its own. |

## As a Skill

`skill/SKILL.md` wraps the whole thing so a non-technical city manager can ask
for it in plain language — "find me venues in Príncipe Real" — rather than
running a CLI.

## Notes

All bundled data is synthetic. `data/fixtures/` was hand-written to mirror the
shape of a Places response; no real venue data, no real reviews, nothing
scraped. Live runs use the official Google Places API within its terms.

Nothing in this repo sends an email, writes to a CRM, or takes any action in the
world. It produces drafts and a shortlist, and a person decides.
