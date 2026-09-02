# Untapped: the replay and the log

An untapped match URL gives you two different things, and a review that mixes them up
gets findings wrong. This note says what each one is, how to read it, and the three
traps that have already produced a wrong finding in a shipped review.

| Source | What it is | Use it for |
|---|---|---|
| **The replay** | `https://mtga.untapped.gg/replay/<shortId>`. A JavaScript board viewer that steps through numbered game states. | Looking at a board the way the player saw it. Screenshots for the user. Sanity-checking one moment. |
| **The log** | `https://api.mtga.untapped.gg/api/v1/upload-log/<shortId>`. The raw MTGA client log the replay is built from. | Everything else. Every finding in a review should come from here. |

**Default to the log.** The replay viewer needs one round trip per game state, and a
three-game match runs to several hundred of them. The log is one fetch and it holds
strictly more: mana payments, priority order, counters, mulligans, both decklists and
the sideboard swaps.

---

## Getting the log

The sandbox can't reach it, so the fetch happens in the browser, on the replay page,
where the origin already matches.

1. Open the replay URL with the browser tools.
2. Fetch the log and the card names in the page context and park them on `window`.

```js
const j = await (await fetch('https://api.mtga.untapped.gg/api/v1/upload-log/<shortId>')).json();
window.__log = j;   // { decks, userId, playerId, deckId, timestamp, log }
```

`j.log` is a ~20 MB string of `[UnityCrossThreadLogger]` blocks, each a header line
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

A three-game match is about 4,600 objects. The ones that matter carry
`greToClientEvent.greToClientMessages[].gameStateMessage`.

**Card names** come from untapped's own card data, not Scryfall:

```js
const cards = await (await fetch('https://mtgajson.untapped.gg/v1/latest/cards.json')).json();
const loc   = await (await fetch('https://mtgajson.untapped.gg/v1/latest/loc_en.json')).json();
const locMap = new Map(loc.map(e => [e.id, e.text]));
const nameOf = new Map(cards.map(c => [c.grpid, locMap.get(c.titleId)]));
```

That resolves `grpId` to a printed name. **It does not replace Scryfall.** Costs,
types and oracle text still get verified on Scryfall, because that's what a finding
turns on. `api.scryfall.com/cards/collection` takes up to 75 names in one POST and
allows CORS, so one call from the same page covers a whole match.

**Return results in small pieces.** The browser tool truncates a long string at about
a thousand characters. An array of short lines survives where one long string doesn't,
so render the game log as `string[]` and page through it in slices of 40 to 50.

---

## What to pull, and where it lives

Walk the messages in order, carrying state forward.

| What | Where |
|---|---|
| Game number | `gameStateMessage.gameInfo.gameNumber` |
| Turn, active player, phase, step | `gameStateMessage.turnInfo` |
| Life totals | `gameStateMessage.players[].lifeTotal`, keyed by `systemSeatNumber` |
| Zones | `gameStateMessage.zones[]` — `type`, `ownerSeatId`, `objectInstanceIds` |
| Objects | `gameStateMessage.gameObjects[]` — `instanceId`, `grpId`, `controllerSeatId`, `cardTypes`, `isTapped` |
| Events | `gameStateMessage.annotations[]` |
| Both decklists and every sideboard swap | `j.decks[]`, one entry per game, `mainDeck` and `sideboard` as `grpId` arrays |
| Who won each game | `gameStateMessage.gameInfo.results[]` — `winningTeamId` against your own seat |
| Which seat is the user | `j.playerId` matched against the `reservedPlayers` block in the first `matchGameRoomStateChangedEvent` |

The annotation types worth reading:

```
ZoneTransfer          the spine. details carry zone_src, zone_dest, category
                      (CastSpell, Resolve, Countered, PlayLand, Draw, Discard,
                      Destroy, Sacrifice, Exile, Surveil, Put)
ManaPaid              which spell or ability the mana went to
TappedUntappedPermanent  the authoritative record of a land tapping
CounterAdded          counter_type and amount. This is how you catch a power-up
ModifiedLife          life swings with their affector
NewTurnStarted        turn boundaries
DamageDealt           combat, when the finding needs the numbers
TokenCreated          tokens, which the zone lists otherwise leave anonymous
```

**Sideboarding is free here.** Diff `j.decks[n].deck.mainDeck` against `j.decks[0]`
and you have the exact in/out for every game without asking the user to remember it.

**Opening hands and mulligans:** the seat's `ZoneType_Hand` contents at the first game
state of each game. Watch the sequence rather than one snapshot: a mulligan shows as a
seven, then another seven, then the six after bottoming, and the card that went to the
bottom is the difference. `players[].mulliganCount` confirms it.

**Pace:** the `[UnityCrossThreadLogger]<timestamp>` headers. Take the first and last
stamp bracketing each `gameNumber`, divide by that game's turn count, and log it as
`untapped-duration`. That's both players' clocks combined, which is the only thing
this source supports. Say so.

---

## The three traps

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
`isTapped` must agree with the `TappedUntappedPermanent` and `ManaPaid` annotations
for the same window. If they disagree, the annotations win.

### 2. The annotation stream is resolution order, not casting order

A spell cast in response resolves before the ability that was already on the stack, so
the log shows the response resolving first. Reading the stream top-down and calling it
a sequence of decisions gets the causality backwards.

The tell is an ability activation followed by an opponent's cast followed by that
cast resolving, with the original ability's effect landing several messages later.
That's a player tapping low, an opponent taking the window, and the first player's
ability resolving into a board that changed underneath it.

When a finding turns on who had priority and what was open, walk that window message
by message and print the annotations in order alongside the untapped list. Don't
summarise it and don't infer it.

### 3. Object ids get reused and reassigned

`AnnotationType_ObjectIdChanged` is common, and a name resolved from a stale id map
produces lines like "sacrificed Get Lost" for a Map token. Treat a card name attached
to a `Sacrifice` or an unexplained `Put` as unreliable unless the object was tracked
through its id changes. If a single event looks strange and nothing depends on it,
leave it out rather than writing a finding on it.

---

## When the replay viewer is still the right tool

- The user wants to see a board, or the review needs a screenshot.
- One specific moment needs a visual check that the log made ambiguous.
- The log endpoint 404s or the upload is incomplete.

The page renders client-side, so read it with the JavaScript-rendering browser tools
rather than a plain fetch. It steps through `?gameStateId=N`. If the page shows a
login wall, say so and ask the user to sign in rather than working around it. Some
panels are Premium-gated: name the one that's locked and work from what's visible.

---

## The rule this note exists to enforce

**No claim about available mana without the tap trace behind it.** "He was tapped out",
"she had the counter up", "he could have paid the {3}" are the sentences that decide
reviews, and each one is a specific set of lands in a specific message. Print them,
count them, then write the finding.
