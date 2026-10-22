"""
Tests for untapped_log.py, the input side of a batch vod-review.

Card names and ids in the fixtures are fake on purpose ("Placeholder Bolt",
grpid 900001). A real card name in a fixture stops being inert the day its text
changes or an alias starts matching it.
"""
import json
import os

from mtg_data.review import untapped_log as ul

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _card(grp, title, types, *texts):
    return {"grpid": grp, "titleId": title, "types": types,
            "abilities": [{"TextId": t} for t in texts]}


LOC = [
    {"id": 1, "text": "Placeholder Swamp"},
    {"id": 2, "text": "Placeholder Beast"},
    {"id": 3, "text": "Placeholder Bolt"},
    {"id": 4, "text": "Placeholder Insight"},
    {"id": 5, "text": "Placeholder Rock"},
    {"id": 6, "text": "Placeholder Stories"},
    {"id": 7, "text": "Placeholder Betrayal"},
    {"id": 101, "text": "Placeholder Bolt deals 3 damage to any target."},
    {"id": 102, "text": "Draw two cards."},
    {"id": 103, "text": "{oT}: Add one mana of any color."},
    {"id": 104, "text": "Draw three cards. Then discard two cards."},
    {"id": 105, "text": "Target opponent exiles a creature they control."},
]
CARDS = ul.Cards([
    _card(900001, 1, [ul.T_LAND]),
    _card(900002, 2, [ul.T_CREATURE]),
    _card(900003, 3, [ul.T_INSTANT], 101),
    _card(900004, 4, [ul.T_SORCERY], 102),
    _card(900005, 5, [ul.T_ARTIFACT], 103),
    _card(900006, 6, [ul.T_SORCERY], 104),
    _card(900007, 7, [ul.T_SORCERY], 105),
], LOC)


def test_roles_follow_type_then_rules_text():
    assert CARDS.role("Placeholder Swamp") == "lands"
    assert CARDS.role("Placeholder Beast") == "threats"
    assert CARDS.role("Placeholder Bolt") == "interaction"
    assert CARDS.role("Placeholder Insight") == "card_advantage"
    assert CARDS.role("Placeholder Rock") == "other"
    assert CARDS.role("Placeholder Betrayal") == "interaction"


def test_discarding_your_own_cards_is_not_interaction():
    """Winternight Stories read as removal on 2026-10-17 because of 'discard'."""
    assert CARDS.role("Placeholder Stories") == "card_advantage"


def test_a_composition_puts_every_card_in_exactly_one_slot():
    hand = ["Placeholder Swamp", "Placeholder Swamp", "Placeholder Beast",
            "Placeholder Bolt", "Placeholder Insight", "Placeholder Rock",
            "Placeholder Stories"]
    comp = CARDS.composition(hand)
    assert sum(comp.values()) == len(hand)
    assert comp == {"lands": 2, "threats": 1, "interaction": 1,
                    "card_advantage": 2, "other": 1}


def test_a_board_diff_records_a_deck_that_grew():
    """60 to 61 is legal; the diff says so instead of looking miscounted."""
    g1 = [900001] * 30 + [900002] * 30
    g2 = [900001] * 30 + [900002] * 29 + [900003, 900003]
    diff = ul.board_diff([{"game": 1, "deck": {"mainDeck": g1}},
                          {"game": 2, "deck": {"mainDeck": g2}}], CARDS)
    assert diff[2]["in"] == ["Placeholder Bolt", "Placeholder Bolt"]
    assert diff[2]["out"] == ["Placeholder Beast"]
    assert diff[2]["size_change"] == 1


def test_the_index_filters_constructed_and_reports_what_it_skipped():
    matches = [
        {"short_id": "AAA", "match_start": 1790000000000, "event_name":
         "Traditional_Ladder", "friendly_team_id": 1, "winning_team_id": 1,
         "friendly_system_seat_id": 1, "games": [], "opponents": []},
        {"short_id": "BBB", "match_start": 1790000000000, "event_name":
         "PremierDraft_XXX", "friendly_team_id": 1, "winning_team_id": 2,
         "games": [], "opponents": []},
        {"short_id": "CCC", "event_name": "Ladder"},
    ]
    rows, skipped = ul.match_rows(matches, constructed=True)
    assert [r["short_id"] for r in rows] == ["AAA"]
    assert skipped == [("CCC", "no match_start")]


