#!/usr/bin/env python3
"""
Fetch Rest-of-Season (ROS) projections from Fangraphs and calculate fantasy points.
Saves projections to data/projections/ros/ for use in the Trade Analyzer during the season.

These are separate from the preseason projections in data/projections/ which remain untouched.

Supported ROS projection systems (7 total):
- OOPSY DC (roopsydc)
- ZiPS DC (rzipsdc)
- Steamer (steamerr)
- Fangraphs DC (rfangraphsdc)
- ATC DC (ratcdc)
- The BAT (rthebat)
- The BAT X (rthebatx)

Usage:
    python fetch_ros_projections.py              # Fetch all ROS systems
    python fetch_ros_projections.py ros_steamer  # Fetch specific system
"""

import requests
import json
import os
import sys
from datetime import datetime

# Fangraphs API endpoints for projections
FANGRAPHS_API_BASE = "https://www.fangraphs.com/api/projections"

# Output directory — separate from preseason projections
OUTPUT_DIR = "data/projections/ros"

# ROS Projection systems to fetch
# Key = output filename suffix, Value = Fangraphs API type parameter
ROS_PROJECTION_SYSTEMS = {
    'ros_oopsydc':     'roopsydc',
    'ros_zipsdc':      'rzipsdc',
    'ros_steamer':     'steamerr',
    'ros_fangraphsdc': 'rfangraphsdc',
    'ros_atcdc':       'ratcdc',
    'ros_thebat':      'rthebat',
    'ros_thebatx':     'rthebatx',
}

# Systems that are batters-only
BATTERS_ONLY_SYSTEMS = {'rthebatx'}

# Your league's scoring settings (same as preseason)
BATTING_SCORING = {
    '1B': 1.1,
    '2B': 2.2,
    '3B': 3.3,
    'HR': 4.4,
    'RBI': 1.0,
    'SB': 2.0,
    'CS': -1.0,
    'BB': 1.0,
    'IBB': 1.0,
    'HBP': 1.0,
    'SO': -0.5,
    'CYC': 5.0,
    'SLAM': 2.0
}

PITCHING_SCORING = {
    'IP': 2.5,
    'W': 2.5,
    'L': -3.0,
    'CG': 5.0,
    'ShO': 5.0,
    'SV': 5.0,
    'HA': -0.75,
    'ER': -1.75,
    'BBA': -0.75,
    'K': 1.5,
    'HLD': 2.0,
    'PICK': 3.0,
    'NH': 10.0,
    'QS': 3.0
}

# Lower thresholds for ROS — mid-season projections cover fewer remaining games
ROS_MIN_PA = 20
ROS_MIN_IP = 5


def calculate_batting_points(stats):
    """Calculate fantasy points for a batter."""
    points = 0.0
    points += stats.get('1B', 0) * BATTING_SCORING['1B']
    points += stats.get('2B', 0) * BATTING_SCORING['2B']
    points += stats.get('3B', 0) * BATTING_SCORING['3B']
    points += stats.get('HR', 0) * BATTING_SCORING['HR']
    points += stats.get('RBI', 0) * BATTING_SCORING['RBI']
    points += stats.get('SB', 0) * BATTING_SCORING['SB']
    points += stats.get('CS', 0) * BATTING_SCORING['CS']
    points += stats.get('BB', 0) * BATTING_SCORING['BB']
    points += stats.get('IBB', 0) * BATTING_SCORING.get('IBB', 0)
    points += stats.get('HBP', 0) * BATTING_SCORING.get('HBP', 0)
    points += stats.get('SO', 0) * BATTING_SCORING['SO']
    return round(points, 1)


def calculate_pitching_points(stats):
    """Calculate fantasy points for a pitcher."""
    points = 0.0
    points += stats.get('IP', 0) * PITCHING_SCORING['IP']
    points += stats.get('W', 0) * PITCHING_SCORING['W']
    points += stats.get('L', 0) * PITCHING_SCORING['L']
    points += stats.get('SV', 0) * PITCHING_SCORING['SV']
    points += stats.get('HLD', 0) * PITCHING_SCORING['HLD']
    points += stats.get('ER', 0) * PITCHING_SCORING['ER']
    points += stats.get('H', 0) * PITCHING_SCORING['HA']
    points += stats.get('BB', 0) * PITCHING_SCORING['BBA']
    points += stats.get('K', 0) * PITCHING_SCORING['K']
    points += stats.get('QS', 0) * PITCHING_SCORING.get('QS', 0)
    points += stats.get('CG', 0) * PITCHING_SCORING.get('CG', 0)
    return round(points, 1)


