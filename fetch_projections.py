#!/usr/bin/env python3
"""
Fetch projections from Fangraphs and calculate fantasy points.
Saves projections to JSON files for use in the Preseason Tools tab.

Supported projection systems:
- Steamer
- ZiPS
- ZiPS DC (with playing time - preferred for 2026)
- ZiPS 2027/2028 (multi-year forecasts)
- Depth Charts (fangraphsdc)
- The BAT (thebat)
- The BAT X (thebatx)

Usage:
    python fetch_projections.py           # Fetch all projection systems
    python fetch_projections.py steamer   # Fetch specific system
    python fetch_projections.py zipsdc    # Fetch ZiPS DC (playing time projections)
    python fetch_projections.py thebatx   # Fetch The BAT X only
"""

import requests
import json
import os
import sys
from datetime import datetime

# Fangraphs API endpoints for projections
FANGRAPHS_API_BASE = "https://www.fangraphs.com/api/projections"

# Output directory
OUTPUT_DIR = "data/projections"

# Projection systems to fetch
# Key = output filename, Value = Fangraphs API type parameter
PROJECTION_SYSTEMS = {
    'steamer': 'steamer',
    'zips': 'zips',
    'zipsdc': 'zipsdc',    # ZiPS DC - with playing time projections (preferred for 2026)
    'zips2027': 'zipsp1',  # ZiPS +1 year projection (2027)
    'zips2028': 'zipsp2',  # ZiPS +2 year projection (2028)
    'depthcharts': 'fangraphsdc',
    'thebat': 'thebat',
    'thebatx': 'thebatx',
    'oopsy': 'oopsy',
    'atc': 'atc'
}

# Systems that should include all players (no truncation)
FULL_PLAYER_LIST_SYSTEMS = {'zips', 'zipsdc', 'zips2027', 'zips2028'}

# Your league's scoring settings
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
    points += stats.get('H', 0) * PITCHING_SCORING['HA']  # Hits allowed
    points += stats.get('BB', 0) * PITCHING_SCORING['BBA']  # Walks allowed
    points += stats.get('K', 0) * PITCHING_SCORING['K']
    points += stats.get('QS', 0) * PITCHING_SCORING.get('QS', 0)
    points += stats.get('CG', 0) * PITCHING_SCORING.get('CG', 0)
    return round(points, 1)


def get_headshot_url(mlb_id):
    """Build MLB headshot URL from player ID, or return default placeholder."""
    if mlb_id:
        return f"https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people/{int(mlb_id)}/headshot/67/current"
    # Return MLB's generic headshot placeholder when no ID available
    return "https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people/1/headshot/67/current"


def fetch_fangraphs_projections(proj_type, stat_type):
    """
    Fetch projections from Fangraphs API.
    
    Args:
        proj_type: 'steamer', 'zips', 'fangraphsdc', 'thebat', 'thebatx'
        stat_type: 'bat' for batters, 'pit' for pitchers
    
    Returns:
        List of player projection dictionaries
    """
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
    """Process raw batter projection data into standardized format matching existing JSONs."""
    players = []
    
    for player in raw_data:
        try:
            name = player.get('PlayerName', player.get('Name', 'Unknown'))
            team = player.get('Team', player.get('teamid', 'FA'))
            if not team or team == '- - -':
                team = 'FA'
            
            # Get position - Fangraphs API uses 'minpos' for position
            position = player.get('minpos', 'Util')
            
            # Clean up position
            if position:
                position = str(position).strip()
            if not position or position == '-' or position == 'nan':
                position = 'Util'
            
            # Add ,Util suffix to match Yahoo format (e.g., "OF,Util", "SS,Util")
            if position and position not in ['Util', 'P', 'SP', 'RP']:
                position = f"{position},Util"
            
            # Calculate singles
            h = int(player.get('H', 0) or 0)
            doubles = int(player.get('2B', 0) or 0)
            triples = int(player.get('3B', 0) or 0)
            hr = int(player.get('HR', 0) or 0)
            singles = h - doubles - triples - hr
            
            # Build stats dict matching existing format
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
            
            # Calculate fantasy points
            points = calculate_batting_points(stats)
            
            # Get headshot URL - xMLBAMID is the MLB player ID from Fangraphs
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
            
            # Only include players with significant playing time projections
            if stats['PA'] >= 50:
                players.append(processed)
                
        except Exception as e:
            print(f"    ⚠ Error processing batter {player.get('PlayerName', 'Unknown')}: {e}")
            continue
    
    # Sort by projected points descending
    players.sort(key=lambda x: x['projected_points'], reverse=True)
    return players


