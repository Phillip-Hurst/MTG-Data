#!/usr/bin/env python3
"""
untapped_log.py - pull Arena games from untapped.gg and turn them into
play-by-plays a review can read. The input side of a batch vod-review.

untapped serves two things without a sign-in, and this reads both:

  the games index   every match a player has in a set, with game durations,
                    play/draw and opening hands
  the upload log    the full MTGA client log for one match (GRE messages), the
                    same data the replay page renders from

The replay page itself draws to a canvas, so reading it in a browser gets
nothing. The log is better anyway: it has both players' plays, every draw,
both decklists per game, and the hands offered at each mulligan.

    python untapped_log.py matches --user USER_ID --player PLAYER_ID --set FRA
    python untapped_log.py matches ... --constructed --since 2026-10-01
    python untapped_log.py fetch SHORT_ID [SHORT_ID ...]
    python untapped_log.py fetch --from-matches --constructed --since 2026-10-01
    python untapped_log.py parse SHORT_ID [SHORT_ID ...]
    python untapped_log.py parse --all

The user and player ids are in the profile URL:
    mtga.untapped.gg/profile/<USER_ID>/<PLAYER_ID>

Everything lands in `untapped_logs/` next to this script (override with
--dir). That folder is the user's own games and the opponents' names, so it is
gitignored and never ships.

For each match, `parse` writes:
    <id>.txt          the play-by-play: a board and hand snapshot at the start
                      of every turn, then every draw, land, cast, attack, block,
                      damage and life change, in order
    <id>.games.json   per game: result, play/draw, mulligans, every hand
                      offered, the kept hand with a SUGGESTED composition and
                      a SUGGESTED outcome (screwed/flooded/neither),
                      duration, turns, and the boarding diff with size_change

The composition is a suggestion from card types and rules text. A card that
does two jobs goes where the deck uses it, which no heuristic knows, so the
reviewer checks it before it reaches the ledger.

Stdlib only. Exit codes: 0 clean, 1 could not run, 2 ran and skipped something
(a match that would not download, a log that would not parse). Every skip is
listed at the end with its reason.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(SCRIPT_DIR, "untapped_logs")
API = "https://api.mtga.untapped.gg/api/v1"
CARDS_URL = "https://mtgajson.untapped.gg/v1/latest/cards.json"
LOC_URL = "https://mtgajson.untapped.gg/v1/latest/loc_en.json"
CARD_CACHE_DAYS = 7
USER_AGENT = "mtg-data untapped_log.py"

# Events that are constructed play rather than limited.
CONSTRUCTED_EVENTS = ("Ladder", "Traditional_Ladder", "DirectGame",
                      "DirectGameTournamentMode", "Play", "Traditional_Play")
LIMITED_MARKERS = ("Draft", "Sealed", "Cube", "Jumpstart")

# Arena card type ids, from cards.json `types`.
T_ARTIFACT, T_CREATURE, T_ENCHANTMENT, T_INSTANT, T_LAND = 1, 2, 3, 4, 5
T_PLANESWALKER, T_SORCERY, T_BATTLE = 8, 10, 11
THREAT_TYPES = {T_CREATURE, T_PLANESWALKER, T_BATTLE}

# Rules-text cues for the composition suggestion, checked in this order.
MANA_RE = re.compile(r"\{oT\}: Add|Add one mana|Add \{o", re.I)
INTERACTION_RE = re.compile(
    r"destroy|exile (?:target|all|up to)|exiles? (?:a|an) (?:creature|card)|"
    r"counter target|deals? \d+ damage|"
    r"deals? X damage|return target [^.]*to its owner'?s hand|"
    r"return up to one other target|reveals? (?:their|his|her) hand|"
    r"(?:opponent|player)s? [^.]*(?:discards?|sacrifices?)|"
    r"-\d+/-\d+|gets? -", re.I)
CARD_ADVANTAGE_RE = re.compile(
    r"draw|look at the top|surveil|scry|empower jace|search your library|"
    r"put .* into your hand", re.I)


# --------------------------------------------------------------- network

def _get(url, retries=4, pause=3.0):
    """GET with a backoff on 429. Returns bytes, or raises the last error."""
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 and attempt + 1 < retries:
                time.sleep(pause * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            if attempt + 1 < retries:
                time.sleep(pause)
                continue
            raise
    raise last


# --------------------------------------------------------------- card data

class Cards:
    """grpId -> name, types, rules text. Loaded from untapped's own card files."""

    def __init__(self, cards, loc):
        text = {x["id"]: x["text"] for x in loc}
        self.name, self.types, self.rules = {}, {}, {}
        for c in cards:
            g = c["grpid"]
            self.name[g] = text.get(c.get("titleId"), "#%d" % g)
            self.types[g] = set(c.get("types") or [])
            self.rules[g] = " ".join(
                text.get(a.get("TextId"), "") for a in c.get("abilities") or [])
        self.by_name = {}
        for g, n in self.name.items():
            self.by_name.setdefault(n, g)

    def nm(self, grp):
        return self.name.get(grp, "#%s" % grp)

    def is_land(self, name):
        return T_LAND in self.types.get(self.by_name.get(name), set())

    def role(self, name):
        """One of lands/threats/interaction/card_advantage/other. A suggestion."""
        g = self.by_name.get(name)
        types = self.types.get(g, set())
        if T_LAND in types:
            return "lands"
        if types & THREAT_TYPES:
            return "threats"
        rules = self.rules.get(g, "")
        if T_ARTIFACT in types and MANA_RE.search(rules):
            return "other"
        if INTERACTION_RE.search(rules):
            return "interaction"
        if CARD_ADVANTAGE_RE.search(rules):
            return "card_advantage"
        return "other"

    def composition(self, hand):
        comp = {"lands": 0, "threats": 0, "interaction": 0,
                "card_advantage": 0, "other": 0}
        for card in hand:
            comp[self.role(card)] += 1
        return comp