def get_headshot_url(mlb_id):
    """Build MLB headshot URL from player ID, or return default placeholder."""
    if mlb_id:
        return f"https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people/{int(mlb_id)}/headshot/67/current"
    return "https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people/1/headshot/67/current"


def fetch_fangraphs_projections(proj_type, stat_type):
    """Fetch projections from Fangraphs API."""
    url = f"{FANGRAPHS_API_BASE}?type={proj_type}&stats={stat_type}&pos=all&team=0&lg=all&players=0"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Referer': 'https://www.fangraphs.com/projections'
    }

    try:
        print(f"  Fetching {proj_type} {stat_type} projections...")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        print(f"    ✓ Found {len(data)} {'batters' if stat_type == 'bat' else 'pitchers'}")
        return data
    except requests.exceptions.RequestException as e:
        print(f"    ⚠ Error fetching {stat_type} projections: {e}")
        return []


def process_batter_projections(raw_data):
    """Process raw batter projection data into standardized format."""
    players = []

    for player in raw_data:
        try:
            name = player.get('PlayerName', player.get('Name', 'Unknown'))
            team = player.get('Team', player.get('teamid', 'FA'))
            if not team or team == '- - -':
                team = 'FA'

            position = player.get('minpos', 'Util')
            if position:
                position = str(position).strip()
            if not position or position == '-' or position == 'nan':
                position = 'Util'
            if position and position not in ['Util', 'P', 'SP', 'RP']:
                position = f"{position},Util"

            # Calculate singles
            h = int(player.get('H', 0) or 0)
            doubles = int(player.get('2B', 0) or 0)
            triples = int(player.get('3B', 0) or 0)
            hr = int(player.get('HR', 0) or 0)
            singles = h - doubles - triples - hr

            stats = {
                'G': int(player.get('G', 0) or 0),
                'HR': hr,
                'RBI': int(player.get('RBI', 0) or 0),
                'R': int(player.get('R', 0) or 0),
                'SB': int(player.get('SB', 0) or 0),
                'H': h,
                '1B': singles,
                '2B': doubles,
                '3B': triples,
                'BB': int(player.get('BB', 0) or 0),
                'SO': int(player.get('SO', 0) or 0),
                'AVG': float(player.get('AVG', 0) or 0),
                'OPS': float(player.get('OPS', 0) or 0),
                'PA': int(player.get('PA', 0) or 0),
            }

            points = calculate_batting_points(stats)

            mlb_id = player.get('xMLBAMID') or player.get('mlbamid') or player.get('MLBAMID')
            headshot_url = get_headshot_url(mlb_id)

            processed = {
                'name': name,
                'team': team,
                'position': position,
                'type': 'batter',
                'projected_points': points,
                'stats': stats,
                'headshot_url': headshot_url,
                'mlb_id': None
            }

            # Lower threshold for ROS projections (fewer remaining games)
            if stats['PA'] >= ROS_MIN_PA:
                players.append(processed)

        except Exception as e:
            print(f"    ⚠ Error processing batter {player.get('PlayerName', 'Unknown')}: {e}")
            continue

    players.sort(key=lambda x: x['projected_points'], reverse=True)
    return players


def process_pitcher_projections(raw_data):
    """Process raw pitcher projection data into standardized format."""
    players = []

    for player in raw_data:
        try:
            name = player.get('PlayerName', player.get('Name', 'Unknown'))
            team = player.get('Team', player.get('teamid', 'FA'))
            if not team or team == '- - -':
                team = 'FA'

            gs = int(player.get('GS', 0) or 0)
            g = int(player.get('G', 0) or 0)
            if gs > 0 and (gs / max(g, 1)) >= 0.5:
                position = 'SP'
            else:
                position = 'RP'

            stats = {
                'W': int(player.get('W', 0) or 0),
                'L': int(player.get('L', 0) or 0),
                'SV': int(player.get('SV', 0) or 0),
                'HLD': int(player.get('HLD', 0) or 0),
                'IP': float(player.get('IP', 0) or 0),
                'K': int(player.get('SO', player.get('K', 0)) or 0),
                'SO': int(player.get('SO', player.get('K', 0)) or 0),
                'ER': int(player.get('ER', 0) or 0),
                'H': int(player.get('H', 0) or 0),
                'BB': int(player.get('BB', 0) or 0),
                'ERA': float(player.get('ERA', 0) or 0),
                'WHIP': float(player.get('WHIP', 0) or 0),
                'G': g,
                'GS': gs,
            }

            points = calculate_pitching_points(stats)

            mlb_id = player.get('xMLBAMID') or player.get('mlbamid') or player.get('MLBAMID')
            headshot_url = get_headshot_url(mlb_id)

            processed = {
                'name': name,
                'team': team,
                'position': position,
                'type': 'pitcher',
                'projected_points': points,
                'stats': stats,
                'headshot_url': headshot_url,
                'mlb_id': None
            }

            # Lower threshold for ROS projections
            if stats['IP'] >= ROS_MIN_IP:
                players.append(processed)

        except Exception as e:
            print(f"    ⚠ Error processing pitcher {player.get('PlayerName', 'Unknown')}: {e}")
            continue

    players.sort(key=lambda x: x['projected_points'], reverse=True)
    return players


