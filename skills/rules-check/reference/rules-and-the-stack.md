# Rules and the stack — the working summary

The baseline. Enough to recognise what kind of question you're looking at and know
which rule to go read. It's a map, not the territory: every number below points into
the Comprehensive Rules, and the CR is what you quote.

```
python rules_lookup.py 117.3b
python rules_lookup.py --search "state-based"
python rules_lookup.py --glossary "deathtouch"
```

Checked against **MagicCompRules 20260819**. The CR is revised with every set, so
re-check anything that matters. The section numbers below have been stable for years;
the sub-rules move.

---

## The four things almost every rules question is really about

1. **Priority.** Who can act right now, and did the window to respond already close?
2. **The stack.** What order things resolve in, and what can still be answered.
3. **State-based actions.** What the game cleans up on its own, without anyone doing
   anything, and when.
4. **Layers.** What a permanent's characteristics actually are once six effects are
   arguing about it.

If a question doesn't reduce to one of those, it's usually a card-specific templating
question, and the answer is on the card's Oracle text rather than in the CR.

---

## Priority (rule 117)

Nothing happens in Magic unless a player has priority and chooses to act. That single
sentence resolves most "could they have responded" arguments.

- **117.3b** The active player receives priority after a spell or ability resolves,
  other than a mana ability.
- Priority passes in turn order. When all players pass in succession on a non-empty
  stack, the top object resolves. When they pass on an empty stack, the step or phase
  ends.
- **Two steps give nobody priority:** the untap step, and the cleanup step in the
  usual case. That's why you can't respond to an untap.
- Mana abilities don't use the stack and don't pass priority.

**The common table mistake:** thinking you get a window that you don't. If a player
passes priority and the spell resolves, "I wanted to respond" is too late. In a VOD
review, this is the difference between a punt and a rules misunderstanding, so check
it rather than assuming.

## The stack (rule 405, resolution at 608)

Last in, first out. Each object resolves one at a time, and players get priority
between each one.

- Spells, activated abilities, and triggered abilities use the stack.
- **Mana abilities, special actions, and state-based actions do not.** Playing a land
  is a special action; it can't be responded to.
- **608** covers resolution: targets are checked again on resolution, and a spell with
  all its targets now illegal doesn't resolve at all.
- **702.61, split second** stops other spells and non-mana activated abilities while
  it's on the stack. Triggers still trigger and still go on the stack.

**Targets are locked when the spell is cast, and re-checked when it resolves.** That's
two separate moments, and the gap between them is where most stack tricks live.

## Triggered abilities (rule 603)

A trigger goes on the stack the next time a player would receive priority, not the
instant its condition is met. So several triggers can pile up from one event and then
all go on the stack together.

- The controller of the triggers chooses the order theirs go on the stack. Active
  player's triggers go on first, so the non-active player's resolve first.
- **State triggers** ("whenever you have no cards in hand") trigger again as soon as
  they resolve if the condition is still true. That's a loop to watch for.
- "Whenever" and "at the beginning of" are triggers. "When you cast" is a trigger and
  resolves before the spell it triggered off.

## State-based actions (rule 704)

The game's housekeeping. Checked whenever a player would receive priority, all
applicable ones performed **simultaneously as a single event**, then checked again
until none apply. They don't use the stack and nobody can respond to them.

The ones that come up:

| Rule | What it does |
|---|---|
| 704.5a | 0 or less life, that player loses |
| 704.5b | drew from an empty library, that player loses |
| 704.5c | ten or more poison counters, that player loses |
| 704.5f | creature with toughness 0 or less goes to the graveyard, and regeneration can't stop it |
| 704.5g | lethal damage marked, creature is destroyed |
| 704.5h | any damage from a deathtouch source, creature is destroyed |
| 704.5i | planeswalker at 0 loyalty goes to the graveyard |
| 704.5j | the legend rule |
| 704.5m | Aura attached to something illegal goes to the graveyard |
| 704.5q | +1/+1 and -1/-1 counters annihilate in pairs |

**The distinction that matters most:** 704.5f (toughness 0 or less) is not destruction,
so indestructible doesn't save it and regeneration can't replace it. 704.5g (lethal
damage) is destruction, so both do.

**Timing trap:** a player at 0 life doesn't lose the instant the damage resolves. They
lose the next time state-based actions are checked, which is before anyone gets
priority again. Practically the same, and it matters when a replacement effect or a
simultaneous trigger is involved.

## Layers (rule 613)

Continuous effects apply in a fixed order, and the order changes the answer. Seven
layers, applied in sequence:

| Layer | What applies |
|---|---|
| 1 | copiable values |
| 2 | control-changing |
| 3 | text-changing |
| 4 | type-changing |
| 5 | color-changing |
| 6 | ability-adding, keyword counters, ability-removing |
| 7 | power and toughness |

Layer 7 splits again:

| Sublayer | What applies |
|---|---|
| 7a | characteristic-defining abilities that set P/T |
| 7b | effects that set P/T to a specific number |
| 7c | effects and counters that modify P/T |
| 7d | effects that switch P/T |

**Why this bites:** a set effect in 7b overwrites a pump in 7c only if the pump came
first in the ordering, and it doesn't, so the pump still applies afterwards. Counters
live in 7c, so a counter on a creature whose power was set to 1 still adds. Within a
layer, timestamps and dependency decide.

Anyone reasoning about layers from memory is wrong more often than they think.
Go read 613, every time.

## Combat (rules 506 through 511)

Five steps in order: beginning of combat, declare attackers, declare blockers, combat
damage, end of combat.

- **508** declare attackers, **509** declare blockers, **510** combat damage.
- Attackers and blockers are declared all at once, and the declaration itself doesn't
  use the stack. Triggers from attacking or blocking go on the stack afterwards.
- A blocked creature stays blocked even if the blocker leaves. It deals no damage
  unless it has trample or the blocker is removed after damage assignment order is
  set.
- First strike creates an extra combat damage step.

**In a VOD review, the combat step is where the countable mistakes are.** Damage is
arithmetic, so the alternative line can be shown rather than argued.

## Replacement effects (rule 614) and prevention (615)

They never use the stack and they aren't triggers. They modify an event as it happens,
so there's no window to respond to one.

"If" and "instead" in a static ability is usually a replacement effect. The affected
player or the controller of the affected object chooses which applies first when
several would.

---

## Where the rules stop and the tournament rules start

The CR governs the game. It doesn't govern the match.

Anything about **deck registration, sideboarding between games, slow play, judge
calls, taking back an action, missed triggers, or match structure** lives in the
Magic Tournament Rules and the Infraction Procedure Guide, published separately by
WotC. Say that plainly rather than reaching for a CR number that isn't there.

Digital play differs too. **MTG Arena and MTGO enforce the rules automatically and
make some choices for you**, including trigger ordering defaults and auto-tapping.
A play that looks wrong in an Arena replay is sometimes the client's choice rather
than the pilot's. Check before scoring it against a player in a review.

---

## The one-line version

Priority decides who can act. The stack decides in what order. State-based actions
clean up between. Layers decide what things actually are. Everything else is on the
card.
