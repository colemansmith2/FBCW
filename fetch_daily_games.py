#!/usr/bin/env python3
"""
Fetch today's MLB schedule and lineups from the MLB Stats API and write
them to data/current_season/daily_games.json.

The frontend uses `teams_playing` to color the active-status dot on each
player's headshot on the My Team page; `games` carries probable pitchers
and (when published) starting lineups for richer per-player views later.

The MLB Stats API is public — no auth required.
Endpoint reference: https://statsapi.mlb.com/api/v1/schedule

Usage:
    python fetch_daily_games.py              # today (US Eastern)
    python fetch_daily_games.py 2026-04-28   # specific date
"""

import os
import sys
import json
import datetime
import zoneinfo

import requests

OUTPUT_PATH = "data/current_season/daily_games.json"
SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
    "?sportId=1&date={date}&hydrate=probablePitcher,lineups,team"
)

# MLB Stats API team_id -> 3-letter abbreviation matching what Yahoo serves
# us in our roster/player data. (Yahoo uses CWS not CHW, KC not KCR, etc.)
TEAM_ID_TO_ABBR = {
    108: "LAA",
    109: "ARI",
    110: "BAL",
    111: "BOS",
    112: "CHC",
    113: "CIN",
    114: "CLE",
    115: "COL",
    116: "DET",
    117: "HOU",
    118: "KC",
    119: "LAD",
    120: "WSH",
    121: "NYM",
    133: "OAK",
    134: "PIT",
    135: "SD",
    136: "SEA",
    137: "SF",
    138: "STL",
    139: "TB",
    140: "TEX",
    141: "TOR",
    142: "MIN",
    143: "PHI",
    144: "ATL",
    145: "CWS",
    146: "MIA",
    147: "NYY",
    158: "MIL",
}


def today_eastern():
    return datetime.datetime.now(
        zoneinfo.ZoneInfo("America/New_York")
    ).date().isoformat()


def fetch_schedule(date_str):
    url = SCHEDULE_URL.format(date=date_str)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def _person_summary(p):
    if not p:
        return None
    pid = p.get("id")
    name = p.get("fullName") or p.get("name")
    if not pid and not name:
        return None
    return {"player_id": pid, "name": name}


def _lineup_players(lineup_list):
    out = []
    for i, p in enumerate(lineup_list or [], start=1):
        summary = _person_summary(p)
        if not summary:
            continue
        summary["batting_order"] = i
        out.append(summary)
    return out


def parse_games(schedule_data):
    games = []
    teams_playing = set()

    for date_block in schedule_data.get("dates", []):
        for game in date_block.get("games", []):
            teams = game.get("teams", {})
            home_id = teams.get("home", {}).get("team", {}).get("id")
            away_id = teams.get("away", {}).get("team", {}).get("id")
            home_abbr = TEAM_ID_TO_ABBR.get(home_id)
            away_abbr = TEAM_ID_TO_ABBR.get(away_id)

            status = (game.get("status") or {}).get("detailedState", "")
            # Skip games that won't actually be played today.
            skip_states = {"Postponed", "Cancelled", "Suspended"}
            if status in skip_states:
                continue

            if home_abbr:
                teams_playing.add(home_abbr)
            if away_abbr:
                teams_playing.add(away_abbr)

            lineups = game.get("lineups") or {}

            games.append(
                {
                    "game_pk": game.get("gamePk"),
                    "game_date": game.get("gameDate"),
                    "status": status,
                    "home_team": home_abbr,
                    "away_team": away_abbr,
                    "home_probable_pitcher": _person_summary(
                        teams.get("home", {}).get("probablePitcher")
                    ),
                    "away_probable_pitcher": _person_summary(
                        teams.get("away", {}).get("probablePitcher")
                    ),
                    "home_lineup": _lineup_players(lineups.get("homePlayers")),
                    "away_lineup": _lineup_players(lineups.get("awayPlayers")),
                }
            )

    return games, sorted(teams_playing)


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else today_eastern()

    print(f"Fetching MLB schedule for {date_str}…")
    schedule = fetch_schedule(date_str)
    games, teams_playing = parse_games(schedule)

    output = {
        "date": date_str,
        "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "teams_playing": teams_playing,
        "game_count": len(games),
        "games": games,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    lineup_games = sum(
        1 for g in games if g["home_lineup"] or g["away_lineup"]
    )
    print(
        f"Wrote {len(games)} games / {len(teams_playing)} teams playing "
        f"({lineup_games} with lineups posted) -> {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
