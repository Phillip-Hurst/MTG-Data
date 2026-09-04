# Untapped: the index and the log

Two JSON endpoints. Between them they hold everything a review needs, and neither one
is the replay viewer. **The replay viewer is not a reading path.** It steps one game
state per round trip, a three-game match runs to several hundred states, and every one
of those states costs a browser call to fetch and a screenshot's worth of context to
read. The log holds strictly more information in one call.

| Source | What it is | Use it for |
|---|---|---|
| **The index** | `api.mtga.untapped.gg/api/v1/games/users/<userId>/players/<playerTag>/?card_set=<CODE>` | Which matches exist, results, durations, mulligan counts, the bottomed card |
| **The log** | `api.mtga.untapped.gg/api/v1/upload-log/<shortId>` | Every finding. Plays, mana payments, revealed hands, decklists, sideboard swaps |

Both are fetched from the page context, because the sandbox can't reach them and the
page's origin can. **Any `mtga.untapped.gg` page works.** Open the user's profile or
deck page, which is where the index parameters come from anyway, and run the fetches
there.

---

## Step 1: the index, one call for the whole cluster

The `userId` and `playerTag` are the first two path segments of any untapped profile
URL, and `friendly_deck_id` is the `deck/` segment. So a deck-page URL the user pastes
carries everything needed to enumerate their matches with that deck.

```js
const base = 'https://api.mtga.untapped.gg/api/v1/games/users/<userId>/players/<playerTag>/';
const rows = await (await fetch(base + '?card_set=HOB', {credentials:'include'})).json();
const mine = rows.filter(m => m.friendly_deck_id === '<deckId>')
                 .sort((a,b) => a.match_start - b.match_start);
```

**`card_set` is required and has to be a real Arena set code.** Anything else returns
`400 Invalid card set <x>`, and a set the account can't see returns `403`. There is no
"all" value, so fetch the two or three codes that cover the date range and concatenate.
Codes come from untapped's own card data, newest last:

```js
const cards = await (await fetch('https://mtgajson.untapped.gg/v1/latest/cards.json')).json();
const sets = []; for (const c of cards) if (c.set && !sets.includes(c.set)) sets.push(c.set);
sets.slice(-12);   // the recent ones, newest at the end
```

What each row carries, per match and per game, without touching a log:

| Field | What it gives |
|---|---|
| `short_id` | The log id. This is the only thing you need from a match to read it |
| `match_start` | Epoch ms. Session dates for the ledger come from here, not from today's date |
| `event_name` | `Historic_Ladder` is Bo1, `Traditional_*` is Bo3 |
| `winning_team_id` vs `friendly_team_id` | Match result |
| `games[]` | One entry per game: `game_number`, `game_duration_seconds`, `active_player_id`, `winning_team_id` |
| `games[].player_opening_hands` | **Length > 1 means a mulligan.** Length 1 is a snap keep |
| `games[].player_mulligan_put_on_bottom` | The `grpId` of the card bottomed. Resolve it through the name map |
| `games[].opponent_revealed_deckstrings` | What they showed, if you want it before reading the log |
| `friendly_deck_id`, `friendly_deck_name` | Filtering the deck you're reviewing out of the profile |

**Pace comes from here, not from the log's timestamp headers.**
`game_duration_seconds` divided by the game's turn count is the `untapped-duration`
measure, and it's both players' clocks combined. A game with 0 turns (an immediate
concede) gets `measure: "none"` and a null, not a divide by zero.

---

## Step 2: the log, one call per match

```js
const j = await (await fetch('https://api.mtga.untapped.gg/api/v1/upload-log/' + sid)).json();
// { decks, userId, playerId, deckId, timestamp, log }
```

`j.log` is a 5 to 20 MB string of `[UnityCrossThreadLogger]` blocks, each a header line
followed by one JSON object. Extract the objects with a brace-matching scan that
respects strings, because a regex will not survive nested braces in card text:

```js
const L = j.log, objs = []; let i = 0;
while (true) {
  const s = L.indexOf('\n{', i); if (s < 0) break;
  let d = 0, k = s + 1, inStr = false, esc = false, end = -1;
  for (; k < L.length; k++) {
    const ch = L[k];
    if (inStr) { if (esc) esc = false; else if (ch === '\\') esc = true; else if (ch === '"') inStr = false; continue; }
    if (ch === '"') { inStr = true; continue; }
    if (ch === '{') d++; else if (ch === '}') { d--; if (d === 0) { end = k; break; } }
  }
  if (end < 0) { i = s + 2; continue; }
  try { objs.push(JSON.parse(L.slice(s + 1, end + 1))); } catch (e) {}
  i = end + 1;
}
```

A three-game match is 1,400 to 4,600 objects. The ones that matter carry
`greToClientEvent.greToClientMessages[].gameStateMessage`.

### The endpoint is rate limited

`upload-log` returns **429** under any sustained pull. A 22-match cluster will hit it.

- Sleep about 3 seconds between logs.
- On 429, back off 7 seconds and retry, up to about 5 tries.
- A 429 arrives as JSON with a `detail` key and **no `log` field**, so a parser that
  assumes `j.log` is a string throws `Cannot read properties of undefined`. Check
  `typeof j.log === 'string'` and report the failure rather than dropping the match
  silently.

### Long runs outgrow the evaluate timeout

The browser's JavaScript call caps at about 45 seconds, and a throttled batch of five
logs takes longer than that. The call times out while the page keeps working, which
looks like a failure and isn't.

Park the run on `window` and poll it:

```js
window.__bg = 'running';
runBatch(ids).then(r => { window.__bg = r; }).catch(e => { window.__bg = 'ERR ' + e.message; });
'started'
```

Then a later call does `await new Promise(r => setTimeout(r, 30000)); window.__bg`.
Make the batch function skip ids already parsed, so a retry after a timeout costs
nothing.

### Card names

```js
const cards = await (await fetch('https://mtgajson.untapped.gg/v1/latest/cards.json')).json();
const loc   = await (await fetch('https://mtgajson.untapped.gg/v1/latest/loc_en.json')).json();
const locMap = new Map(loc.map(e => [e.id, e.text]));
const nameOf = new Map(cards.map(c => [c.grpid, locMap.get(c.titleId)]));
```

That resolves `grpId` to a printed name. **It does not replace Scryfall.** Costs, types
and oracle text still get verified on Scryfall, because that's what a finding turns on,
and the rebalanced Alchemy versions differ from the paper card in exactly the way that
decides a review. `api.scryfall.com/cards/collection` takes up to 75 names in one POST
and allows CORS; `?q=!"A-Card Name"` gets a rebalanced version.

### Getting results back out

**Return `string[]`, never one long string.** The browser tool truncates a long string
at about a thousand characters. An array of short lines survives, so render the game as
lines and page through it in slices of 40 to 50.

**Strip query strings from anything you echo.** The extension refuses a result that
looks like it carries cookie or query-string data and returns
`[BLOCKED: Cookie/query string data]` instead of the value. Reading
`performance.getEntriesByType('resource')` trips this. Return `host + pathname` only.

---

## The two-pass rule, which is where the token cost lives

Reading every log in full detail for a 29-game cluster is unaffordable and unnecessary.
Two passes.

**Pass one, every game: the digest.** One parse per match producing, per game, a line
per meaningful event. `T<turn>(m|o) <ME|OPP> <category> <card name>`, plus life changes
and damage. That's 40 to 250 lines per game, it's readable in one call, and it is enough
to see the shape of every game and shortlist the moments that might be findings.

**Pass two, only the shortlist: the trace.** Re-parse the one match and print, for the
two or three turns in question, the annotation stream in order alongside the battlefield
with tap state, `ManaPaid`, `TappedUntappedPermanent`, and any `RevealedCard*`. That's
the evidence a finding needs, and it costs one call per moment.

The discipline is that pass one **never** produces a graded finding. It produces
candidates. A candidate becomes a finding only after a trace, and a trace kills roughly
half of them. In one 29-game cluster it killed a "he had the uncounterable Yawgmoth and
cast a two-drop" finding stone dead: the trace showed three mana sources for a four-mana
spell.

---

## What to pull, and where it lives

Walk the messages in order, carrying state forward.

