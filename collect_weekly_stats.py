"""
Weekly Stats Collection for Fantasy Baseball Civil War
Generates weekly_stats.json for the in-season dashboard

This script should run every Monday morning to collect the previous week's data.
It pulls data from Yahoo Fantasy API and formats it for the website.
"""

import json
import os
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from yahoo_oauth import OAuth2
from yahoo_fantasy_api import Game, League

# =============================================================================
# CONFIGURATION
# =============================================================================

SEASON = 2026
DATA_DIR = "data"
OUTPUT_FILE = f"{DATA_DIR}/{SEASON}/weekly_stats.json"

# Scoring settings (adjust to match your league)
BATTING_SCORING = {
    '1B': 2.6, '2B': 5.2, '3B': 7.8, 'HR': 10.4,
    'RBI': 1.9, 'R': 1.9, 'BB': 2.6, 'HBP': 2.6,
    'SB': 4.2, 'CS': -2.6, 'SO': -1, 'IBB': 0,
    'CYC': 10, 'SLAM': 10  # Cycle and Grand Slam bonuses
}

PITCHING_SCORING = {
    'IP': 5, 'W': 4, 'L': -4, 'SV': 8, 'HLD': 4,
    'ER': -3, 'H': -1, 'BB': -1, 'K': 3,
    'QS': 4, 'CG': 5, 'SHO': 5, 'NH': 10, 'PICK': 2
}

# Yahoo stat ID mappings
BATTING_STAT_IDS = {
    60: '1B', 61: '2B', 62: '3B', 63: 'HR',
    13: 'RBI', 12: 'R', 18: 'BB', 17: 'HBP',
    15: 'SB', 16: 'CS', 14: 'K', 76: 'IBB',
    93: 'CYC', 75: 'SLAM'
}