def _gre(game_no, turn, active, zones=(), objects=(), annotations=(),
         results=()):
    gs = {"gameInfo": {"gameNumber": game_no, "results": list(results)},
          "turnInfo": {"turnNumber": turn, "activePlayer": active},
          "zones": list(zones), "gameObjects": list(objects),
          "annotations": list(annotations),
          "players": [{"systemSeatNumber": 1, "lifeTotal": 20},
                      {"systemSeatNumber": 2, "lifeTotal": 20}]}
    return {"greToClientEvent": {"greToClientMessages": [
        {"type": "GREMessageType_GameStateMessage", "gameStateMessage": gs}]}}


def test_a_minimal_log_parses_into_one_game_with_its_hand_and_result():
    hand_zone = {"zoneId": 31, "type": "ZoneType_Hand", "ownerSeatId": 1,
                 "objectInstanceIds": [11, 12]}
    objs = [{"instanceId": 11, "grpId": 900001, "type": "GameObjectType_Card",
             "ownerSeatId": 1, "controllerSeatId": 1},
            {"instanceId": 12, "grpId": 900003, "type": "GameObjectType_Card",
             "ownerSeatId": 1, "controllerSeatId": 1}]
    room = {"matchGameRoomStateChangedEvent": {"gameRoomInfo": {
        "gameRoomConfig": {"reservedPlayers": [
            {"userId": "PLAYERX", "playerName": "Placeholder Me",
             "systemSeatId": 1},
            {"userId": "PLAYERY", "playerName": "Placeholder Them",
             "systemSeatId": 2}]}}}}
    end = _gre(1, 1, 1, results=[{"scope": "MatchScope_Game",
                                  "winningTeamId": 1,
                                  "reason": "ResultReason_Concede"}])
    log = "\n".join("[UnityCrossThreadLogger]header\n" + json.dumps(o)
                    for o in (room, _gre(1, 1, 1, [hand_zone], objs), end))
    seat, opp, games = ul.parse_log({"playerId": "PLAYERX", "log": log}, CARDS)
    assert seat == 1 and opp == "Placeholder Them"
    assert len(games) == 1
    g = games[0]
    assert g["first"] == "play"
    assert g["hand0"] == ["Placeholder Swamp", "Placeholder Bolt"]
    assert g["result"] == "W" and g["reason"] == "Concede"


def test_untapped_logs_never_ship_or_commit():
    from pathlib import Path

    import build_plugin as package
    assert not package.should_ship(Path("untapped_logs/PLACEHOLDER0000.json"))
    with open(os.path.join(SCRIPT_DIR, ".gitignore"), encoding="utf-8") as fh:
        assert "untapped_logs/" in fh.read().split()


def test_outcome_suggestion_reads_missed_drops_and_land_heavy_draws():
    def t(play, hand):
        return {"lands_in_play": play, "lands_in_hand": hand}

    screwed = {"my_turns": [t(0, 1), t(1, 1), t(2, 0), t(2, 0)], "draws": []}
    assert ul.suggest_outcome(screwed, CARDS) == "screwed"
    # Short a land but holding one is a choice, not a screw.
    held = {"my_turns": [t(0, 1), t(1, 1), t(1, 1)], "draws": []}
    assert ul.suggest_outcome(held, CARDS) == "neither"
    flooded = {"my_turns": [t(0, 1), t(1, 1), t(2, 1)],
               "draws": ["Placeholder Swamp"] * 4 + ["Placeholder Bolt"] * 2}
    assert ul.suggest_outcome(flooded, CARDS) == "flooded"
    assert ul.suggest_outcome({"my_turns": [], "draws": []}, CARDS) == "unknown"
