---
name: city-launch-scout
description: Find and vet candidate restaurants for Timeleft dinners in a given city and neighbourhood, score them against the venue rubric, and draft partner outreach emails. Use this whenever someone asks about finding venues, scouting restaurants, opening or launching a new city or neighbourhood, building a venue shortlist, replacing a venue that is not working out, or checking whether a specific restaurant would suit a Timeleft table — even if they do not use the word "scout". Also use it when someone asks how a venue scored or why one was rejected.
---

# City Launch Scout

Builds a vetted, ranked shortlist of candidate venues for Timeleft dinners in a
neighbourhood, and drafts a first-contact email for each one worth approaching.

A Timeleft venue has to work for a very specific format: six strangers, one
table, roughly two hours, on a weeknight. Plenty of excellent restaurants fail
that test — a ten-seat counter, a standing wine bar, a rooftop with a DJ. This
skill exists because judging that fit by hand takes a city manager most of a
morning per neighbourhood.

## How the decision is made

Two stages, deliberately separated:

**Hard filters run in code.** Google rating, review count, price band, distance
from the zone centre, and whether the place is still open. These have right
answers, so they are never left to judgement. A venue failing any of them is
rejected before it is scored, and the rejection reason is always a specific
number.

**The rubric is scored by judgement.** Dietary range, conversation fit, group
readiness, service quality, atmosphere. Every score comes back with a
justification and the evidence behind it, because a city manager who cannot see
why a venue was rejected will not trust the shortlist.

Both live in `config/rubric.yaml`. Change thresholds there, not in the code.

## Running it

Ask the user for the city and neighbourhood if they have not said. If they name
a city but not a neighbourhood, ask which one — running a whole city at once
produces a list too long to act on and costs more than it needs to.

```bash
python -m src.run --city "Lisbon" --zone "Principe Real" --lat 38.7167 --lng -9.15
```

To demonstrate the tool without spending API credit, or when no keys are
configured:

```bash
python -m src.run --mock
```

Useful flags: `--query` to bias discovery (`"wine bar"`, `"trattoria"`),
`--max-results`, `--no-outreach` to skip email drafting, `--sender` to sign the
drafts with the right name.

## Reporting back

Point the user at `out/shortlist.html` first — it is the thing they actually
work from, and it has accept/pass buttons that export their decisions.

Then summarise in chat, briefly:
- how many venues were found, passed filters, and made the shortlist
- the top three by name with a one-line reason each
- anything flagged for manual review, and why
- any venue rejected for a reason that looks like it might be a data problem
  rather than a real failing (a missing price level, a suspiciously low review
  count for a well-known place)

Do not paste the full shortlist into chat. The HTML exists so that the chat can
stay short.

## Things to be careful about

The outreach emails are **drafts**. Never send them, never offer to send them,
and say plainly that a human should read each one first. A bad first email
burns a venue relationship permanently and there is no undo.

Scores are a starting point for a human decision, not a replacement for one.
When someone asks "is this venue good", answer with the score *and* the evidence
behind it, so they can disagree with it.

If more than a couple of venues come back flagged `review`, that usually means
the venues have thin review coverage rather than that they are bad. Say so —
the honest answer is "there was not enough to go on here", not a confident low
score.

If nothing passes the hard filters, do not quietly relax them. Tell the user
which filter is doing the damage and let them decide whether to widen the radius
or accept a lower review floor for that market. A 150-review floor is sensible
in Lisbon and much too aggressive in a city Timeleft has just opened in.