def process_pitcher_projections(raw_data):
    """Process raw pitcher projection data into standardized format matching existing JSONs."""
    players = []
    
    for player in raw_data:
        try:
            name = player.get('PlayerName', player.get('Name', 'Unknown'))
            team = player.get('Team', player.get('teamid', 'FA'))
            if not team or team == '- - -':
                team = 'FA'
            
            # Determine SP vs RP based on GS vs G ratio
            gs = int(player.get('GS', 0) or 0)
            g = int(player.get('G', 0) or 0)
            
            if gs > 0 and (gs / max(g, 1)) >= 0.5:
                position = 'SP'
            else:
                position = 'RP'
            
            # Build stats dict matching existing format
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
            
            # Calculate fantasy points
            points = calculate_pitching_points(stats)
            
            # Get headshot URL - xMLBAMID is the MLB player ID from Fangraphs
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
            
            # Only include pitchers with significant IP projections
            if stats['IP'] >= 10:
                players.append(processed)
                
        except Exception as e:
            print(f"    ⚠ Error processing pitcher {player.get('PlayerName', 'Unknown')}: {e}")
            continue
    
    # Sort by projected points descending
    players.sort(key=lambda x: x['projected_points'], reverse=True)
    return players


def fetch_and_save_projections(output_name, api_type):
    """
    Fetch both batting and pitching projections and save to JSON.

    Args:
        output_name: Name for output file (e.g., 'steamer', 'thebat')
        api_type: Fangraphs API type parameter (e.g., 'steamer', 'thebat')
    """
    print(f"\n{'='*50}")
    print(f"Fetching {output_name.upper()} Projections")
    print(f"{'='*50}")

    # Determine if this system should include all players (no truncation)
    include_all_players = output_name in FULL_PLAYER_LIST_SYSTEMS

    # Fetch raw data
    batters_raw = fetch_fangraphs_projections(api_type, "bat")
    pitchers_raw = fetch_fangraphs_projections(api_type, "pit")

    if not batters_raw and not pitchers_raw:
        print(f"\n⚠ No data fetched for {output_name}. API may be unavailable.")
        return False

    # Process data
    batters = process_batter_projections(batters_raw)
    pitchers = process_pitcher_projections(pitchers_raw) if pitchers_raw else []

    # Truncate to top 400 each (already sorted by projected points) unless it's a full-list system
    if not include_all_players:
        batters = batters[:400]
        pitchers = pitchers[:400]
    else:
        print(f"  ℹ️  Including all players for {output_name.upper()} (no truncation)")

    print(f"\n  Processed {len(batters)} batters and {len(pitchers)} pitchers")

    # Determine projection year based on system
    if output_name == 'zips2027':
        projection_year = 2027
    elif output_name == 'zips2028':
        projection_year = 2028
    else:
        projection_year = 2026

    # Build output matching existing JSON format
    output = {
        'generated_at': datetime.now().isoformat(),
        'year': projection_year,
        'projection_type': output_name,
        'scoring': {
            'batting': BATTING_SCORING,
            'pitching': PITCHING_SCORING
        },
        'batters': batters,
        'pitchers': pitchers
    }

    # Add note for multi-year ZiPS projections
    if output_name in ['zips2027', 'zips2028']:
        output['note'] = f'ZiPS {projection_year} projection (multi-year forecast)'
    
    # Create output directory if needed
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Save to JSON - filename format: projections_steamer.json
    output_file = os.path.join(OUTPUT_DIR, f"projections_{output_name}.json")
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n  ✓ Saved to {output_file}")
    print(f"    - {len(batters)} batters")
    print(f"    - {len(pitchers)} pitchers")
    
    return True


def main():
    print("\n" + "="*60)
    print("  FANGRAPHS PROJECTION FETCHER")
    print("  Fetching projections for preseason tools")
    print("="*60)
    
    # Check for command line argument to fetch specific system
    if len(sys.argv) > 1:
        requested = sys.argv[1].lower()
        if requested in PROJECTION_SYSTEMS:
            success = fetch_and_save_projections(requested, PROJECTION_SYSTEMS[requested])
            print("\n" + "="*60)
            print(f"  {requested.upper()}: {'✓ Success' if success else '✗ Failed'}")
            print("="*60 + "\n")
            return
        elif requested == '--help' or requested == '-h':
            print("\nUsage:")
            print("  python fetch_projections.py           # Fetch all systems")
            print("  python fetch_projections.py <system>  # Fetch specific system")
            print("\nAvailable systems:")
            for name in PROJECTION_SYSTEMS.keys():
                print(f"  - {name}")
            print()
            return
        else:
            print(f"\n⚠ Unknown projection system: {requested}")
            print(f"Available systems: {', '.join(PROJECTION_SYSTEMS.keys())}")
            return
    
    # Fetch all projection systems
    results = {}
    for output_name, api_type in PROJECTION_SYSTEMS.items():
        results[output_name] = fetch_and_save_projections(output_name, api_type)
    
    print("\n" + "="*60)
    print("  SUMMARY")
    print("="*60)
    for name, success in results.items():
        status = '✓ Success' if success else '✗ Failed'
        print(f"  {name.ljust(12)}: {status}")
    
    successful = sum(1 for s in results.values() if s)
    if successful > 0:
        print(f"\n  Projections saved to: {OUTPUT_DIR}/")
        print("  You can now use the Preseason Tools tab in the web app.")
    else:
        print("\n  ⚠ No projections were saved. Check your internet connection")
        print("    and try again, or download CSVs manually from Fangraphs.")
    
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
