# Running it with real data

Assumes no prior setup. About 30 minutes, most of it waiting on Google.

---

## 1. Check Python is installed

Open Terminal (Mac: Cmd+Space, type "Terminal") or PowerShell (Windows).

```bash
python3 --version
```

You want 3.10 or higher. If you get "command not found", install it from
[python.org/downloads](https://www.python.org/downloads/) and reopen Terminal.

---

## 2. Go to the project folder

```bash
cd path/to/city-launch-scout
```

Tip: type `cd ` then drag the folder onto the Terminal window — it fills in the
path for you.

Check you're in the right place:

```bash
ls
```

You should see `README.md`, `src`, `config`, and others.

---

## 3. Install the two libraries it needs

```bash
pip3 install -r requirements.txt
```

---

## 4. Confirm it works before spending any money

```bash
python3 -m src.run --mock
```

This runs on fake data with no API keys. You should see it find 14 venues, keep
9, and write three files. **If this fails, stop and fix it here** — nothing
later will work otherwise.

Open the result:

```bash
open out/shortlist.html          # Mac
start out\shortlist.html         # Windows
```

---

## 5. Get a Google Places key

This is the fiddliest step. Google requires a billing card even though there's a
generous free monthly credit — a run of 20 venues uses a tiny fraction of it.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Top-left dropdown → **New Project** → name it `venue-scout` → Create
3. Make sure the new project is selected in that same dropdown
4. Search **"Places API (New)"** in the top search bar → click it → **Enable**
   - It must be *Places API (New)*, not the older "Places API". Different key
     permissions, and the old one will fail.
5. Left menu → **APIs & Services** → **Credentials** → **+ Create Credentials**
   → **API key**
6. Copy the key somewhere safe
7. It'll ask you to set up billing if you haven't — you have to, but you won't
   be charged within the free tier

---

## 6. Get an Anthropic key

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign up
2. **Billing** → add a small amount of credit (the minimum is plenty; scoring 20
   venues costs cents, and every run prints its exact token usage)
3. **API keys** → **Create Key** → copy it

---

## 7. Put both keys in a file

```bash
cp .env.example .env
```

Open `.env` in any text editor and paste your keys in:

```
ANTHROPIC_API_KEY=sk-ant-your-actual-key-here
GOOGLE_PLACES_API_KEY=AIzaYour-actual-key-here
```

Save it. `.env` is already in `.gitignore`, so it won't end up on GitHub — keep
it that way. Anyone with these keys can spend your money.

---

## 8. Find the coordinates of your neighbourhood

1. Open [Google Maps](https://maps.google.com)
2. Find the neighbourhood you want to scout
3. **Right-click** the middle of it
4. The top of the menu shows two numbers like `38.71670, -9.15000` — click to
   copy

First number is latitude, second is longitude.

---

## 9. Run it

```bash
python3 -m src.run --city "Lisbon" --zone "Principe Real" --lat 38.7167 --lng -9.15
```

Swap in your own city, neighbourhood, and coordinates. Keep the quotes around
names with spaces.

Takes a minute or two. You'll see it count through the stages, then print where
it saved everything.

---

## 10. Look at the results

```bash
open out/shortlist.html
```

Three files are in `out/`:

- `shortlist.html` — the one to actually look at
- `shortlist.json` — the raw data
- `outreach_drafts.md` — draft emails. **Read every one before sending.**

---

## If something goes wrong

| Message | Fix |
|---|---|
| `command not found: python3` | Try `python` instead of `python3` (common on Windows) |
| `No module named requests` | You skipped step 3 |
| `Missing required environment variable` | `.env` is missing, misspelt, or not in the project folder |
| `Places search failed after 3 attempts` | Wrong API enabled (needs *Places API (New)*), or billing isn't set up |
| `401` from Anthropic | Key is wrong, or you have no credit |
| `0 passed hard filters` | Not a bug. The area genuinely has few venues above 4.3 with 150+ reviews. Lower `min_review_count` in `config/rubric.yaml` or raise `max_distance_from_zone_m` |

---

## Then: measure it

This is the part that makes it a portfolio piece rather than a demo.

1. Open `eval/labels.csv`. Delete the fake rows.
2. For each real venue the tool found, read its Google reviews yourself and
   score the five columns 0–3. Do about 20. Takes ~40 minutes.
3. Run:

```bash
python3 eval/run_eval.py --run out/shortlist.json
```

You get the percentage of the time the tool agrees with you. Compare it against
the keyword baseline in the README (53% dimension, 56% verdict) — that
difference is your headline number.