def load_cards(folder, refresh=False):
    """Card data cached under <folder>/_cards, refetched when a week old."""
    cache = os.path.join(folder, "_cards")
    os.makedirs(cache, exist_ok=True)
    paths = {}
    for name, url in (("cards.json", CARDS_URL), ("loc_en.json", LOC_URL)):
        path = os.path.join(cache, name)
        stale = (not os.path.exists(path) or refresh or
                 time.time() - os.path.getmtime(path) > CARD_CACHE_DAYS * 86400)
        if stale:
            data = _get(url)
            with open(path, "wb") as fh:
                fh.write(data)
        paths[name] = path
    with open(paths["cards.json"], encoding="utf-8") as fh:
        cards = json.load(fh)
    with open(paths["loc_en.json"], encoding="utf-8") as fh:
        loc = json.load(fh)
    return Cards(cards, loc)


# --------------------------------------------------------------- the index

def fetch_matches(user, player, card_set):
    url = "%s/games/users/%s/players/%s/?card_set=%s" % (
        API, user, player, card_set)
    return json.loads(_get(url))


def is_constructed(event_name):
    if any(m in (event_name or "") for m in LIMITED_MARKERS):
        return False
    return (event_name or "") in CONSTRUCTED_EVENTS or "Constructed" in (event_name or "")


def match_rows(matches, constructed=False, since=None):
    """Summary rows for the index. Skips are returned, never dropped silently."""
    rows, skipped = [], []
    for m in matches:
        start = m.get("match_start")
        if not isinstance(start, (int, float)):
            skipped.append((m.get("short_id"), "no match_start"))
            continue
        when = datetime.fromtimestamp(start / 1000, tz=timezone.utc)
        if since and when.date().isoformat() < since:
            continue
        if constructed and not is_constructed(m.get("event_name")):
            continue
        me = m.get("friendly_team_id")
        games = []
        for g in m.get("games") or []:
            games.append("%s%s" % (
                "w" if g.get("winning_team_id") == me else "l",
                "P" if g.get("active_player_id") == m.get("friendly_system_seat_id")
                else "D"))
        rows.append({
            "short_id": m.get("short_id"),
            "utc": when.strftime("%Y-%m-%d %H:%M"),
            "event": m.get("event_name"),
            "deck": m.get("friendly_deck_name"),
            "result": "W" if m.get("winning_team_id") == me else "L",
            "games": " ".join(games),
            "opponent": ", ".join(o.get("player_name", "?")
                                  for o in m.get("opponents") or []),
        })
    return rows, skipped


# --------------------------------------------------------------- the log

