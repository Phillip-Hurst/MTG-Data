---
name: rules-check
description: Answer Magic: The Gathering rules questions from the actual Comprehensive Rules rather than from memory. Covers priority, the stack, triggered abilities, state-based actions, layers, combat, and replacement effects, and knows where the rules stop and the tournament rules start. Use whenever someone asks how an interaction works, whether a response was possible, what order things resolve in, why a creature died or survived, or what a card actually does in a corner case. Trigger on phrasings like "can I respond to that", "does this trigger first", "how do layers work here", "why did my creature die", "what happens if both", "is that legal", "does indestructible stop this", "what order do these resolve", "look up rule 704", "what does the rulebook say about", or any question about an interaction between two or more cards.
---

# rules-check

One job: answer the rules question from the document, with the rule number, so the
answer survives being challenged.

## Related skills in this plugin

| Skill | What it's for | Hand off when |
|---|---|---|
| `vod-review` | Reviews your own games and finds the decisions that decided them | The question is "was that the right play" rather than "was that play legal" |
| `mtg-tournament-analysis` | Meta share, win rates, matchup matrices, card-level signal | The question turns into what's good in the format rather than what's legal in it |
| `deck-check` | Assigns the right archetype name and pushes it into the win-rate data | A deck needs naming before anything else can proceed |

`mtg-price-check` prices a Moxfield binder against Face to Face Games. It is a
separate skill and does not ship in this plugin, so point the user at it by name
rather than assuming it is installed.

---

## The hard rule

**Never answer from memory. Quote the rule.**

Rules knowledge in training data is a mix of current rules, rules from ten years ago,
and forum posts that were wrong when they were written. The Comprehensive Rules are
revised with every set release. An answer that sounds authoritative and cites nothing
is the failure mode this skill exists to prevent.

Every answer names a rule number and quotes the text. If you can't find the rule, say
you couldn't find it.

```bash
python rules_lookup.py 117.3b            # one rule, verbatim
python rules_lookup.py 704               # a whole section
python rules_lookup.py --search "split second"
python rules_lookup.py --search "legend rule" --context 2
python rules_lookup.py --glossary "deathtouch"
python rules_lookup.py --version         # what's cached, and how old
```

The script downloads the current CR from magic.wizards.com, caches it beside the
scripts, and re-downloads after 14 days or when WotC publishes a newer dated file. It
prints the CR version alongside every result, so an answer can always be traced to a
document.

**Report the version with the answer** when the interaction is at all unusual. "Rule
704.5f, CR 20260819" tells the reader what to re-check after the next set.

---

## Step 1: Work out which question it actually is

Most rules questions reduce to one of four things. Naming which one before searching
saves reading the wrong section.

| The question sounds like | It's really about | Start at |
|---|---|---|
| "Could they have responded?" | priority | 117 |
| "What resolves first?" | the stack, or trigger ordering | 405, 603 |
| "Why did it die / survive?" | state-based actions | 704 |
| "What's its power right now?" | layers | 613 |
| "Does the damage go through?" | combat | 506 to 511 |
| "It says instead / if" | replacement effects | 614 |
| "Can I take that back?" | not the CR at all | tournament rules, see below |

`reference/rules-and-the-stack.md` is the map. Read it to place the question, then go
to the CR for the answer. It carries the sub-rules that come up most, and the two
traps that catch people: toughness 0 is not destruction, and layer 7c counters still
apply after a 7b set effect.

## Step 2: Get the card text

**Every card in the question gets verified on Scryfall.** Same hard rule as the rest
of the plugin, and it matters more here than anywhere: a rules answer built on a
misremembered Oracle text is wrong no matter how right the rule is.

Oracle text is what the game uses, and it isn't always what's printed on the card.
Cards get errata. Quote the Oracle wording.

```
https://scryfall.com/search?q=!"Card Name"&unique=cards
```

If a card is from a set outside your training coverage, that changes nothing: look it
up like every other card.

## Step 3: Answer

Structure, in this order:

1. **The answer.** One sentence. Commit to it.
2. **The rule.** Number and the quoted text.
3. **Why, in sequence.** Walk the actual steps: this goes on the stack, that gets
   priority, this state-based action checks here. Sequence is what makes a rules
   answer convincing, and it's what shows your work if you got it wrong.
4. **The trap, if there is one.** The near-miss reading that's wrong, and why. Only
   when someone would plausibly land on it.

Keep it short. A rules answer that runs four paragraphs has usually stopped answering
and started lecturing.

**When the answer is genuinely uncertain**, say so and say why. A corner case with no
clean CR answer is a judge call, and pretending otherwise is worse than admitting it.
Point at the relevant rules and let the user decide.

## Step 4: Know when it isn't a CR question

The Comprehensive Rules govern the game. They don't govern the match.

**Not in the CR:** deck registration, sideboarding procedure, slow play, taking back
an action, missed triggers and their penalties, judge calls, match structure, tardiness,
communication policy. Those live in the Magic Tournament Rules and the Infraction
Procedure Guide, published separately by WotC.

Say which document the answer lives in rather than reaching for a CR number that
doesn't exist. If the user needs the actual text, point them at the WPN rules and
documents page; this skill doesn't cache those.

**Digital play differs from paper.** MTG Arena and MTGO enforce rules automatically
and make some choices on the player's behalf, including default trigger ordering and
auto-tapping. When a question comes out of a digital game, separate "what the rules
say" from "what the client did". In a VOD review that distinction decides whether a
play was a mistake at all.

---

## Rules

- **Quote the rule or say you couldn't find it.** No unsourced answers.
- **Verify every card on Scryfall.** Oracle text, not printed text, not memory.
- **Name the CR version** on anything non-obvious. The document changes.
- **Sequence beats assertion.** Walk the steps. "Because rule 704.5f" convinces
  nobody on its own.
- **Don't guess at tournament policy.** Different document, and getting it wrong at an
  event costs a game loss.
- **Uncertainty is an acceptable answer.** Judge calls exist because some cases are
  genuinely unclear.
- **One question at a time.** A rules answer that hedges across three readings of the
  question has answered none of them.
