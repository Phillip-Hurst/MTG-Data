---
name: mtg-tournament-analysis
description: Analyze Magic: The Gathering Standard tournament results from melee.gg, mtgtop8.com, magic.gg, MTGGoldfish, and MTGO (Challenges and 5-0 league dumps). Use this skill whenever the user asks about the current MTG meta, what decks are winning, trending cards, interesting sideboard tech, melee.gg results, MTGO results, Challenge results, 5-0 decks, tournament standings, deck recommendations, what to play at an upcoming event, matchup data, or competitive MTG analysis of any kind. Trigger even for casual phrasing like "what's good in Standard right now", "what's winning on melee this week", "any interesting 5-0s lately", or "anything interesting happening in the meta."
---

# MTG Tournament Analysis

## Related skills in this plugin

| Skill | What it's for | Hand off when |
|---|---|---|
| `deck-check` | Assigns the right archetype to mislabeled or uncategorized decks, and pushes that label into the win-rate and matchup data | A deck is under the wrong name, an unnamed shell from `card_signal.py` needs naming, or the user wants to clear the mislabel queue |
| `vod-review` | Reviews the user's own games from an untapped.gg replay, a YouTube VOD, or a pasted log, and finds the decisions that decided them | The question moves from "what's good" to "how did I play it". Field data says a deck wins 55%; only a review says why this pilot didn't |
| `rules-check` | Quotes the Comprehensive Rules. Priority, the stack, triggers, state-based actions, layers | An interaction needs a ruling. Never resolve one from memory inside an analysis write-up |

`mtg-price-check` prices a Moxfield binder against Face to Face Games. It is a separate skill and does not ship in this plugin, so point the user at it by name rather than assuming it is installed.

**This skill does not categorize decks.** When the classifier can't name a deck,
report the cards that are performing in it and stop. Naming it is `deck-check`'s
job, and it's the only thing that turns those cards into an archetype with a win
rate. Say the skill's name and hand over; never reimplement it here.

**Check the pool before quoting a number.** `event_quarantine_<fmt>.json` must
exist, match the current era, and postdate the last scrape. If it doesn't, say so
and point at `validate_events.py` rather than reporting the number as fact. On
2026-08-27 an unvalidated pool produced a snapshot reporting Izzet Prowess at 6.8%
of a "post-ban" metagame, 17 days after it was banned out of the format. Nothing
errored.

---

## Card-level signal

Step 3.5 below covers how to *write* about a card once you've found it. `card_signal.py` is how you find it. Run it before writing the "Cards to watch" section — that section should come out of this, not out of impressions.

```bash
python card_signal.py                       # all four lenses, current era
python card_signal.py --lens rogue          # just the deckbuilding shortlist
python card_signal.py --archetype "Mono-Green"   # deviations in one deck
python card_signal.py --write               # save a note
```

**rogue** — under 8% of the field is on the card, and the pilots who are finish above average. This is the deckbuilding shortlist: slots you could change tomorrow. Each row names where the card lives, so a rogue inclusion in a known archetype and one in an unnamed shell both surface.

**deviation** — cards in an archetype's lists that aren't in its goto build, ranked by how much better those pilots finished than the rest of the archetype. This is the caster's read made countable: *"we don't see Slickshot Show-Off from Tony's build."* A card filling a flex slot isn't signal; a card several pilots independently reach for, who then beat their own archetype's average, is.

**trend** — adoption moving across the window. A block of cards moving together is one deck moving, not eight discoveries; the outlier moving the other way is usually the better line.

**unnamed** — shells the classifier can't name, grouped by co-occurrence, each a real deck with a real record and no label. Report them as exactly that and hand them to `deck-check`. Don't invent a name here.

Rows marked `*` rest on fewer than 4 pilots. Say so in the write-up rather than
presenting them as settled — a lead to check, not a conclusion. Verify every card
on Scryfall before writing it up (Step 0 hard rule).

If more than about a third of the field is unnamed, say so. That means the
references predate the era, not that the format is unusually brewy.

---

Fetch real tournament data since the current format era started. Track two kinds of shift: how the meta is maturing within the era (intra-era drift), and how this era compares to the one before it (cross-era shift). Surface both, and present matchup data clearly.

The user plays the game. Get to the data.

---

## Format eras: the thing that makes old data lie

An era is the stretch of time over which results are comparable. Two things end one:

1. **A set release.** New cards, new format.
2. **A banned and restricted announcement.** The top of the metagame gets deleted. Every matchup number that involved the banned deck is now describing a deck that can't be registered.

A ban is the more dangerous of the two, because nothing about the data looks different afterward. The CSVs keep the same filenames, the archetype names stay spelled the same way, and a 62% win rate against Izzet Prowess still reads like a fact. It isn't one, if Izzet Prowess lost its keystone card on Monday.

**Run this before any analysis:**

```
python mtg_era.py
```

It prints the current era, the date it started, why it started there, and what the previous era was. The window start comes from whichever is later: the newest set release in `set_releases.json`, or the newest B&R announcement for this format in `bans.json`. `mtg_fetch.py` and `build_baseline.py` both anchor on it.

**Current Standard era: post-ban, 2026-08-10 onward.** Badgermole Cub, Stormchaser's Talent, and Gran-Gran are banned. Selesnya Offense, Izzet Prowess, and Jeskai Lessons are the decks that lost a card. Anything from before that date is a different format.

### When a ban lands

1. Add the announcement to `bans.json` (effective date, format, cards, decks hit, the WotC URL).
2. `python archive_era.py --dry-run`, then `python archive_era.py`. That moves every scraped CSV, the MTGO dumps, and the closing era's baseline into `archive/through-YYYY-MM-DD/` with a manifest. The analysis scripts glob the data folder non-recursively, so this is what actually takes the old data out of the live pool.
3. `python mtg_fetch.py`. The window now opens at the ban date, so the new scrape only pulls post-ban events.
4. Freeze the archetype files: rename the live `## Matchup data` heading to `## Matchup data (pre-ban, through YYYY-MM-DD)` and add a ban banner to every deck that ran a banned card. Don't delete anything.