def chunks(log):
    """(header, json object) for every message in the raw client log."""
    for part in re.split(r"^\[UnityCrossThreadLogger\]", log, flags=re.M):
        nl = part.find("\n")
        body = part[nl + 1:] if nl >= 0 else ""
        j = body.find("{")
        if j < 0:
            continue
        try:
            obj = json.JSONDecoder().raw_decode(body[j:])[0]
        except ValueError:
            continue
        yield part[:nl], obj


def parse_log(doc, cards, seat=None):
    """
    Walk one upload-log document. Returns (seat, opponent, games).

    `seat` can be passed from the games index; otherwise it is read from the
    room state by matching the uploader's player id.
    """
    me_id = doc.get("playerId")
    opp = None
    games, g = [], None
    objs, zones = {}, {}
    cur_turn = None
    seen = set()

    def new_game(n):
        return {"n": n, "events": [], "mull": [], "offered": [], "hand0": None,
                "first": None, "result": None, "reason": None, "turns": None,
                "opp_cards": set(), "life": {}, "my_turns": [], "draws": []}

    for _, o in chunks(doc.get("log", "")):
        room = o.get("matchGameRoomStateChangedEvent")
        if room:
            cfg = room.get("gameRoomInfo", {}).get("gameRoomConfig", {})
            for p in cfg.get("reservedPlayers", []):
                if p.get("userId") == me_id:
                    seat = p.get("systemSeatId")
                else:
                    opp = p.get("playerName")
            continue
        payload = o.get("payload")
        if isinstance(payload, dict):
            if payload.get("type") == "ClientMessageType_MulliganResp" and g:
                g["mull"].append(payload["mulliganResp"]["decision"]
                                 .replace("MulliganOption_", ""))
            continue
        ev = o.get("greToClientEvent")
        if not ev:
            continue
        for m in ev.get("greToClientMessages", []):
            if m.get("type") == "GREMessageType_MulliganReq" and g is not None:
                hz = [z for z in zones.values()
                      if z.get("type") == "ZoneType_Hand"
                      and z.get("ownerSeatId") == seat]
                if hz:
                    g["offered"].append([cards.nm(objs[i]["grpId"])
                                         for i in hz[0].get("objectInstanceIds", [])
                                         if i in objs])
            gs = m.get("gameStateMessage")
            if not gs:
                continue
            gi = gs.get("gameInfo", {})
            if gi.get("gameNumber") and (g is None or g["n"] != gi["gameNumber"]):
                g = new_game(gi["gameNumber"])
                games.append(g)
                objs, zones, cur_turn = {}, {}, None
            if g is None:
                continue
            for z in gs.get("zones", []):
                zones[z["zoneId"]] = z
            for ob in gs.get("gameObjects", []):
                objs[ob["instanceId"]] = ob
                who = "ME" if ob.get("controllerSeatId") == seat else "OPP"
                if (ob.get("type") == "GameObjectType_Card"
                        and ob.get("ownerSeatId") != seat
                        and ob.get("visibility") == "Visibility_Public"):
                    g["opp_cards"].add(cards.nm(ob["grpId"]))
                if ob.get("attackState") in ("AttackState_Attacking",
                                             "AttackState_Declared"):
                    key = (g["n"], cur_turn, "a", ob["instanceId"])
                    if key not in seen:
                        seen.add(key)
                        g["events"].append("%s attack: %s %s/%s" % (
                            who, cards.nm(ob["grpId"]),
                            ob.get("power", {}).get("value", "?"),
                            ob.get("toughness", {}).get("value", "?")))
                if ob.get("blockState") == "BlockState_Blocking" and ob.get("blockInfo"):
                    key = (g["n"], cur_turn, "b", ob["instanceId"])
                    if key not in seen:
                        seen.add(key)
                        tgt = [cards.nm(objs[t]["grpId"])
                               for t in ob["blockInfo"].get("attackerIds", [])
                               if t in objs]
                        g["events"].append("%s block: %s blocks %s" % (
                            who, cards.nm(ob["grpId"]), ", ".join(tgt)))
            for p in gs.get("players", []):
                if "lifeTotal" in p:
                    s = p["systemSeatNumber"]
                    old = g["life"].get(s)
                    g["life"][s] = p["lifeTotal"]
                    if old is not None and old != p["lifeTotal"]:
                        g["events"].append("  life %s %s->%s" % (
                            "ME" if s == seat else "OPP", old, p["lifeTotal"]))
            ti = gs.get("turnInfo", {})
            if ti.get("turnNumber") and ti["turnNumber"] != cur_turn:
                cur_turn = ti["turnNumber"]
                active = ti.get("activePlayer")
                if g["first"] is None and cur_turn == 1:
                    g["first"] = "play" if active == seat else "draw"
                hand = _zone_cards(zones, objs, cards, "ZoneType_Hand", seat)
                if g["hand0"] is None:
                    g["hand0"] = hand
                if active == seat:
                    mine = [x for x in _board(zones, objs, cards, seat, True)]
                    g["my_turns"].append({
                        "lands_in_play": sum(1 for x in mine
                                             if cards.is_land(x.replace("(T)", ""))),
                        "lands_in_hand": sum(1 for x in hand if cards.is_land(x)),
                    })
                ohand = [z for z in zones.values()
                         if z.get("type") == "ZoneType_Hand"
                         and z.get("ownerSeatId") not in (None, seat)]
                g["events"].append(
                    "=== T%d %s | life me %s opp %s | my hand: %s | opp hand %s\n"
                    "   my board: %s\n   opp board: %s" % (
                        cur_turn, "ME" if active == seat else "OPP",
                        g["life"].get(seat), _other_life(g["life"], seat),
                        ", ".join(hand),
                        len(ohand[0].get("objectInstanceIds", [])) if ohand else "?",
                        ", ".join(_board(zones, objs, cards, seat, True)),
                        ", ".join(_board(zones, objs, cards, seat, False))))
            for a in gs.get("annotations", []):
                types = a.get("type", [])
                det = {x["key"]: (x.get("valueInt32") or x.get("valueString") or [None])
                       for x in a.get("details", [])}
                if "AnnotationType_ZoneTransfer" in types:
                    cat = (det.get("category") or [""])[0]
                    for i in a.get("affectedIds", []):
                        ob = objs.get(i)
                        if not ob:
                            continue
                        who = "ME" if ob.get("ownerSeatId") == seat else "OPP"
                        if cat == "Draw":
                            if who == "ME":
                                g["events"].append("ME draw %s" % cards.nm(ob["grpId"]))
                                if cur_turn is not None:
                                    g["draws"].append(cards.nm(ob["grpId"]))
                            continue
                        dest = zones.get((det.get("zone_dest") or [None])[0], {})
                        g["events"].append("%s %s: %s -> %s" % (
                            who, cat or "move", cards.nm(ob["grpId"]),
                            dest.get("type", "?").replace("ZoneType_", "")))
                if "AnnotationType_DamageDealt" in types:
                    src = objs.get(a.get("affectorId"))
                    if src:
                        tgt = []
                        for x in a.get("affectedIds", []):
                            if x in (1, 2):
                                tgt.append("ME" if x == seat else "OPP")
                            elif x in objs:
                                tgt.append(cards.nm(objs[x]["grpId"]))
                        g["events"].append("  dmg %s from %s to %s" % (
                            (det.get("damage") or [None])[0],
                            cards.nm(src["grpId"]), ", ".join(tgt)))
            for r in gi.get("results", []):
                if r.get("scope") == "MatchScope_Game":
                    g["result"] = "W" if r.get("winningTeamId") == seat else "L"
                    g["reason"] = r.get("reason", "").replace("ResultReason_", "")
                    g["turns"] = cur_turn
    return seat, opp, games


