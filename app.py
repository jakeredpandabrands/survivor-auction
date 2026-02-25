"""Survivor Auction — Outwit, outbid, outlast."""

import json
import random
import string
import time
import uuid
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, jsonify

# Constants
STARTING_BUDGET = 1000
STARTING_BID = 20
BID_TIMER_SECONDS = 30
BID_EXTEND_SECONDS = 30  # extend timer by this much on new bid
MIN_PLAYERS = 2
MAX_PLAYERS = 8

# Load items
ITEMS_PATH = Path(__file__).parent / "items.json"
try:
    with open(ITEMS_PATH, encoding="utf-8") as f:
        ALL_ITEMS = json.load(f)
except Exception as e:
    import sys
    print(f"FATAL: Could not load items.json: {e}", file=sys.stderr)
    raise

app = Flask(__name__)

# In-memory game state: game_id -> game dict
games: dict[str, dict] = {}


GAME_CODE_LEN = 6
GAME_CODE_CHARS = string.ascii_uppercase + string.digits


def normalize_game_code(raw: str) -> str:
    """Uppercase, alphanumeric only."""
    return "".join(c for c in (raw or "").upper() if c in GAME_CODE_CHARS)[:GAME_CODE_LEN]


def player_id() -> str:
    """Generate player ID."""
    return str(uuid.uuid4())[:8]


def draw_items(count: int) -> list[dict]:
    """Shuffle and draw N items from the mega-list. Items are {name} only."""
    shuffled = random.sample(ALL_ITEMS, min(count, len(ALL_ITEMS)))
    return [{"name": item["name"]} for item in shuffled]


def pick_mystery_rounds(total: int) -> set[int]:
    """Pick 10-20% of round indices as mystery items."""
    n = max(0, int(total * random.uniform(0.10, 0.20)))
    return set(random.sample(range(total), min(n, total)))


def create_game(game_code: str, host_name: str) -> dict | None:
    """Create a new game with host-chosen code. Host auto-joins as first player."""
    code = normalize_game_code(game_code)
    if len(code) < 4:
        return None
    if code in games:
        return None
    # Items and rounds determined at start_game
    games[code] = {
        "id": code,
        "players": [],
        "items": [],
        "rounds_total": 0,
        "mystery_rounds": set(),
        "current_round": 0,
        "phase": "lobby",
        "budgets": {},
        "collections": {},
        "current_high_bid": 0,
        "current_leader": None,
        "bid_timer_end": None,
        "resolved_item": None,
        "winner": None,
        "votes": {},
    }
    g = games[code]
    p = add_player(code, host_name)
    return g if p else None


def get_game(gid: str) -> dict | None:
    """Get game by ID (game code)."""
    return games.get(normalize_game_code(gid))


def add_player(gid: str, name: str) -> dict | None:
    """Add player to game."""
    g = get_game(gid)
    if not g or len(g["players"]) >= MAX_PLAYERS:
        return None
    pid = player_id()
    g["players"].append({"id": pid, "name": name})
    g["budgets"][pid] = STARTING_BUDGET
    g["collections"][pid] = []
    return {"id": pid, "name": name}


def start_game(gid: str) -> bool:
    """Start game if enough players. Set dynamic rounds, draw items, pick mystery rounds."""
    g = get_game(gid)
    if not g or len(g["players"]) < MIN_PLAYERS:
        return False
    n = len(g["players"])
    rounds_total = random.randint(n * 2, n * 5)
    g["rounds_total"] = rounds_total
    g["items"] = draw_items(rounds_total)
    g["mystery_rounds"] = pick_mystery_rounds(rounds_total)
    g["phase"] = "play"
    g["current_round"] = 0
    g["current_high_bid"] = STARTING_BID
    g["current_leader"] = None
    g["bid_timer_end"] = time.time() + BID_TIMER_SECONDS
    g["resolved_item"] = None
    g["winner"] = None
    g["votes"] = {}
    return True


def get_current_item(g: dict) -> dict | None:
    """Get current round's item."""
    if g["current_round"] >= len(g["items"]):
        return None
    return g["items"][g["current_round"]]


def check_timer_expired(g: dict) -> bool:
    """Return True if bid timer has expired."""
    return g["bid_timer_end"] is not None and time.time() >= g["bid_timer_end"]


def resolve_round(g: dict) -> None:
    """Timer expired: current leader wins item, pays bid. Advance to reveal."""
    item = get_current_item(g)
    if not item:
        return
    g["resolved_item"] = item
    g["phase"] = "reveal"
    leader = g["current_leader"]
    if leader is not None and g["current_high_bid"] > 0:
        g["budgets"][leader] -= g["current_high_bid"]
        g["collections"][leader].append({"name": item["name"]})
        g["winner"] = leader
    else:
        g["winner"] = None