### Reading data from the archive

The frozen files stay readable. Use them for cross-era comparison and for questions about how the format used to look. Never merge them into live win-rate or matchup numbers, and always label them with the era they came from. `archive/*/manifest.json` carries the era label, the closing date, the ban, and the row counts.

### The first weeks of a new era

Post-ban data is thin by definition. Say so. One weekend of MTGO Challenges after a ban is a real signal about what people are trying, and a weak signal about what's good. The honest framing is "here's what showed up, here's how little of it there is," not a tier list built on 40 matches.

Until there are enough post-ban events to stand on their own, lean on three things and label each one: the ban announcement's own reasoning (WotC publishes what they think the format looked like), mtgtop8's live meta share, and pre-ban data for the archetypes that *didn't* lose a card, flagged as pre-ban.

---

## This is a local-first tool: where the data comes from

The cleanest, most complete data comes from the local scrapers running on the user's own machine. `setup.py` sets that up, and `scrape.bat` / `scrape.sh` pull melee + MTGO into a per-format folder. Cowork reads what they produce. Prefer local data whenever it's present and fresh.

What you can fetch live in a Cowork session, with no local data:

- **mtgtop8 (reliable, server-rendered).** Fetch `https://www.mtgtop8.com/format?f=ST` for archetype meta share and the "decks to beat," then `https://www.mtgtop8.com/archetype?a=ID&f=ST` and `https://www.mtgtop8.com/mtgo?d=DECKID` for representative lists. This is the cold-start engine, and the source `setup.py` seeds the baseline from. mtgtop8 files several builds under one umbrella ("Izzet Control"); the deck-level label ("Izzet Lesson", "Izzet Spellementals") is the granularity that matches the archetype files, so read the deck labels, not just the umbrella.
- **MTGO and magic.gg are JavaScript-rendered.** A plain fetch of an mtgo.com decklist or a magic.gg results page returns a loading shell, not the cards. Don't present that shell as data. Card-level MTGO data comes from the local `fetch_mtgo.py` scrape. If you must read one of these pages live, use the browser tools that render JavaScript (Claude in Chrome), not a plain fetch.
- **melee.gg** round data (the matchup matrix and head-to-head win rates) is JavaScript-rendered and the API is OAuth-gated. It comes only from the local melee scrape.

So if a user asks for a matchup matrix and there's no local data, don't fake it. Say matchup data comes from a local melee scrape, point them at `setup.py` (it builds the folders and a one-click `scrape.bat` / `scrape.sh`), and meanwhile give the live read from mtgtop8. A partial but accurate answer beats a dead end.

A fresh install isn't empty. `setup.py` step 6 seeds `archetype_refs.json` and an mtgtop8 meta-share snapshot per format. Read the snapshot at `baselines/meta_baseline_mtgtop8_<format>.json` for the starting archetype list and share, and label it as an mtgtop8 baseline with its fetch date, not as the user's own scraped data.

Local data lives wherever `setup.py` put it — read `mtg_workspace.json` at the workspace root for the per-format `scrapes` and `insights` paths. If the user hasn't run setup, the scripts fall back to reading and writing next to themselves.

---

## Step 0: Establish the current Standard card pool

Fetch `https://magic.wizards.com/en/formats/standard` first, every time.

Note which sets are currently legal, the release date of the most recent set, and anything listed as "Coming Soon" (not yet legal). Every card reference in the analysis must come from a currently legal set. If a card is from a set outside your training coverage, say so — don't guess.

**Then check the ban list.** Fetch `https://magic.wizards.com/en/banned-restricted-list` and compare it against `bans.json`. A legal set is not the same thing as a legal card, and this is the failure mode that produces confident, useless advice: recommending a deck built around a card that got banned. If the live list has a change `bans.json` doesn't, add it before going any further — the window start and the whole data split depend on that file being current.

**Never recommend a banned card.** Currently banned in Standard as of 2026-08-10: Badgermole Cub, Stormchaser's Talent, Gran-Gran. If a decklist in the data or in a vault note runs one of those, that list is a historical artifact. Say so.

### Hard rule: verify every card before recommending around it

This applies to **every card** referenced in a recommendation, not just unfamiliar ones. Cards you "know" from prior coverage, vault notes, or training data are the most dangerous — confident-sounding wrong information is worse than asking. Verify before you write.

**What to verify on Scryfall before mentioning a card in any recommendation:**
- Mana cost (full pip breakdown, not just CMC)
- Card type (instant vs sorcery vs enchantment vs permanent — Great Hall, Tablet, etc. only help cast instants/sorceries)
- Oracle text — the actual effect, not your memory of it
- Power/toughness for creatures (especially landfall creatures whose counters change the math)
- Colors of the card (a card you think is Izzet may be Selesnya, breaking the whole archetype claim)

**Verification pattern:**

1. Search: `"Card Name" MTG scryfall oracle text [set code]`
2. Or fetch directly: `https://scryfall.com/card/[set]/[number]/[card-name]`
3. Or `https://scryfall.com/search?q=!"Card Name"&unique=cards`

If WebFetch returns empty (some Scryfall pages render client-side), WebSearch with the query pattern above usually surfaces the oracle text in the result snippet.

**When verification matters most** — re-verify, don't trust memory:

- Building a sideboard plan that names specific opposing cards as targets ("Disdainful Stroke for Mossborn Hydra" requires verifying Mossborn Hydra's actual CMC)
- Running a Karsten manabase check (every spell's exact pip count drives the threshold)
- Recommending a card swap (need to know both cards' costs and what they answer)
- Quoting a card's effect to justify a play pattern ("X bounces Y" — verify X is a bounce spell)
- Describing what a card does in an archetype write-up

**The "I don't have it" fallback:**

If you can't reach Scryfall for any reason, say: "I haven't verified [card] this session — costs and effects below are from memory and should be checked." Then continue with the analysis flagged. A wrong description of a card stated with confidence is worse than no description.

**Vault notes are NOT a source of truth.** Archetype files in the vault may include placeholder text or auto-transcribed coverage that mis-identifies cards (e.g., a card attributed to Izzet Spellementals that's actually Selesnya-colored). Scryfall is the source of truth. If the vault and Scryfall disagree, Scryfall wins, and flag the vault discrepancy for the user.

---

## Step 1: Gather tournament results — last 4 weeks

Read local scrape output first — that's the primary data source. The Playwright scrapers (`mtg_fetch.py` for melee, `fetch_mtgo.py` for MTGO) run on the user's machine and produce the CSV and JSON files this analysis works from. Cowork reads what they produce; it does not pull melee or MTGO data live.

What you can supplement with a live fetch in a Cowork session: mtgtop8 (server-rendered) and magic.gg Metagame Mentor articles. Everything else needs the local scrapers to have run first.

### Sources

**melee.gg** — Primary source for decklists and round-by-round matchup records. **Requires the local Playwright scraper.** melee.gg is JavaScript-rendered and OAuth-gated; a plain fetch returns a shell. All melee data comes from `mtg_fetch.py` (discovery + scheduling) and `melee_scraper.py` (per-tournament round data), which drive a real browser on the user's machine. The output lands in the format's `scrapes/` folder as `melee_<format>_all_pairings.csv` and `melee_<format>_all_standings.csv`.
- Individual decklists at `https://melee.gg/Decklist/View/{uuid}` render as static HTML and can be fetched live if you have a specific UUID.

**MTGO** — Two types of data, both from the local `fetch_mtgo.py` scraper. MTGO decklist pages are JavaScript-rendered; a plain fetch returns a loading shell, not cards. **Requires the local Playwright scraper.**

*Challenges* — Competitive weekend events. Standard runs a Challenge 32 (32-player cap) and Challenge 64 (64-player cap) most weekends. Full Top 32 decklists and standings land in the local scrape output.
- URL pattern (for reference only — not live-fetchable): `https://www.mtgo.com/decklist/standard-challenge-64-YYYY-MM-DD`

*5-0 League dumps* — Published weekly. Every decklist that went 5-0 in a Standard league gets posted. No matchup data, no standings — just lists. Use these to catch brewing happening outside the Challenge field: new archetypes, fringe cards, singleton tech showing up across multiple pilots.
- URL pattern (for reference only): `https://www.mtgo.com/decklist/standard-league-YYYY-MM-DD`

**mtgtop8.com** — Aggregated results across many events. **Server-rendered — can be fetched live.** Use for archetype meta share, the "decks to beat," and representative decklists. This is the cold-start engine and what `setup.py` seeds the archetype baseline from.
- Standard: `https://www.mtgtop8.com/format?f=ST`

**magic.gg** — Official competitive results. Pro Tours, Regional Championships, sanctioned Organized Play. **Metagame Mentor articles can be fetched live.** Event results pages are JavaScript-rendered.
- Results: `https://magic.gg/results`
- Individual event pages linked from results

**MTGGoldfish** — Meta share percentages and tier standings. **Can be fetched live.**
- Standard meta: `https://www.mtggoldfish.com/metagame/standard/full`

### Supplementary: YouTube recap videos

Caster-style Standard recaps (OptimusTomTV, CovertGoBlue, others) are a second-pass data source that adds two things the CSVs don't: weekend-only matchup numbers from a smaller field, and named-pilot tech notes ("Alex McIac's Izzet Fling list," "post-PT Mono-Green cut its Curators from 4 main to 2"). Use them after you've scraped the events, not before.

**When the user pastes a YouTube link, pull the transcript:**

```bash
pip install yt-dlp --break-system-packages -q
yt-dlp --write-auto-sub --sub-lang en --skip-download --sub-format vtt -o "%(id)s.%(ext)s" "<URL>"
yt-dlp --get-title --skip-download "<URL>"
yt-dlp --print "uploader,upload_date,duration_string" --skip-download "<URL>"
```

Then clean the VTT to plain text:

```python
import re
with open("<id>.en.vtt") as f:
    raw = f.read()
lines, out, last = raw.split("\n"), [], ""
for ln in lines:
    if "-->" in ln or ln.startswith("WEBVTT") or ln.strip().startswith(("Kind:","Language:")) or not ln.strip():
        continue
    ln = re.sub(r"<[^>]+>", "", ln).strip()
    if not ln or ln == last: continue
    out.append(ln); last = ln
text = re.sub(r"\s+", " ", " ".join(out)).strip()
```

Save both the `.vtt` and cleaned `.txt` to `Skills/mtg-tournament-analysis/transcripts/<id>.txt` so the skill's source set persists across sessions. The transcripts folder is the durable record — `arch_update.txt` and similar debug files in there are scratch, the `*.txt` and `*.en.vtt` pairs are signal.

**What a typical recap covers** (OptimusTomTV format, ~50-60 min):
1. Combined metagame share by pilot count (top 10-15 decks)
2. Popularity tier analysis (S/A/B/C/D by standard deviation from mean)
3. Top 10 win rate decks (small samples; sleeper picks)
4. Head-to-head matchup matrix for the top 10-11 presence decks
5. Recent champions and their archetypes

**What to extract for archetype files:**
- Named-pilot tech (e.g., "Tamoya Kobayashi's monumentless Izzet Lessons with Ral, Crackling Wit + Aemiritus of Ideation")
- Card swaps with reason (e.g., "post-PT Mono-Green cut Keen-Eyed Curator from 4 main to 2 because the field shifted off graveyard axis")
- Specific weekend matchup numbers (with N when stated)
- Distinguishing features that separate two builds of the same archetype (e.g., Mardu Discard runs Hardened Academic + Practiced Offense, NOT Flameweave Phoenix, unlike Rakdos)

**Verify cards via Scryfall** if the caster mentions a card you can't confirm — Step 0 hard rule applies. Caster pronunciations sometimes drift ("Wandermurk Crab" vs "Eddymurk Crab"). The transcript text comes from YouTube auto-captions and frequently mangles card names; check the actual card before writing it into a file.

### Supplementary: Twitter / X

Players post results during and after MTGO Challenges, often before Wizards publishes official standings. The most common post pattern is a brief result declaration — "Top 4'd the Standard Challenge" or "9th the Challenge 64" — sometimes with a screenshot of final standings or pairings. These are easy to spot and usually accurate.

Search `"standard challenge" after:YYYY-MM-DD` on X/Twitter around the weekend of the event. Look for posts matching the pattern "Top X" or "Xth the challenge". If you find multiple players reporting results, cross-reference their reported finishes against the official standings once published. Treat pre-publication data as unverified.

### Event types to prioritize

Pull from these in order of weight:
1. Regional Championships (RCs) and Pro Tours (paper)
2. MTGO Challenges (weekly, high volume — weight these heavily for trend data)
3. Spotlight Series
4. RCQs
5. MTGO 5-0 dumps (no matchup data, but useful for card-level signals)
6. YouTube caster recaps (use as a second pass after scraping — adds weekend-only matchup numbers and named-pilot tech the CSVs don't carry)

Filter out small locals and casual store events (fewer than ~30 players). MTGO league results below 5-0 are not published.

### Time split

The analysis uses three windows.

- **Recent window**: the last 2–3 weeks of current-era events. Run `mtg_fetch.py --since YYYY-MM-DD` where the date is 2–3 weeks ago. This is the live meta — what's winning right now.
- **Current era window**: everything from the era start to today. Run `mtg_fetch.py` without flags. This is the full picture of how the meta developed since the last reset, whether that reset was a set release or a ban.
- **Prior era baseline**: the saved snapshot from the era before (`baselines/meta_baseline_[era_slug].json`, or `archive/through-YYYY-MM-DD/baselines/` once it's been frozen). This is the cross-era reference.

`mtg_fetch.py` gets the window start from `mtg_era.py`, which takes the later of the newest set release and the newest B&R date for the format. The recent window cutoff is a judgment call — use 2 weeks for an active meta, 3 weeks if events have been thin.

If the era just started (fewer than ~10 events total), don't force a recent-vs-earlier split — there's nothing meaningful to diff yet. Report the full era window only and note the sample size. After a ban this will be the normal state for two or three weeks; say the sample is small rather than dressing it up.

---

## Step 1.5: Collect melee.gg tournament IDs

Tournament data comes from melee.gg directly. Tell the user to run:

> ```
> python mtg_fetch.py
> ```
>
> This searches melee.gg/Tournaments for Standard events with published decklists since the latest set release (window start comes from `set_releases.json`) and scrapes them automatically. Both scripts are in `Skills/mtg-tournament-analysis/`.
>
> Flags: `--since YYYY-MM-DD` (tighter window), `--dry-run` (see what it found without scraping).
>
> To target a specific event instead: `python melee_scraper.py 393283 339227`

Wait for the user to paste the CSV before proceeding to Step 2. If they paste it, skip straight to matrix building.

**Staleness check (mandatory before using on-disk data):** check the newest event date in the combined pairings file (`melee_<format>_all_pairings.csv`, e.g. `melee_standard_all_pairings.csv`) and the `date` fields in `mtgo_*_latest.json` before treating them as current. If the newest data is older than the recent window, say so plainly ("local data ends YYYY-MM-DD") and ask the user to run the fetch scripts rather than presenting old data as the live meta. The scheduled scrape can fail silently — file dates are the only honest signal.

**Era check (also mandatory):** run `python mtg_era.py` and confirm the data folder holds data from *this* era. Right after a ban the folder is empty by design — `archive_era.py` moved the old files out. An empty data folder means "no post-ban data scraped yet," not "no data exists." Say which of those it is. Do not reach into `archive/` to fill the gap and present it as current.

---

## Step 2: Build the matchup matrix

### Important: melee.gg data access constraints

melee.gg tournament pages are JavaScript-rendered. Fetching `https://melee.gg/Tournament/View/{id}` returns only a static shell — the round-by-round pairings, standings, and match results are loaded dynamically and are not accessible via web_fetch. The melee.gg API also requires OAuth credentials granted only to tournament organizers and their designated coverage staff.

**What IS accessible from melee.gg:**
- Individual decklists via `https://melee.gg/Decklist/View/{uuid}` — these render as static HTML with full 75-card lists
- Decklist pages linked from magic.gg articles or surfaced in search results

**What IS NOT accessible:**
- Round-by-round pairings
- Per-player match records
- Swiss standings tables
- Live bracket/elimination data

### When the user pastes melee_scraper.py output

The scraper produces two CSVs:

**`melee_<format>_all_pairings.csv`** (e.g. `melee_standard_all_pairings.csv`) — one row per match:
`tournament_id, tournament_name, round, table_num, player1, player1_deck, player1_deck_url, player2, player2_deck, player2_deck_url, result, winner`

**`melee_<format>_all_standings.csv`** — one row per player per round:
`tournament_id, tournament_name, round, rank, player, deck_name, deck_url, match_record, game_record, points, omw_pct, tgw_pct, ogw_pct`

To build the matchup matrix from pairings CSV:
1. Use `player1_deck` and `player2_deck` as archetype labels (normalize similar names to one canonical label — e.g. "Mono-Green Landfall" and "Mono Green Landfall" → same deck)
2. For each unique deck-pair (A vs B), count wins for each side
3. Only report a matchup cell when n ≥ 10 matches (matches `MIN_MATCHUP_GAMES` in the scripts); use "—" below that threshold
4. Express as win% from Deck A's perspective: `A wins / (A wins + B wins)`

If `player1_deck` is blank for a match, try fetching `player1_deck_url` from melee.gg Decklist/View to get the archetype name from the decklist title.

### Matchup data sources — in priority order

1. **magic.gg Metagame Mentor articles** — Frank Karsten publishes per-archetype win rates and explicit favored/struggles matchup lists for each RC weekend. These are the most authoritative aggregated matchup numbers available. Fetch these directly.

2. **Third-party aggregators with round data:**
   - `https://www.mtggoldfish.com/tournament/{event-name}` — MTGGoldfish sometimes publishes individual player records with archetype labels. Try fetching event-specific pages.
   - `https://mtgdecks.net/Standard/{event-name-tournament-id}` — mtgdecks.net surfaces individual player results (e.g. "Top8 (4-3) 57%") with archetype labels, aggregated from melee.gg. Search for the specific event by name + date to find these pages.
   - `https://www.metamages.com` — MetaMage aggregates MTGO and melee round data into per-matchup win rates with match counts. Search for archetype-specific matchup queries.
   - `https://mtga.untapped.gg/constructed/standard/archetypes/{id}/{archetype-name}` — Untapped.gg has per-matchup win rates from Arena ladder data. Matchup breakdowns are paywalled (Premium feature), but the archetype page itself is accessible and shows overall win rate, total matches, and popular decklists.

3. **SCG/ChannelFireball/coverage articles** — Major events (RC weekends, Pro Tours, Spotlights) often get dedicated coverage with round-by-round feature match recaps, Top 8 profiles with full records, and occasionally full standings exports. Search by event name.

### Building the matrix

**When the user has a pairings CSV from melee_scraper.py**, render an interactive matchup matrix widget using `show_widget`. The widget loads the CSV client-side (no server needed), computes win rates for every archetype pair, and displays a color-coded heatmap. Use this HTML:

- File drop zone using PapaParse (from cdnjs.cloudflare.com)
- For each row: skip byes (player2 empty), skip forfeits, skip draws
- `matchup[d1][d2].wins++` when winner == player1; always `matchup[d1][d2].total++` and `matchup[d2][d1].total++`
- Win rate = wins / total, shown as % with W-L in sub-text
- Color scale: ≥65% strong green → ≥55% light green → 45–55% neutral → ≥35% light red → <35% strong red
- Two sliders: "min matches per deck" (filters which archetypes appear) and "min cell matches" (fades low-sample cells)
- Mirror cells (same deck vs same deck) show "—"
- Deck names are trimmed — "Izzet Spellementals " and "Izzet Spellementals" are the same deck

When round data is available from aggregators but no CSV:

1. For each target archetype player found in event results, record: player name, final record, and any per-round opponent archetype data
2. Aggregate by matchup pair: wins / total matches, expressed as a percentage
3. Present as a table with match counts in parentheses

| Deck | vs Aggro | vs Midrange | vs Control | vs Combo | Overall |
|------|----------|-------------|------------|----------|---------|
| Archetype A | 63% (8) | 44% (9) | 71% (7) | — | 58% |
| Archetype B | ... | ... | ... | ... | ... |

Use "—" when fewer than 10 matches exist for that pairing. Note the source and whether data is from RC paper, MTGO Challenge, or Arena. MTGO Challenge data often has larger sample sizes than any single paper RC — weight it accordingly, but flag that MTGO and paper metas sometimes diverge (card availability, player base, metagame pace).

When round data is NOT available, use Metagame Mentor win rates + explicit favored/struggles lists as the matrix substitute. Label it as aggregated win rates, not raw round data. A partial matrix sourced honestly is more useful than silence.

---

## Step 3: Identify the meta shift

Two layers of analysis, run both every time there's enough data.

---

### Layer 1: Intra-era drift (recent vs earlier this era)

Compare the **recent window** (last 2–3 weeks) against the **earlier current-era data** (era start to the start of the recent window).

This tells you how the meta is maturing. The field adjusts after week 1 — good players identify what's winning, tech against it, and the meta stabilizes or breaks open again. This layer catches that.

For each archetype: did it rise, fall, or hold? Name the number — "Izzet Elementals went from 3 top 8s in the first 3 weeks to 8 in the last 2" is the kind of sentence this layer should produce.

For cards: what moved between the earlier lists and the recent ones? A card appearing more frequently in the recent window is responding to something in the field. Name what.

**Skip this layer if:** the current era has fewer than ~15 total events, or the recent window has fewer than 5 events. Diffing noise against noise isn't useful — just report the full era window and move on.

---

### Layer 2: Cross-era shift (current era vs prior era baseline)

Compare the **full current era window** against the **prior era baseline** (`baselines/meta_baseline_[era_slug].json`, or the copy under `archive/through-YYYY-MM-DD/baselines/`).

This tells you what actually changed at the break. Some archetypes survive a rotation or a ban mostly intact. Others collapse. New ones emerge. This layer documents that.

For each archetype with data in both windows:
- Change in meta share (e.g., Dimir Midrange was 7.5% in Strixhaven week 1 and is now 14% at week 6)
- Change in top 8 representation across comparable event counts
- Archetypes new to this era — not present in the prior baseline at all
- Archetypes that dropped out or declined sharply

**When the break was a ban, name the mechanism.** A deck that fell off a cliff because its 4-of got banned is not a metagame trend, and reporting it as one is misleading. Check `bans.json` for `decks_hit` and separate the two groups: decks that lost cards, and decks whose share moved because the field around them changed. The second group is the interesting one.

**If no prior baseline exists** (first era the skill has tracked): skip this layer, label it "no prior baseline available," and say which baseline is the first reference point.

---

### Signal rules (both layers)

5-0 dumps cover a broader slice of the player base than the Challenge Top 32. A card appearing in 3+ independent 5-0 lists in one week is worth noting. If it's also in Challenge Top 8s, that's confirmed signal. Only in dumps and not yet Challenges — flag it as early.

One pilot's change is noise. The same change across independent lists in the same window is signal. Cross-source confirmation (Challenge + league dump, or MTGO + paper) is stronger than either alone.

---

### Saving snapshots

After every analysis session, save a snapshot of the current data to the baseline file. This is what makes Layer 1 work over time.

The baseline file for the current era (`baselines/meta_baseline_[era_slug].json`) holds a `snapshots` array. A ban starts a new file, so a run-over-run delta never straddles a break. Append a new entry after each session:

```json
{
  "set_name": "Secrets of Strixhaven",
  "set_release": "2026-04-24",
  "snapshots": [
    {
      "date": "2026-05-04",
      "label": "Week 1 — local events only",
      "events_covered": 9,
      "total_players_with_deck": 80,
      "archetypes": {
        "Izzet Elementals": { "player_count": 11, "meta_share_pct": 13.8, "top8_appearances": 5 },
        "Dimir Midrange":   { "player_count": 6,  "meta_share_pct": 7.5,  "top8_appearances": 3 }
      }
    },
    {
      "date": "2026-05-18",
      "label": "Week 3 — first RCQ weekend included",
      "events_covered": 22,
      "total_players_with_deck": 310,
      "archetypes": { "...": {} }
    }
  ],
  "event_top8s": {},
  "matchups": {}
}
```

When running Layer 1, compare the most recent snapshot against the previous one. The `label` field is how you know what kind of events each snapshot covers.

**Re-run `build_baseline.py`** (in `Skills/mtg-tournament-analysis/`, next to the scrapers) after any major scrape. It reads the combined standings file (`melee_<format>_all_standings.csv`) and appends a new snapshot entry to the current era's baseline file, stamping each snapshot with its era slug and start date.

### Goto-list baseline check

Before flagging a card as signal, know what the dominant build of the archetype actually runs. A "new card" in a list isn't signal if it just replaced a flex slot. It's signal when it replaces a 4-of from the goto list across multiple pilots. This is the diff that matters.

When reporting a card movement, frame it explicitly:
- Goto build runs `[X]` as a 4-of. This list runs `[Y]` instead. That signals `[meta read]`.
- Goto build is `[A, B, C, D]` in slot N. Three pilots independently swapped to `[E]`. That signals `[meta read]`.

Without the baseline, "Card Z is in 5 lists this week" is just a count. With the baseline, it's a deviation worth understanding.

---

## Step 3.5: Coverage-style card commentary

For every card flagged as signal in Step 3, write 1-2 sentences using one or two of the angles below. Don't use all of them — pick the ones that actually apply. A bullet that doesn't fit any of these probably isn't signal worth flagging.

**The angles:**

- **Role:** What slot does this card fill in the deck? (removal, threat, mana fixing, sideboard hate, combo piece, top-end finisher)
- **Replacement:** What card is this displacing in lists from the prior window? Name both, with counts.
- **Synergy:** Is this card in lists because of a 2- or 3-card interaction? Name the line. Format: "[card] shines because [trigger condition], which produces [outcome]."
- **Why now (meta context):** What about the current field made this card good *this* week. Tie it to a deck or card that rose. Format: "[card] is good against [matchup] because [mechanical reason]." The mechanical reason is non-negotiable.
- **Main vs side:** If a sideboard card moved maindeck, what meta read does that imply? If a card is in the sideboard, name the specific opposing threat it answers — not "good vs aggro," but "answers [card name] cleanly."
- **Fail case:** If the sample is small or the card has obvious blowouts, flag what kills it. Coverage casters call this out live ("a sad flow state, just to get one card") — the skill should do the same in writing.
- **Game phase:** For a control or value card, name when in the game it takes over. "Shines on turn 6+" beats "it's a control card."
- **Comparison to a historic card** *(optional, use sparingly):* Only when the analogy is genuinely close — Karsten calling Erode "evoking comparisons to Path to Exile" works because the effect is functionally exile-creature. A forced or loose comparison is worse than none. Default: skip this angle.

Card text comes from Scryfall (Step 0 hard rule). Don't speculate on mechanics. If you can't fetch the card, write the role and replacement angles only — they don't depend on text.

**Sample output:**

> **Eddymurk Crab** — Now a 4-of in 87 of 99 Izzet Prowess lists at PT Strixhaven, up from a 2-of in most prior-window lists. The shift looks like a mirror-match read: it dodges Sunderflock (Elemental tribal) and trades up against Slickshot Show-Off. Replaces copies of Elusive Otter in trimmed builds.

> **Withering Curse** — Two-card combo with Ancient Cornucopia for a 3-mana board sweep, single-handedly enabling the Sultai Control archetype that wasn't in the meta two weeks ago. Watch the 5-0 dumps for it next week — small sample so far, fail case is drawing the curse without the cornucopia.

> **Petrified Hamlet** — Sideboarded by most Jeskai Control pilots specifically as a clean answer to Ba Sing Se. Naming the answer-target pair is what makes the inclusion useful — generic "land hate" wouldn't.

---

## Step 4: Answer the core questions

**What's winning right now?**
Top 8 appearances in the recent window, cross-checked against MTGGoldfish meta share. Flag anything meaningfully over- or underperforming its expected rate.

**What changed in the last 2 weeks?**
The delta from Step 3. Be specific — name the deck, the card, the number.

**What does the matchup landscape look like?**
Summary of the matrix. Which deck has the cleanest matchup profile? Any surprising results (a deck beating something it's not supposed to)?

**What's worth revisiting?**
Decks that performed well in the prior window but haven't shown up in the recent one. Could be timing (small event sample), could be a real decline. Worth flagging if the prior window numbers were strong.

---

## Step 5: Update archetype files

After any session that produces matchup data, update the archetype files in `02 Projects/MTG Tournament Analysis Skill/Archetypes/`.

**Always look cards up on Scryfall when building a reference file.** You are explicitly allowed and expected to fetch Scryfall to learn what any card does. Do not write a card's role from a guess, and do not hedge with "needs verification" when you can just check. If a card is unfamiliar, fetch it (Step 0 verification pattern) and describe what it actually does. The only time you flag a card as unconfirmed is when Scryfall is genuinely unreachable that session — and then you say so plainly. A reference file with verified card text is the whole point; a file full of "unverified" placeholders is a half-finished job.

### For each archetype with new matchup data:

1. **Find the file** — `[C] {Archetype Name}.md` in the Archetypes folder.
2. **Check the era of what's already there.** A heading like `## Matchup data (pre-ban, through 2026-08-10)` is frozen history from a dead format. Never replace it and never merge new numbers into it — add a new `## Matchup data` section for the current era below it.
3. **Update or add the current-era `## Matchup data` section.** If a current-era section already exists, replace it entirely. If not, append at the end of the file.
4. **Update `date:` in the front matter** to today's date.
5. **If the archetype ran a card that got banned**, keep the ban banner at the top of the file. Don't quietly drop it once new data arrives — a rebuilt deck sharing a name with the old one is exactly the case where a reader needs the warning.

Section format (sort by win% descending; flag N < 20 as `* small sample`; omit matchups with N < 10):

~~~markdown
## Matchup data

*Updated: YYYY-MM-DD · {event names} · {total match pool} total matches*

| Opponent | Win% | N | Notes |
|---|---|---|---|
| Deck A | 62.9% | 159 | — |
| Deck B | 27.8% | 18 | * small sample |

**Overall field win rate: X% (N games)**
~~~

### For new archetypes (≥ 20 games, no existing file):

Create `[C] {Archetype Name}.md` with front matter, a one-line deck summary, a key cards table, any sideboard notes from coverage, and the matchup data section. Look up every card you don't already know on Scryfall and write its real role — don't ship a table of cards you couldn't be bothered to verify. A stub is more useful than a gap, but the stub should still have correct card text; fill in deeper game plan as coverage accumulates.

**Creation threshold:** ≥ 20 games in the current dataset, no existing file in `Archetypes/`, appeared in at least one RC, PT, or MTGO Challenge.

### When the source is a YouTube transcript (not a CSV)

Don't overwrite the existing `## Matchup data` section — the snapshot's numbers come from a much larger pool (e.g., 5,803 matches across 15 events). Transcript numbers are weekend-only.

Instead, append a `## Weekend update — {Event Name(s)} ({YYYY-MM-DD})` section after `## Weaknesses` (or before `## Matchup data` if Weaknesses isn't present). Format:

```markdown
---

## Weekend update — {Event} ({YYYY-MM-DD})

Source: {Caster} ({video ID from yt-dlp}). {Pilot count}, {meta share}%, {combined WR}.

**Beating up**:
- vs {Deck}: {WR}% — {one-line mechanical reason}

**Falling apart**:
- vs {Deck}: {WR}% — {one-line mechanical reason}

{One paragraph of the deck's overall standing for the weekend or pilot guidance.}
```

Update the `sources:` line in front matter to include the new video ID:

```yaml
sources: existing_ids, NEW_VIDEO_ID (Caster — Event recap, YYYY-MM-DD)
```

If the transcript surfaces a distinct variant (e.g., monumentless Izzet Lessons), add a `## Variants — {Event} (YYYY-MM-DD)` section with the named pilot, the engine change, and the specific cards swapped in. Don't fold variants into the main game plan section — they're a parallel build, not a refinement.

---

## Step 6: Update the meta snapshot

The current set has one canonical snapshot file: `02 Projects/MTG Tournament Analysis Skill/[C] Meta Snapshot — {Set Name}.md`. This is the user-facing summary of the format and gets re-read every session.

After a YouTube recap is processed, append a `## Weekend recap — {Events} ({YYYY-MM-DD})` section at the bottom of the snapshot. Don't rewrite the existing headline or tier list — those represent the larger-sample read. The weekend recap is a delta against that.

Structure:

```markdown
---

## Weekend recap — {Events} (YYYY-MM-DD)

Source: {Caster} YouTube recap ({video ID}), "{Video title}" — {duration}, uploaded YYYY-MM-DD. {Combined pilot count} pilots across {N} events.

### Combined metagame share (top 10 by pilot count)

| Deck | Pilots | Share | Combined WR | Note |
|---|---:|---:|---:|---|
| ... | ... | ... | ... | ... |

### What changed in 2 weeks

{3-6 short paragraphs. Name the deck, name the card, name the number. Use the named-pilot tech to anchor claims.}

### Top 10 win rate (small sample standouts)

{Numbered list, one line each: deck → key tech / named pilot / event placement.}

### Recent champion update

- **YYYY-MM-DD — {Event}**: {Player} on **{Deck}**, {record}.

### Sources

- {Caster} — "{Video title}" ({URL}, YYYY-MM-DD, transcript at `Skills/mtg-tournament-analysis/transcripts/{video ID}.txt`)
```

Multiple weekend recaps stack at the bottom in chronological order. When the next set drops, archive the snapshot and start a new file for the new set.

---

## Output Format

Use this structure every time:

---

**Standard — [Era label] ([era start] – [today])**
*Era anchor: [set release, or B&R effective DATE — cards banned]*
*Events covered: [names, types, dates, player counts]*
*Legal sets as of [date]: [most recent set] through [oldest set]*
*Banned in Standard: [current ban list]*
*Snapshots available: [dates of saved snapshots, or "none"]*
*Prior era baseline: [prior era label, or "none — first run"]*

---

**What's winning (current era window)**
[2-3 sentences. Archetype names, top 8 counts, over/underperformance vs. meta share. If the era is days old, lead with the sample size instead of the ranking.]

---

**Intra-era drift — recent vs earlier this era**
[How the meta has matured since the era started. Decks rising or falling, cards moving in or out of lists. Name the numbers. Skip and note "insufficient data" if fewer than ~15 total events or 5 recent events.]

---

**Cross-era shift — [current era] vs [prior era baseline]**
[What changed at the break. Archetypes that survived, collapsed, or appeared fresh. Name the numbers. When the break was a ban, separate decks that lost a card from decks whose share moved on their own. Skip and note "no prior baseline" if this is the first tracked era.]

---

**Matchup matrix**
[Table as defined in Step 2. Include event source and sample sizes. If partial, note which events are missing round data.]

---

**Cards to watch**
- [Card name] — Each card gets at least one of: a named replacement (with counts), a named synergy, a meta-context "why now," a specific sideboard answer-target, or a fail case. Not a generic "this card is good" sentence. If a card has none of those, it's not signal worth flagging.
- [3-5 cards]

---

**Worth revisiting**
[Optional. A deck or strategy from the prior window with upside. Skip if nothing stands out.]

---

**The call**
[1-2 sentences. The one actionable thing for someone preparing for a tournament this weekend.]

---

Keep it tight. If you've made the point, stop.

---

## Feedback

If a script broke, a site changed its layout, or the analysis missed something real — a bug report helps fix it for everyone.

**What to include:**

- What you were trying to do
- Which script failed (`mtg_fetch.py`, `fetch_mtgo.py`, `melee_scraper.py`, etc.)
- The full error message or wrong output (paste it)
- Your OS and Python version (`python --version`)
- The date you ran it (site structures change)

**Where to file it:** [GitHub Issues](https://github.com/Phillip-Hurst/MTG-Data/issues)

Use this format when opening an issue:

```
**What I was trying to do:**

**Script:**

**Error / wrong output:**

**Python version:**

**OS:**

**Date run:**
```

For feature requests — new data sources, new analysis angles, coverage casters to add — use the same Issues link and label it `enhancement`.

---

## Handling specific requests

**"What should I play?"** — One deck, one reason. Commit. Check it against the current ban list first, and if the era is only days old, commit to the pick but say what it's built on ("two Challenges and the mtgtop8 read, not a season of data").

**A specific event** — Fetch the magic.gg Metagame Mentor article covering that event for win rates and matchup data. For decklists, fetch individual melee.gg Decklist/View links as surfaced in those articles or search results. Do NOT attempt to fetch melee.gg Tournament/View pages expecting round data — they are JS-rendered and return nothing useful. Instead, search mtgdecks.net and MTGGoldfish for that specific event by name to find aggregated player records.

**Finding a specific player's decklist from a bulk dump** — Magic.gg Pro Tour decklist pages publish all lists in one page sorted alphabetically by last name. Player names are NOT visible in the rendered text returned by web_fetch, but ARE in the raw HTML source as `deck-title` attributes on `<deck-list>` tags. Do NOT try to count alphabetically through the page — this is error-prone and wrong.

The correct approach: fetch the raw HTML and search for the player name directly.

**On Mac/Linux (bash):**
```bash
curl -s "https://magic.gg/decklists/[event-decklist-page]" | grep -i "LastName" -A 60
```

**On Windows (PowerShell) — confirmed working:**
```powershell
$names = "Player1|Player2|Player3"  # pipe-separated last names
foreach ($PAGE in @("a-f","g-l","m-r","s-z")) {
    "=== $PAGE ===" | Out-File -Append pt_results.txt
    $lines = ((Invoke-WebRequest "https://magic.gg/decklists/[event]-standard-decklists-$PAGE" -UseBasicParsing).Content) -split "`n"
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $names) {
            $end = [Math]::Min($i + 60, $lines.Count - 1)
            $lines[$i..$end] | Out-File -Append pt_results.txt
        }
    }
}
```
This outputs matching lines including the `deck-title` and `subtitle` attributes, which contain the player's full name and deck archetype.

**If the bash workspace is unavailable** (error: "isolated Linux environment failed to start"), fall back to PowerShell and have the user run it in VS Code's terminal. This is a Cowork sandbox issue, not a network issue.

**Compound last names:** Magic.gg sorts by the secondary surname word, not the first. "Santos Esquici" sorts under E (Esquici), appearing in the A-F section. "De Gaetano" sorts under G. When searching, try both the full compound name and just the primary/secondary word separately.

**Search an aggregator by player name** — Sites like MTGDecks.net and Aetherhub tag PT decklists by player. Search: `"[Last Name]" "[Event Name]" site:mtgdecks.net` or `site:aetherhub.com`.

**Search magic.gg coverage articles** — The "Spiciest Decklists" article published alongside each PT names players explicitly. Search: `"[Last Name]" site:magic.gg [event name]`.

**Isolating Constructed records at a mixed-format Pro Tour** — Pro Tours combine Draft and Standard (or other Constructed) rounds on the same day. Published standings are cumulative, not split by format. To compute a player's Constructed-only record:

1. Fetch the standings after the last Draft round (e.g. Round 3 for a 3-Draft/5-Standard split). These standings = draft record only.
2. Fetch the end-of-day standings (e.g. Round 8).
3. Subtract: `Standard pts = Round 8 pts - Round 3 pts`. Divide by 3 to get wins.

Example: Round 8 = 21 pts, Round 3 = 9 pts → Standard = 12 pts = 4-1.

This lets you identify which archetypes actually performed in Constructed independent of draft variance, and find players who went 5-0 in Standard despite a poor draft day (or vice versa).

**An MTGO Challenge** — Fetch the relevant `https://www.mtgo.com/decklist/standard-challenge-{32|64}-YYYY-MM-DD` page directly. These publish as static HTML with full Top 32 standings and decklists. If the exact date is unknown, check `https://www.mtgo.com/decklists` and filter by Standard.

**"Any interesting 5-0s?"** — Pull the most recent 1-2 league dump URLs from `https://www.mtgo.com/decklists`. Scan for cards or archetypes that appear in multiple independent lists. Don't recap every list — pull out what's new or surprising.

**A specific deck** — Focus the card analysis on that archetype across both windows. Check both Challenge results and 5-0 dumps for it. What's in, what's out, how are the matchups trending?

**Thin data** — If fewer than 2-3 events exist in either window, say so. Be clear about what the numbers can and can't support. MTGO Challenges run most weekends, so a thin paper window can often be supplemented with MTGO data — just label the source.

---

## When live data isn't available

1. Step 0 is still mandatory — fetch `https://magic.wizards.com/en/formats/standard` to confirm the legal set list.
2. Anchor everything to the confirmed legal sets.
3. Be explicit about which sets are within your training knowledge. Don't reference cards from sets outside your coverage.
4. Follow the output format as normal. Label it as training-data-based with an approximate knowledge date.
5. Skip the matchup matrix if you have no real round data to work from — don't fabricate match records.
6. Don't show a blank template. Give the actual analysis with what you know, labeled honestly.

---

## Credits

Card text comes from [Scryfall](https://scryfall.com) (see the Step 0 hard rule). Magic: The Gathering is © Wizards of the Coast; this is unofficial Fan Content under the [WotC Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy), not approved or endorsed by Wizards.