def _other_life(life, seat):
    others = [v for k, v in life.items() if k != seat]
    return others[0] if others else None


def _zone_cards(zones, objs, cards, ztype, seat):
    z = [z for z in zones.values()
         if z.get("type") == ztype and z.get("ownerSeatId") == seat]
    if not z:
        return []
    return [cards.nm(objs[i]["grpId"]) for i in z[0].get("objectInstanceIds", [])
            if i in objs]


def _board(zones, objs, cards, seat, mine):
    out = []
    for z in zones.values():
        if z.get("type") != "ZoneType_Battlefield":
            continue
        for i in z.get("objectInstanceIds", []):
            ob = objs.get(i)
            if not ob or ob.get("type") != "GameObjectType_Card":
                continue
            if (ob.get("controllerSeatId") == seat) != mine:
                continue
            out.append(cards.nm(ob["grpId"]) + ("(T)" if ob.get("isTapped") else ""))
    return out


def suggest_outcome(game, cards):
    """
    screwed, flooded or neither, off the draws. A suggestion: colour screw is
    invisible to a land count, so a reviewer who saw one overrides it.

    screwed  started one of his first five turns with fewer lands in play than
             turns taken and no land in hand to play
    flooded  six or more draws and at least 60% of them lands
    """
    for k, t in enumerate(game.get("my_turns", [])[:5]):
        if t["lands_in_play"] < k and t["lands_in_hand"] == 0:
            return "screwed"
    draws = game.get("draws", [])
    if len(draws) >= 6:
        lands = sum(1 for d in draws if cards.is_land(d))
        if lands / len(draws) >= 0.6:
            return "flooded"
    if not game.get("my_turns"):
        return "unknown"
    return "neither"