| What | Where |
|---|---|
| Game number | `gameStateMessage.gameInfo.gameNumber` |
| Turn, active player, phase, step | `gameStateMessage.turnInfo` |
| Life totals | `gameStateMessage.players[].lifeTotal`, keyed by `systemSeatNumber` |
| Zones | `gameStateMessage.zones[]` — `type`, `ownerSeatId`, `objectInstanceIds` |
| Objects | `gameStateMessage.gameObjects[]` — `instanceId`, `grpId`, `ownerSeatId`, `controllerSeatId`, `cardTypes`, `isTapped` |
| Events | `gameStateMessage.annotations[]` |
| Both decklists and every sideboard swap | `j.decks[]`, one entry per game, `mainDeck` and `sideboard` as `grpId` arrays |
| Who won each game | `gameStateMessage.gameInfo.results[]`, `scope: MatchScope_Game`, `winningTeamId` against your own seat |
| Which seat is the user | `j.playerId` matched against the `reservedPlayers` block in the first `matchGameRoomStateChangedEvent` |

**Reset per game.** `gameNumber` changing means a new game: zero the turn counter and
throw away the id maps. Carrying a turn number across the boundary makes game 2's
opening hand invisible, because the hand snapshot only fires while `turnNumber === 0`.

The annotation types worth reading:

```
ZoneTransfer          the spine. details carry zone_src, zone_dest, category
                      (CastSpell, Resolve, Countered, PlayLand, Draw, Discard,
                      Destroy, Sacrifice, Exile, Surveil, Put)
ManaPaid              which source the mana came from, with a color field
TappedUntappedPermanent  the authoritative record of a land tapping
CounterAdded          counter_type and amount. This is how you catch a power-up
ModifiedLife          life swings with their affector
DamageDealt           combat, when the finding needs the numbers
ObjectIdChanged       orig_id and new_id. Carry your maps across it
RevealedCardCreated   how you grade a Thoughtseize or any hand-reveal effect
NewTurnStarted        turn boundaries
TokenCreated          tokens, which the zone lists otherwise leave anonymous
```

**Sideboarding is free here.** Diff `j.decks[n].deck.mainDeck` against `j.decks[0]` and
you have the exact in and out for every game without asking the user to remember it.
Check the counts balance: an in-list shorter than its out-list means a card got missed.

**Hand-reveal effects are gradeable.** A Thoughtseize or a Duress produces a run of
`AnnotationType_RevealedCardCreated`, one per card, followed by the opponent's
`ZoneType_Hand` with the taken card gone. That is the full hand they held, which is the
only way to grade the choice. Grade it on that hand and their available mana at the
time, never on what they drew afterwards.

**Opening hands and mulligans:** take the count and the bottomed card from the index
(above), and the card list from the log's `ZoneType_Hand` for your seat while
`turnNumber === 0`. Snapshots that dedupe consecutive duplicates end on the *second*
seven, not the six, so reconstruct the six as the last seven minus
`player_mulligan_put_on_bottom`. `players[].mulliganCount` is often absent; don't rely
on it.

---

## The five traps

### 0. Lands on the battlefield are not usable mana

**Count usable mana from `ManaPaid`, and count it before writing any "he could have
held X up" line.** Lands in play is the wrong number, and there are at least three ways
it lies.

The one that has already cost a review: a **stun counter**.
`AnnotationType_CounterAdded` with `counter_type: 172` on a land means its next untap
step is spent removing the counter instead of untapping it, so the land sits there
tapped through a turn it looks entitled to. Magmatic Hellkite and the whole "searches
for a basic, puts it onto the battlefield tapped with a stun counter" family do this,
and the giveaway is a `CounterRemoved` for 172 on the following turn with no
`TappedUntappedPermanent` for that land.

The other two: a land that only makes colourless (Petrified Hamlet, Fountainport,
Cavern of Souls) is not a source for a coloured cost, and a land that entered tapped
this turn was never available at all.