def advance_from_reveal(gid: str) -> bool:
    """Advance to next round or start voting phase or end game."""
    g = get_game(gid)
    if not g or g["phase"] != "reveal":
        return False

    g["current_round"] += 1
    g["resolved_item"] = None
    g["winner"] = None

    if g["current_round"] >= g["rounds_total"]:
        g["phase"] = "voting"
        return True

    # Next item
    g["phase"] = "play"
    g["current_high_bid"] = STARTING_BID
    g["current_leader"] = None
    g["bid_timer_end"] = time.time() + BID_TIMER_SECONDS
    return True


def compute_borda_standings(g: dict) -> list[dict]:
    """Compute final standings from votes. Returns list of {id, name, score, rank}."""
    n = len(g["players"])
    scores = {p["id"]: 0 for p in g["players"]}
    first_place_votes = {p["id"]: 0 for p in g["players"]}

    for pid, rankings in g["votes"].items():
        if len(rankings) != n - 1:
            continue
        for rank, target_id in enumerate(rankings):
            if target_id in scores:
                points = (n - 1) - rank
                scores[target_id] += points
                if rank == 0:
                    first_place_votes[target_id] += 1

    standings = []
    for p in g["players"]:
        pid = p["id"]
        standings.append({
            "id": pid,
            "name": p["name"],
            "score": scores[pid],
            "first_place_votes": first_place_votes[pid],
        })
    standings.sort(key=lambda x: (-x["score"], -x["first_place_votes"]))

    # Assign ranks
    for i, s in enumerate(standings):
        s["rank"] = i + 1
    return standings


def public_state(g: dict, player_id: str | None = None) -> dict:
    """Build state for client."""
    players = [{"id": p["id"], "name": p["name"]} for p in g["players"]]

    # Leaderboard: items won count (or during voting/ended: Borda standings)
    if g["phase"] in ("voting", "ended") and g.get("final_standings"):
        leaderboard = [
            {"id": s["id"], "name": s["name"], "rank": s["rank"], "score": s["score"]}
            for s in g["final_standings"]
        ]
    else:
        leaderboard = []
        for p in g["players"]:
            pid = p["id"]
            items_count = len(g["collections"][pid])
            leaderboard.append({"id": pid, "name": p["name"], "items_won": items_count})
        leaderboard.sort(key=lambda x: x["items_won"], reverse=True)

    current_item = None
    if g["phase"] == "play" and g["current_round"] < len(g["items"]):
        item = g["items"][g["current_round"]]
        is_mystery = g["current_round"] in g.get("mystery_rounds", set())
        display_name = "Mystery Item" if is_mystery else item["name"]
        min_bid = g["current_high_bid"] + 1 if g["current_leader"] else STARTING_BID
        current_item = {
            "name": display_name,
            "is_mystery": is_mystery,
            "min_bid": min_bid,
        }

    # For reveal
    resolved = None
    if g["phase"] == "reveal" and g.get("resolved_item"):
        winner = next((p for p in g["players"] if p["id"] == g["winner"]), None)
        resolved = {
            "item_name": g["resolved_item"]["name"],
            "winner_name": winner["name"] if winner else None,
        }

    # Bidding state
    seconds_remaining = 0
    if g["phase"] == "play" and g["bid_timer_end"]:
        secs = int(g["bid_timer_end"] - time.time())
        seconds_remaining = max(0, secs)
    current_leader_name = None
    if g["current_leader"]:
        leader_p = next((p for p in g["players"] if p["id"] == g["current_leader"]), None)
        current_leader_name = leader_p["name"] if leader_p else None

    # For voting: list of other players to rank
    players_to_rank = []
    if g["phase"] == "voting" and player_id:
        players_to_rank = [{"id": p["id"], "name": p["name"]} for p in g["players"] if p["id"] != player_id]
    has_voted = player_id in g["votes"] if player_id else False
    votes_count = len(g["votes"])

    my_budget = g["budgets"].get(player_id) if player_id else None
    my_collection = g["collections"].get(player_id, []) if player_id else []

    n = len(g["players"])
    rounds_min = n * 2
    rounds_max = n * 5

    return {
        "game_id": g["id"],
        "phase": g["phase"],
        "current_round": g["current_round"],
        "rounds_min": rounds_min,
        "rounds_max": rounds_max,
        "players": players,
        "leaderboard": leaderboard,
        "current_item": current_item,
        "current_high_bid": g["current_high_bid"],
        "current_leader_name": current_leader_name,
        "seconds_remaining": seconds_remaining,
        "bid_timer_end": g["bid_timer_end"],
        "resolved": resolved,
        "my_collection": my_collection,
        "my_budget": my_budget,
        "players_to_rank": players_to_rank,
        "has_voted": has_voted,
        "votes_count": votes_count,
        "final_standings": g.get("final_standings"),
    }


# --- Routes ---

@app.route("/health")
def health():
    return "ok", 200


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/game/create", methods=["POST"])
def game_create():
    game_code = (request.form.get("game_code") or "").strip()
    host_name = (request.form.get("host_name") or "Host").strip()
    if not host_name:
        host_name = "Host"
    g = create_game(game_code, host_name)
    if not g:
        return render_template("index.html", create_error="Game code taken or invalid (use 4–6 letters/numbers)")
    return redirect(url_for("host", game_id=g["id"]))