def board_diff(decks, cards):
    """Per post-board game: in, out and size_change, off the submitted lists."""
    by_game = {}
    for d in decks or []:
        by_game[d.get("game")] = Counter(
            cards.nm(x) for x in (d.get("deck") or {}).get("mainDeck", []))
    out = {}
    for n in sorted(k for k in by_game if isinstance(k, int)):
        if n - 1 not in by_game:
            continue
        before, after = by_game[n - 1], by_game[n]
        out[n] = {
            "in": sorted((after - before).elements()),
            "out": sorted((before - after).elements()),
            "size_change": sum(after.values()) - sum(before.values()),
        }
    return out


def summarise(doc, cards, index_row=None):
    """The per-game JSON a review starts from."""
    seat = (index_row or {}).get("friendly_system_seat_id")
    seat, opp, games = parse_log(doc, cards, seat)
    diffs = board_diff(doc.get("decks"), cards)
    index_games = (index_row or {}).get("games") or []
    out = []
    for i, g in enumerate(games):
        ig = index_games[i] if i < len(index_games) else {}
        dur = ig.get("game_duration_seconds")
        hand = g["hand0"] or []
        comp = cards.composition(hand) if hand else None
        out.append({
            "game": g["n"],
            "result": g["result"],
            "reason": g["reason"],
            "on_the_play": None if g["first"] is None else g["first"] == "play",
            "mulligans": g["mull"],
            "hands_offered": g["offered"],
            "kept": hand,
            "kept_lands": sum(1 for c in hand if cards.is_land(c)),
            "suggested_composition": comp,
            "suggested_outcome": suggest_outcome(g, cards),
            "turns": g["turns"],
            "duration_seconds": dur,
            "seconds_per_turn": round(dur / g["turns"], 1)
            if dur and g["turns"] else None,
            "sideboard": diffs.get(g["n"]),
            "opponent_public_cards": sorted(g["opp_cards"]),
        })
    return {"opponent": opp, "seat": seat, "games": out}, games


def render_txt(short_id, summary, games):
    lines = ["# %s vs %s" % (short_id, summary["opponent"])]
    for s, g in zip(summary["games"], games):
        lines.append("\n## Game %s: %s (%s) | %s | turns %s | mulligans %s" % (
            s["game"], s["result"], s["reason"],
            {True: "play", False: "draw", None: "?"}[s["on_the_play"]],
            s["turns"], s["mulligans"]))
        for k, h in enumerate(s["hands_offered"]):
            lines.append("  hand offered #%d: %s" % (k + 1, ", ".join(h)))
        if s["suggested_composition"]:
            lines.append("  kept: %s" % ", ".join(s["kept"]))
            lines.append("  suggested composition: %s" % s["suggested_composition"])
            lines.append("  suggested outcome: %s" % s["suggested_outcome"])
        if s["sideboard"]:
            lines.append("  boarded: %s" % s["sideboard"])
        if s["seconds_per_turn"]:
            lines.append("  %ss over %s turns (%s s/turn, both clocks)" % (
                s["duration_seconds"], s["turns"], s["seconds_per_turn"]))
        lines.append("  opp public cards: " + ", ".join(s["opponent_public_cards"]))
        lines.extend(g["events"])
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- commands

def _index_path(folder):
    return os.path.join(folder, "_matches.json")


def cmd_matches(args):
    matches = fetch_matches(args.user, args.player, args.set)
    os.makedirs(args.dir, exist_ok=True)
    with open(_index_path(args.dir), "w", encoding="utf-8") as fh:
        json.dump(matches, fh)
    rows, skipped = match_rows(matches, args.constructed, args.since)
    for r in rows:
        print("%(short_id)s  %(utc)s  %(event)-26s %(deck)-20s %(result)s  "
              "%(games)-10s vs %(opponent)s" % r)
    print("\n%d match(es) listed of %d in the index. Saved to %s"
          % (len(rows), len(matches), _index_path(args.dir)))
    for sid, why in skipped:
        print("  skipped %s: %s" % (sid, why))
    return 2 if skipped else 0