PITCHING_STAT_IDS = {
    50: 'IP', 28: 'W', 29: 'L', 32: 'SV', 48: 'HLD',
    27: 'ER', 25: 'H', 39: 'BB', 42: 'K',
    63: 'QS', 34: 'CG', 35: 'SHO', 54: 'NH', 77: 'PICK'
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def safe_float(value, default=0.0):
    """Safely convert value to float."""
    if value is None:
        return default
    try:
        f = float(value)
        return default if math.isnan(f) else f
    except (ValueError, TypeError):
        return default

def safe_int(value, default=0):
    """Safely convert value to int."""
    if value is None:
        return default
    try:
        f = float(value)
        return default if math.isnan(f) else int(f)
    except (ValueError, TypeError):
        return default

def setup_oauth():
    """Initialize OAuth for Yahoo Fantasy API."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    oauth_path = os.path.join(script_dir, 'oauth2.json')
    
    if not os.path.exists(oauth_path):
        raise FileNotFoundError(f"oauth2.json not found at: {oauth_path}")
    
    return OAuth2(None, None, from_file=oauth_path)

def get_current_week(lg) -> int:
    """Get the current fantasy week number."""
    try:
        settings = lg.settings()
        current_week = settings.get('current_week', 1)
        return int(current_week)
    except:
        return 1

def get_completed_week(lg) -> int:
    """
    Get the most recently completed week.
    If today is Monday, returns last week's number.
    """
    current_week = get_current_week(lg)
    
    # If it's Monday and we're running the update, 
    # we want the week that just ended (current_week - 1)
    today = datetime.now()
    if today.weekday() == 0:  # Monday
        return max(1, current_week - 1)
    return current_week

# =============================================================================
# DATA COLLECTION FUNCTIONS
# =============================================================================

def get_team_stats(lg, week: int) -> Dict:
    """
    Get team stats for a specific week.
    Returns hitting and pitching stats broken down by team.
    """
    hitting_stats = []
    pitching_stats = []
    
    teams = lg.teams()
    
    for team_key, team_info in teams.items():
        try:
            # Get team's weekly stats
            team_stats = lg.team_stats(team_key, week=week)
            
            hitting = {
                'team_key': team_key,
                'team_name': team_info['name'],
                'manager': team_info['managers'][0]['manager']['nickname'],
                'Points': 0
            }
            pitching = {
                'team_key': team_key, 
                'team_name': team_info['name'],
                'manager': team_info['managers'][0]['manager']['nickname'],
                'Points': 0
            }
            
            # Parse stats from Yahoo response
            for stat in team_stats.get('stats', []):
                stat_id = stat.get('stat_id')
                value = safe_float(stat.get('value', 0))
                
                # Batting stats
                if stat_id in BATTING_STAT_IDS:
                    stat_name = BATTING_STAT_IDS[stat_id]
                    hitting[stat_name] = value
                    if stat_name in BATTING_SCORING:
                        hitting['Points'] += value * BATTING_SCORING[stat_name]
                
                # Pitching stats
                if stat_id in PITCHING_STAT_IDS:
                    stat_name = PITCHING_STAT_IDS[stat_id]
                    pitching[stat_name] = value
                    if stat_name in PITCHING_SCORING:
                        pitching['Points'] += value * PITCHING_SCORING[stat_name]
            
            # Calculate derived stats
            if 'IP' in pitching and pitching['IP'] > 0:
                ip = pitching['IP']
                pitching['ERA'] = round((pitching.get('ER', 0) * 9) / ip, 2)
                pitching['K/9'] = round((pitching.get('K', 0) * 9) / ip, 2)
            else:
                pitching['ERA'] = 0
                pitching['K/9'] = 0
            
            hitting['Points'] = round(hitting['Points'], 1)
            pitching['Points'] = round(pitching['Points'], 1)
            
            hitting_stats.append(hitting)
            pitching_stats.append(pitching)
            
        except Exception as e:
            print(f"  Warning: Could not get stats for {team_key}: {e}")
            continue
    
    return {
        'hitting': hitting_stats,
        'pitching': pitching_stats
    }

def get_matchups(lg, week: int) -> List[Dict]:
    """Get matchup results for a specific week."""
    matchups = []
    
    try:
        matchup_data = lg.matchups(week=week)
        raw_matchups = matchup_data['fantasy_content']['league'][1]['scoreboard']['0']['matchups']
        
        for i in range(6):  # Max 6 matchups in a 12-team league
            matchup_key = str(i)
            if matchup_key not in raw_matchups:
                break
            
            matchup = raw_matchups[matchup_key]['matchup']['0']['teams']
            
            team1 = matchup['0']['team']
            team2 = matchup['1']['team']
            
            matchups.append({
                'team1_key': team1[0][0]['team_key'],
                'team1_score': safe_float(team1[1].get('team_points', {}).get('total', 0)),
                'team2_key': team2[0][0]['team_key'],
                'team2_score': safe_float(team2[1].get('team_points', {}).get('total', 0))
            })
            
    except Exception as e:
        print(f"  Warning: Could not get matchups for week {week}: {e}")
    
    return matchups

def get_top_performers(lg, week: int) -> Dict:
    """Get top individual player performances for the week."""
    top_hitters = []
    top_pitchers = []
    
    # This would require additional API calls to get individual player stats
    # For now, return empty lists - can be enhanced later
    
    return {
        'topHitters': top_hitters,
        'topPitchers': top_pitchers
    }

def get_category_leaders(hitting_stats: List, pitching_stats: List) -> Dict:
    """Calculate category leaders from team stats."""
    leaders = {}
    
    # Hitting categories
    hitting_cats = ['HR', 'RBI', 'SB', '1B', '2B', '3B']
    for cat in hitting_cats:
        sorted_teams = sorted(hitting_stats, key=lambda x: x.get(cat, 0), reverse=True)
        if sorted_teams and sorted_teams[0].get(cat, 0) > 0:
            leaders[cat] = {
                'team_key': sorted_teams[0]['team_key'],
                'value': sorted_teams[0].get(cat, 0)
            }
    
    # Pitching categories
    pitching_cats = ['K', 'W', 'SV', 'QS']
    for cat in pitching_cats:
        sorted_teams = sorted(pitching_stats, key=lambda x: x.get(cat, 0), reverse=True)
        if sorted_teams and sorted_teams[0].get(cat, 0) > 0:
            leaders[cat] = {
                'team_key': sorted_teams[0]['team_key'],
                'value': sorted_teams[0].get(cat, 0)
            }
    
    # ERA (lower is better) - only include teams with IP
    pitching_with_ip = [p for p in pitching_stats if p.get('IP', 0) > 0]
    if pitching_with_ip:
        sorted_era = sorted(pitching_with_ip, key=lambda x: x.get('ERA', 999))
        leaders['ERA'] = {
            'team_key': sorted_era[0]['team_key'],
            'value': sorted_era[0].get('ERA', 0)
        }
    
    return leaders

def calculate_cumulative_stats(all_weeks: Dict) -> Dict:
    """Calculate cumulative stats across all weeks."""
    cumulative_hitting = {}
    cumulative_pitching = {}
    
    # Sum up all weeks
    for week_num, week_data in all_weeks.items():
        for hitting in week_data.get('hitting', []):
            team_key = hitting['team_key']
            if team_key not in cumulative_hitting:
                cumulative_hitting[team_key] = {
                    'team_key': team_key,
                    'team_name': hitting['team_name'],
                    'manager': hitting['manager'],
                    'Points': 0
                }
            
            for key, value in hitting.items():
                if key in ['team_key', 'team_name', 'manager']:
                    continue
                current = cumulative_hitting[team_key].get(key, 0)
                cumulative_hitting[team_key][key] = current + value
        
        for pitching in week_data.get('pitching', []):
            team_key = pitching['team_key']
            if team_key not in cumulative_pitching:
                cumulative_pitching[team_key] = {
                    'team_key': team_key,
                    'team_name': pitching['team_name'],
                    'manager': pitching['manager'],
                    'Points': 0
                }
            
            for key, value in pitching.items():
                if key in ['team_key', 'team_name', 'manager', 'ERA', 'K/9']:
                    continue
                current = cumulative_pitching[team_key].get(key, 0)
                cumulative_pitching[team_key][key] = current + value
    
    # Recalculate derived stats for cumulative
    for team_key, stats in cumulative_pitching.items():
        ip = stats.get('IP', 0)
        if ip > 0:
            stats['ERA'] = round((stats.get('ER', 0) * 9) / ip, 2)
            stats['K/9'] = round((stats.get('K', 0) * 9) / ip, 2)
        else:
            stats['ERA'] = 0
            stats['K/9'] = 0
        
        stats['Points'] = round(stats['Points'], 1)
    
    for team_key, stats in cumulative_hitting.items():
        stats['Points'] = round(stats['Points'], 1)
    
    return {
        'hitting': list(cumulative_hitting.values()),
        'pitching': list(cumulative_pitching.values())
    }

# =============================================================================
# MAIN COLLECTION FUNCTION
# =============================================================================

def collect_weekly_stats():
    """Main function to collect and save weekly stats."""
    print("=" * 60)
    print(f"WEEKLY STATS COLLECTION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Setup
    oauth = setup_oauth()
    gm = Game(oauth, 'mlb')
    league_ids = gm.league_ids(year=SEASON)
    
    if not league_ids:
        print(f"ERROR: No league found for {SEASON}")
        return False
    
    lg = League(oauth, league_ids[0])
    print(f"League: {lg.metadata().get('name', 'Unknown')}")
    
    # Determine which week to collect
    completed_week = get_completed_week(lg)
    print(f"Collecting data for Week {completed_week}")
    
    # Load existing data if available
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    existing_data = {
        'currentWeek': completed_week,
        'weeks': {},
        'cumulative': {}
    }
    
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            print(f"Loaded existing data with {len(existing_data.get('weeks', {}))} weeks")
        except Exception as e:
            print(f"Could not load existing data: {e}")
    
    # Collect stats for completed week
    print(f"\nCollecting Week {completed_week} stats...")
    week_stats = get_team_stats(lg, completed_week)
    matchups = get_matchups(lg, completed_week)
    performers = get_top_performers(lg, completed_week)
    leaders = get_category_leaders(week_stats['hitting'], week_stats['pitching'])
    
    # Store week data
    existing_data['weeks'][str(completed_week)] = {
        'hitting': week_stats['hitting'],
        'pitching': week_stats['pitching'],
        'matchups': matchups,
        'topHitters': performers['topHitters'],
        'topPitchers': performers['topPitchers'],
        'categoryLeaders': leaders
    }
    
    # Update current week pointer
    existing_data['currentWeek'] = completed_week
    
    # Recalculate cumulative stats
    print("Calculating cumulative stats...")
    existing_data['cumulative'] = calculate_cumulative_stats(existing_data['weeks'])
    
    # Add metadata
    existing_data['lastUpdated'] = datetime.now().isoformat()
    existing_data['season'] = SEASON
    
    # Save
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Saved to {OUTPUT_FILE}")
    print(f"  - Weeks collected: {len(existing_data['weeks'])}")
    print(f"  - Current week: {completed_week}")
    print(f"  - Matchups this week: {len(matchups)}")
    
    return True

# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("""
Weekly Stats Collector for Fantasy Baseball Civil War

Usage:
    python collect_weekly_stats.py          # Collect last completed week
    python collect_weekly_stats.py --week N # Collect specific week N
    python collect_weekly_stats.py --all    # Collect all weeks up to current
    python collect_weekly_stats.py --help   # Show this help
        """)
    elif len(sys.argv) > 2 and sys.argv[1] == "--week":
        # Collect specific week
        week = int(sys.argv[2])
        print(f"Collecting specific week: {week}")
        # Would need to modify collect_weekly_stats to accept week parameter
        collect_weekly_stats()
    elif len(sys.argv) > 1 and sys.argv[1] == "--all":
        print("Collecting all weeks...")
        collect_weekly_stats()
    else:
        collect_weekly_stats()