@app.route("/game/join", methods=["POST"])
def game_join():
    game_code = (request.form.get("game_code") or "").strip()
    player_name = (request.form.get("player_name") or "").strip()
    g = get_game(game_code)
    if not g:
        return render_template("index.html", join_error="Game not found. Check the code.")
    if not player_name:
        return render_template("index.html", join_error="Enter your name.")
    p = add_player(game_code, player_name)
    if not p:
        return render_template("index.html", join_error="Game full or already started.")
    return redirect(url_for("play", game_id=g["id"], player_id=p["id"]))


@app.route("/game/<game_id>/host")
def host(game_id):
    g = get_game(game_id)
    if not g:
        return "Game not found", 404
    host_player_id = g["players"][0]["id"] if g["players"] else None
    return render_template("host.html", game_id=g["id"], host_player_id=host_player_id)


@app.route("/game/<game_id>/join", methods=["GET", "POST"])
def join(game_id):
    g = get_game(game_id)
    if not g:
        return "Game not found", 404
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if name and len(g["players"]) < MAX_PLAYERS:
            p = add_player(game_id, name)
            if p:
                return redirect(url_for("play", game_id=game_id, player_id=p["id"]))
    return render_template("join.html", game_id=game_id, players=len(g["players"]))


@app.route("/game/<game_id>/play/<player_id>")
def play(game_id, player_id):
    g = get_game(game_id)
    if not g:
        return "Game not found", 404
    if not any(p["id"] == player_id for p in g["players"]):
        return "Player not found", 404
    return render_template("play.html", game_id=game_id, player_id=player_id)


@app.route("/api/game/<game_id>/state")
def api_state(game_id):
    g = get_game(game_id)
    if not g:
        return jsonify({"error": "not_found"}), 404
    pid = request.args.get("player_id")
    # Check if timer expired (server-side)
    if g["phase"] == "play" and check_timer_expired(g):
        resolve_round(g)
    return jsonify(public_state(g, pid))


@app.route("/api/game/<game_id>/bid", methods=["POST"])
def api_bid(game_id):
    g = get_game(game_id)
    if not g:
        return jsonify({"error": "not_found"}), 404
    if g["phase"] != "play":
        return jsonify({"error": "wrong_phase"}), 400
    if check_timer_expired(g):
        resolve_round(g)
        return jsonify({"ok": True})

    data = request.get_json() or {}
    pid = data.get("player_id")
    if not pid or not any(p["id"] == pid for p in g["players"]):
        return jsonify({"error": "invalid_player"}), 400

    amount = data.get("amount")
    if amount is None:
        return jsonify({"error": "invalid_bid"}), 400
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_bid"}), 400

    budget = g["budgets"][pid]
    if amount < 0 or amount > budget:
        return jsonify({"error": "invalid_bid"}), 400
    min_bid = g["current_high_bid"] + 1 if g["current_leader"] else STARTING_BID
    if amount < min_bid:
        return jsonify({"error": f"Bid must be at least ${min_bid}"}), 400

    g["current_high_bid"] = amount
    g["current_leader"] = pid
    g["bid_timer_end"] = time.time() + BID_EXTEND_SECONDS

    return jsonify({"ok": True})


@app.route("/api/game/<game_id>/vote", methods=["POST"])
def api_vote(game_id):
    g = get_game(game_id)
    if not g:
        return jsonify({"error": "not_found"}), 404
    if g["phase"] != "voting":
        return jsonify({"error": "wrong_phase"}), 400

    data = request.get_json() or {}
    pid = data.get("player_id")
    if not pid or not any(p["id"] == pid for p in g["players"]):
        return jsonify({"error": "invalid_player"}), 400
    if pid in g["votes"]:
        return jsonify({"error": "already_voted"}), 400

    rankings = data.get("rankings", [])
    n = len(g["players"])
    other_ids = {p["id"] for p in g["players"] if p["id"] != pid}
    if len(rankings) != n - 1:
        return jsonify({"error": "rankings must contain exactly " + str(n - 1) + " player IDs"}), 400
    if set(rankings) != other_ids:
        return jsonify({"error": "rankings must be all other players, each exactly once"}), 400

    g["votes"][pid] = rankings

    if len(g["votes"]) == n:
        g["final_standings"] = compute_borda_standings(g)
        g["phase"] = "ended"

    return jsonify({"ok": True})


@app.route("/api/game/<game_id>/advance", methods=["POST"])
def api_advance(game_id):
    g = get_game(game_id)
    if not g:
        return jsonify({"error": "not_found"}), 404

    if g["phase"] == "lobby":
        if start_game(game_id):
            return jsonify({"ok": True})
        return jsonify({"error": "not_enough_players"}), 400

    if g["phase"] == "reveal":
        advance_from_reveal(game_id)
        return jsonify({"ok": True})

    return jsonify({"error": "nothing_to_advance"}), 400


if __name__ == "__main__":
    # Use 5001: macOS AirPlay Receiver uses 5000 by default
    app.run(debug=True, host="0.0.0.0", port=5001)