def _load_index(folder):
    path = _index_path(folder)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _ids_from_args(args):
    if getattr(args, "from_matches", False):
        rows, _ = match_rows(_load_index(args.dir), args.constructed, args.since)
        return [r["short_id"] for r in rows]
    return list(args.ids)


def cmd_fetch(args):
    ids = _ids_from_args(args)
    if not ids:
        print("Nothing to fetch. Pass short ids, or run `matches` first and use "
              "--from-matches.")
        return 1
    os.makedirs(args.dir, exist_ok=True)
    got, have, failed = 0, 0, []
    for sid in ids:
        path = os.path.join(args.dir, "%s.json" % sid)
        if os.path.exists(path) and not args.refresh:
            have += 1
            continue
        try:
            data = _get("%s/upload-log/%s" % (API, sid))
            json.loads(data)                       # refuse to save a non-log
        except Exception as e:                     # noqa: BLE001 - reported below
            failed.append((sid, str(e)))
            continue
        with open(path, "wb") as fh:
            fh.write(data)
        got += 1
        time.sleep(args.pause)
    print("Fetched %d, already had %d, failed %d." % (got, have, len(failed)))
    for sid, why in failed:
        print("  failed %s: %s" % (sid, why))
    return 2 if failed else 0


def cmd_parse(args):
    if args.all:
        ids = sorted(f[:-5] for f in os.listdir(args.dir)
                     if f.endswith(".json") and not f.startswith("_")
                     and not f.endswith(".games.json"))
    else:
        ids = _ids_from_args(args)
    if not ids:
        print("Nothing to parse.")
        return 1
    cards = load_cards(args.dir, args.refresh_cards)
    index = {m.get("short_id"): m for m in _load_index(args.dir)}
    done, failed = 0, []
    for sid in ids:
        path = os.path.join(args.dir, "%s.json" % sid)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            failed.append((sid, "unreadable: %s" % e))
            continue
        summary, games = summarise(doc, cards, index.get(sid))
        if not games:
            failed.append((sid, "no games found in the log"))
            continue
        if summary["seat"] is None:
            failed.append((sid, "could not tell which seat was yours"))
            continue
        with open(os.path.join(args.dir, "%s.games.json" % sid), "w",
                  encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1, ensure_ascii=False)
        with open(os.path.join(args.dir, "%s.txt" % sid), "w",
                  encoding="utf-8") as fh:
            fh.write(render_txt(sid, summary, games))
        done += 1
    print("Parsed %d match(es) into %s, %d failed." % (done, args.dir, len(failed)))
    for sid, why in failed:
        print("  failed %s: %s" % (sid, why))
    return 2 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default=DEFAULT_DIR,
                    help="Where logs and parsed output go (default untapped_logs/)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def filters(p):
        p.add_argument("--constructed", action="store_true",
                       help="Constructed events only, no draft or sealed")
        p.add_argument("--since", help="UTC date YYYY-MM-DD")

    m = sub.add_parser("matches", help="List a player's matches in a set")
    m.add_argument("--user", required=True)
    m.add_argument("--player", required=True)
    m.add_argument("--set", required=True, help="Arena set code, e.g. FRA")
    filters(m)

    f = sub.add_parser("fetch", help="Download upload logs")
    f.add_argument("ids", nargs="*")
    f.add_argument("--from-matches", action="store_true")
    f.add_argument("--refresh", action="store_true")
    f.add_argument("--pause", type=float, default=1.0,
                   help="Seconds between downloads (untapped rate-limits)")
    filters(f)

    p = sub.add_parser("parse", help="Turn logs into play-by-plays")
    p.add_argument("ids", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--from-matches", action="store_true")
    p.add_argument("--refresh-cards", action="store_true")
    filters(p)

    args = ap.parse_args(argv)
    try:
        return {"matches": cmd_matches, "fetch": cmd_fetch,
                "parse": cmd_parse}[args.cmd](args)
    except (urllib.error.URLError, OSError) as e:
        print("Could not run: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