def fetch_and_save_ros_projections(output_name, api_type):
    """Fetch both batting and pitching ROS projections and save to JSON."""
    print(f"\n{'='*50}")
    print(f"Fetching {output_name.upper()} ROS Projections")
    print(f"{'='*50}")

    is_batters_only = api_type in BATTERS_ONLY_SYSTEMS

    # Fetch raw data
    batters_raw = fetch_fangraphs_projections(api_type, "bat")

    if is_batters_only:
        pitchers_raw = []
        print(f"  ℹ️  {output_name.upper()} is a batters-only projection system")
    else:
        pitchers_raw = fetch_fangraphs_projections(api_type, "pit")

    if not batters_raw and not pitchers_raw:
        print(f"\n⚠ No data fetched for {output_name}. API may be unavailable or season hasn't started.")
        return False

    # Process data
    batters = process_batter_projections(batters_raw)
    pitchers = process_pitcher_projections(pitchers_raw) if pitchers_raw else []

    # Include all players for ROS (no truncation — important for matching roster players)
    print(f"\n  Processed {len(batters)} batters and {len(pitchers)} pitchers")

    # Build output
    output = {
        'generated_at': datetime.now().isoformat(),
        'year': 2026,
        'projection_type': output_name,
        'is_ros': True,
        'scoring': {
            'batting': BATTING_SCORING,
            'pitching': PITCHING_SCORING
        },
        'batters': batters,
        'pitchers': pitchers
    }

    if is_batters_only:
        output['note'] = 'This ROS projection system only provides batting projections'

    # Create output directory if needed
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Save to JSON
    output_file = os.path.join(OUTPUT_DIR, f"{output_name}.json")
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n  ✓ Saved to {output_file}")
    print(f"    - {len(batters)} batters")
    print(f"    - {len(pitchers)} pitchers")

    return True


def main():
    print("\n" + "="*60)
    print("  FANGRAPHS REST-OF-SEASON PROJECTION FETCHER")
    print("  Fetching ROS projections for in-season trade analysis")
    print("="*60)

    # Check for command line argument to fetch specific system
    if len(sys.argv) > 1:
        requested = sys.argv[1].lower()
        if requested in ROS_PROJECTION_SYSTEMS:
            success = fetch_and_save_ros_projections(requested, ROS_PROJECTION_SYSTEMS[requested])
            print("\n" + "="*60)
            print(f"  {requested.upper()}: {'✓ Success' if success else '✗ Failed'}")
            print("="*60 + "\n")
            return
        elif requested == '--help' or requested == '-h':
            print("\nUsage:")
            print("  python fetch_ros_projections.py              # Fetch all ROS systems")
            print("  python fetch_ros_projections.py <system>     # Fetch specific system")
            print("\nAvailable systems:")
            for name in ROS_PROJECTION_SYSTEMS.keys():
                print(f"  - {name}")
            print()
            return
        else:
            print(f"\n⚠ Unknown ROS projection system: {requested}")
            print(f"Available systems: {', '.join(ROS_PROJECTION_SYSTEMS.keys())}")
            return

    # Fetch all ROS projection systems
    results = {}
    for output_name, api_type in ROS_PROJECTION_SYSTEMS.items():
        results[output_name] = fetch_and_save_ros_projections(output_name, api_type)

    print("\n" + "="*60)
    print("  SUMMARY")
    print("="*60)
    for name, success in results.items():
        status = '✓ Success' if success else '✗ Failed'
        print(f"  {name.ljust(18)}: {status}")

    successful = sum(1 for s in results.values() if s)
    if successful > 0:
        print(f"\n  ROS projections saved to: {OUTPUT_DIR}/")
        print(f"  Preseason projections in data/projections/ are untouched.")
    else:
        print("\n  ⚠ No ROS projections were saved.")
        print("    ROS projections may not be available until the season starts.")

    print("="*60 + "\n")


if __name__ == "__main__":
    main()