**Nonland sources count too, and they have restrictions.** Delighted Halfling's second
ability makes any colour but only for a legendary spell. Phyrexian Tower makes `{C}` or
`{B}{B}` and nothing else, so it can never pay a green activation cost. Badgermole Cub
adds an extra `{G}` only when a creature is tapped for mana, which a sacrifice-for-mana
land does not do. Each of these has flipped a finding.

**The check that settles it.** Sum the `ManaPaid` annotations for every spell cast that
turn, subtract from the untap-step `TappedUntappedPermanent` count, and that difference
is what was actually left. If a finding says a two-mana answer was live, the difference
has to be at least 2 in the right colours, and the `ManaPaid` `color` field says which
colours came from where.

### 1. `isTapped` is omitted, not set to false

**This one has already produced a wrong finding in a shipped review.** MTGA sends
`isTapped: true` on a tapped permanent and leaves the field off entirely when it's
untapped. So merging game objects across messages the obvious way:

```js
objMap.set(ob.instanceId, Object.assign(objMap.get(ob.instanceId) || {}, ob));   // WRONG
```

leaves a stale `isTapped: true` on every land that ever tapped, forever. Every board
then reads as fully tapped, and "he was tapped out" becomes a finding that never
happened.

```js
objMap.set(ob.instanceId, ob);   // right: replace
```

Each message carries full object state for the objects it includes, so replacing is
correct and merging is not.

**Cross-check before writing any mana claim.** Untapped-land counts derived from
`isTapped` must agree with the `TappedUntappedPermanent` and `ManaPaid` annotations for
the same window. If they disagree, the annotations win.

### 2. The active player is not the caster

**This one has already produced a wrong finding.** Labelling a `ZoneTransfer` by
`turnInfo.activePlayer` marks every instant the opponent casts on your turn as yours.
A Golgari deck's digest came back showing it casting Bitter Triumph and Lightning Axe,
which were the opponent's removal spells cast during its own turn.

Label by the card's owner, tracked from `gameObjects[]`:

```js
const ow = ob.ownerSeatId != null ? ob.ownerSeatId : ob.controllerSeatId;
if (ow != null) idToOwn.set(ob.instanceId, ow);
```

Keep the active player as separate information, because whose turn it is still matters.
Two fields, two meanings: `T7(o) ME Sacrifice Young Wolf` is you sacrificing on their
turn, which is a different decision from doing it on your own.

`ownerSeatId` also has to be carried across `ObjectIdChanged` alongside `grpId`, or
ownership goes missing the moment a card changes zones.

### 3. The annotation stream is resolution order, not casting order

A spell cast in response resolves before the ability that was already on the stack, so
the log shows the response resolving first. Reading the stream top-down and calling it a
sequence of decisions gets the causality backwards.

The tell is an ability activation followed by an opponent's cast followed by that cast
resolving, with the original ability's effect landing several messages later. That's a
player tapping low, an opponent taking the window, and the first player's ability
resolving into a board that changed underneath it.

When a finding turns on who had priority and what was open, walk that window message by
message and print the annotations in order alongside the untapped list. Don't summarise
it and don't infer it.

### 4. Object ids get reused and reassigned

`AnnotationType_ObjectIdChanged` is common, and a name resolved from a stale id map
produces lines like "sacrificed Get Lost" for a Map token. Treat a card name attached to
a `Sacrifice`, a `CounterAdded` target, or an unexplained `Put` as unreliable unless the
object was tracked through its id changes. If a single event looks strange and nothing
depends on it, leave it out rather than writing a finding on it.

---

## The replay viewer

Not a reading path. Open it only when the **user asks to see a board**, or when the log
endpoint 404s because the upload is incomplete. In both cases say which one it is.

It renders client-side and steps through `?gameStateId=N`, so it needs the
JavaScript-rendering browser tools and one round trip per state. If the page shows a
login wall, say so and ask the user to sign in rather than working around it. Some
panels are Premium-gated: name the one that's locked and work from what's visible.

Never step the replay to establish a fact the log already holds. The log holds all of
them.

---

## The rule this note exists to enforce

**No claim about available mana without the tap trace behind it.** "He was tapped out",
"she had the counter up", "he could have paid the {3}" are the sentences that decide
reviews, and each one is a specific set of lands and nonland sources in a specific
message. Print them, count them, then write the finding.
