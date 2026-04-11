"""
Weekly Stats Collection for Fantasy Baseball Civil War
Generates weekly_stats.json for the in-season dashboard

This script should run every Monday morning to collect the previous week's data.
It pulls data from Yahoo Fantasy API and formats it for the website.

FULLY AUTOMATIC - Tokens are automatically refreshed and saved back to GitHub Secrets.

SETUP FOR GITHUB ACTIONS:
1. Create a Personal Access Token (PAT) with 'repo' scope:
   - Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Generate new token with 'repo' scope
   - Save this as GITHUB_PAT secret

2. Create these GitHub Secrets in your repository:
   - GITHUB_PAT: Your personal access token (for updating secrets)
   - YAHOO_CONSUMER_KEY: Your Yahoo app consumer key
   - YAHOO_CONSUMER_SECRET: Your Yahoo app consumer secret
   - YAHOO_ACCESS_TOKEN: Your OAuth access token
   - YAHOO_REFRESH_TOKEN: Your OAuth refresh token
   - YAHOO_TOKEN_TIME: The token timestamp
"""

import json
import os
import math
import base64
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from yahoo_oauth import OAuth2
from yahoo_fantasy_api import Game, League

# =============================================================================
# CONFIGURATION
# =============================================================================

SEASON = 2026
DATA_DIR = "data"
# Write to current_season so the frontend can find it
OUTPUT_FILE = f"{DATA_DIR}/current_season/weekly_stats.json"
# Also write a copy to the year-specific directory for archival
OUTPUT_FILE_ARCHIVE = f"{DATA_DIR}/{SEASON}/weekly_stats.json"

# Scoring settings - matches FBCW IX league settings
BATTING_SCORING = {
    '1B': 1.1, '2B': 2.2, '3B': 3.3, 'HR': 4.4,
    'RBI': 1.0, 'SB': 2.0, 'CS': -1.0, 'BB': 1.0,
    'IBB': 1.0, 'HBP': 1.0, 'K': -0.5,
    'CYC': 5.0, 'SLAM': 2.0
}

PITCHING_SCORING = {
    'IP': 2.5, 'W': 2.5, 'L': -3.0, 'CG': 5.0,
    'SHO': 5.0, 'SV': 5.0, 'H': -0.75, 'ER': -1.75,
    'BB': -0.75, 'K': 1.5, 'HLD': 2.0,
    'PICK': 3.0, 'NH': 10.0, 'QS': 3.0
}

# Yahoo stat ID mappings - from league stat_modifiers
BATTING_STAT_IDS = {
    9: '1B', 10: '2B', 11: '3B', 12: 'HR',
    13: 'RBI', 16: 'SB', 17: 'CS', 18: 'BB',
    19: 'IBB', 20: 'HBP', 21: 'K',
    64: 'CYC', 66: 'SLAM'
}

PITCHING_STAT_IDS = {
    50: 'IP', 28: 'W', 29: 'L', 30: 'CG',
    31: 'SHO', 32: 'SV', 34: 'H', 37: 'ER',
    39: 'BB', 42: 'K', 48: 'HLD',
    72: 'PICK', 79: 'NH', 83: 'QS'
}

# =============================================================================
# GITHUB SECRETS MANAGEMENT
# =============================================================================

def get_github_public_key(repo_owner: str, repo_name: str, github_token: str) -> tuple:
    """Get the public key for encrypting secrets."""
    import urllib.request
    import urllib.error
    
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/secrets/public-key"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {github_token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data['key'], data['key_id']
    except urllib.error.HTTPError as e:
        print(f"Error getting public key: {e.code} - {e.read().decode()}")
        raise

def encrypt_secret(public_key: str, secret_value: str) -> str:
    """Encrypt a secret using the repository's public key."""
    from nacl import encoding, public
    
    public_key_bytes = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key_bytes)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def update_github_secret(repo_owner: str, repo_name: str, github_token: str, 
                         secret_name: str, secret_value: str) -> bool:
    """Update a GitHub repository secret."""
    import urllib.request
    import urllib.error
    
    try:
        # Get public key
        public_key, key_id = get_github_public_key(repo_owner, repo_name, github_token)
        
        # Encrypt the secret
        encrypted_value = encrypt_secret(public_key, secret_value)
        
        # Update the secret
        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/secrets/{secret_name}"
        data = json.dumps({
            "encrypted_value": encrypted_value,
            "key_id": key_id
        }).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method='PUT')
        req.add_header("Authorization", f"Bearer {github_token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        
        with urllib.request.urlopen(req) as response:
            print(f"  ✓ Updated secret: {secret_name}")
            return True
            
    except urllib.error.HTTPError as e:
        print(f"  ✗ Failed to update {secret_name}: {e.code} - {e.read().decode()}")
        return False
    except ImportError:
        print("  ✗ PyNaCl not installed - cannot encrypt secrets")
        print("    Install with: pip install pynacl")
        return False
    except Exception as e:
        print(f"  ✗ Error updating {secret_name}: {e}")
        return False

def save_tokens_to_github_secrets(oauth_data: dict) -> bool:
    """Save refreshed OAuth tokens back to GitHub Secrets."""
    github_token = os.environ.get('GITHUB_PAT')
    github_repo = os.environ.get('GITHUB_REPOSITORY', '')
    
    if not github_token:
        print("GITHUB_PAT not set - cannot auto-update secrets")
        return False
    
    if not github_repo or '/' not in github_repo:
        print(f"GITHUB_REPOSITORY not valid: {github_repo}")
        return False
    
    repo_owner, repo_name = github_repo.split('/', 1)
    
    print("\nUpdating GitHub Secrets with refreshed tokens...")
    
    success = True
    secrets_to_update = {
        'YAHOO_ACCESS_TOKEN': oauth_data.get('access_token', ''),
        'YAHOO_REFRESH_TOKEN': oauth_data.get('refresh_token', ''),
        'YAHOO_TOKEN_TIME': str(oauth_data.get('token_time', ''))
    }
    
    for secret_name, secret_value in secrets_to_update.items():
        if secret_value:
            if not update_github_secret(repo_owner, repo_name, github_token, secret_name, secret_value):
                success = False
    
    return success

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

def parse_selected_position(player) -> str:
    """Extract the selected roster position from a Yahoo player payload."""
    try:
        pos_data = player[1].get('selected_position', [])
        if isinstance(pos_data, list) and len(pos_data) > 1:
            return pos_data[1].get('position', '')
        if isinstance(pos_data, dict):
            return pos_data.get('position', '')
    except (AttributeError, IndexError, KeyError, TypeError):
        pass
    return ''

def extract_player_metadata(player) -> Dict[str, str]:
    """Extract core player metadata from the Yahoo player payload."""
    metadata = {
        'player_id': '',
        'player_key': '',
        'name': '',
        'position_type': '',
        'headshot': ''
    }

    try:
        for item in player[0]:
            if not isinstance(item, dict):
                continue
            if 'player_id' in item:
                metadata['player_id'] = str(item.get('player_id') or '')
            elif 'player_key' in item:
                metadata['player_key'] = item.get('player_key', '') or ''
            elif 'name' in item:
                metadata['name'] = item['name'].get('full', '')
            elif 'position_type' in item:
                metadata['position_type'] = item['position_type']
            elif 'headshot' in item:
                headshot = item['headshot']
                if isinstance(headshot, dict):
                    metadata['headshot'] = headshot.get('url', '') or ''
                elif isinstance(headshot, str):
                    metadata['headshot'] = headshot
    except (IndexError, TypeError):
        pass

    return metadata

def extract_player_points(player) -> float:
    """Extract fantasy points from a Yahoo player payload."""
    for item in player:
        if isinstance(item, dict) and 'player_points' in item:
            try:
                return float(item['player_points'].get('total', 0))
            except (ValueError, TypeError):
                return 0.0
    return 0.0

def extract_player_stats(player) -> Dict[int, float]:
    """Extract stat values from a Yahoo player payload keyed by stat_id."""
    stats = {}
    for item in player:
        if not isinstance(item, dict) or 'player_stats' not in item:
            continue
        for stat_entry in item['player_stats'].get('stats', []):
            if not isinstance(stat_entry, dict) or 'stat' not in stat_entry:
                continue
            stat = stat_entry['stat']
            stat_id = safe_int(stat.get('stat_id'), 0)
            if stat_id <= 0:
                continue
            stats[stat_id] = safe_float(stat.get('value', 0))
        break
    return stats

def convert_ip_display_to_outs(ip_value) -> int:
    """Convert baseball-style innings pitched notation to outs recorded."""
    innings = safe_float(ip_value, 0.0)
    whole_innings = int(innings)
    remainder_outs = int(round((innings - whole_innings) * 10))
    if remainder_outs not in (0, 1, 2):
        remainder_outs = 0
    return (whole_innings * 3) + remainder_outs

def convert_outs_to_ip_display(outs: int) -> float:
    """Convert outs recorded to baseball-style innings pitched notation."""
    whole_innings = outs // 3
    remainder_outs = outs % 3
    return round(whole_innings + (remainder_outs / 10), 1)

def setup_oauth():
    """
    Initialize OAuth for Yahoo Fantasy API.
    Automatically handles token refresh and saves new tokens to GitHub Secrets.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    oauth_path = os.path.join(script_dir, 'oauth2.json')
    
    # Check if we have environment variables (GitHub Actions mode)
    consumer_key = os.environ.get('YAHOO_CONSUMER_KEY')
    consumer_secret = os.environ.get('YAHOO_CONSUMER_SECRET')
    access_token = os.environ.get('YAHOO_ACCESS_TOKEN')
    refresh_token = os.environ.get('YAHOO_REFRESH_TOKEN')
    token_time = os.environ.get('YAHOO_TOKEN_TIME')
    
    if all([consumer_key, consumer_secret, access_token, refresh_token]):
        print("Using credentials from environment variables")
        
        # Create oauth2.json from environment variables
        original_oauth_data = {
            "consumer_key": consumer_key,
            "consumer_secret": consumer_secret,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_time": float(token_time) if token_time else datetime.now().timestamp(),
            "token_type": "bearer"
        }
        
        # Write temporary oauth file
        with open(oauth_path, 'w') as f:
            json.dump(original_oauth_data, f)
        
        try:
            oauth = OAuth2(None, None, from_file=oauth_path)
            
            # Read back the file to check for token refresh
            with open(oauth_path, 'r') as f:
                updated_oauth_data = json.load(f)
            
            # Check if tokens changed (were refreshed)
            if updated_oauth_data.get('access_token') != access_token:
                print("\n" + "=" * 60)
                print("OAuth tokens were refreshed!")
                print("=" * 60)
                
                # Try to automatically update GitHub Secrets
                if save_tokens_to_github_secrets(updated_oauth_data):
                    print("✓ Tokens automatically saved to GitHub Secrets")
                else:
                    # Manual fallback
                    print("\nManual update required. Update these GitHub Secrets:")
                    print(f"  YAHOO_ACCESS_TOKEN: {updated_oauth_data.get('access_token')}")
                    print(f"  YAHOO_REFRESH_TOKEN: {updated_oauth_data.get('refresh_token')}")
                    print(f"  YAHOO_TOKEN_TIME: {updated_oauth_data.get('token_time')}")
            
            return oauth
            
        finally:
            # Clean up the temporary file for security
            if os.path.exists(oauth_path):
                os.remove(oauth_path)
    
    # Fall back to local file (for local development)
    elif os.path.exists(oauth_path):
        print("Using credentials from local oauth2.json file")
        print("WARNING: Make sure oauth2.json is in your .gitignore!")
        return OAuth2(None, None, from_file=oauth_path)
    
    else:
        raise FileNotFoundError(
            "No OAuth credentials found!\n"
            "For GitHub Actions: Set YAHOO_CONSUMER_KEY, YAHOO_CONSUMER_SECRET, "
            "YAHOO_ACCESS_TOKEN, and YAHOO_REFRESH_TOKEN as repository secrets.\n"
            "For local development: Create an oauth2.json file."
        )

def get_current_week(lg) -> int:
    """Get the current fantasy week number."""
    try:
        settings = lg.settings()
        current_week = settings.get('current_week', 1)
        return int(current_week)
    except:
        return 1

def get_completed_week(lg) -> int:
    """Get the most recently completed week."""
    current_week = get_current_week(lg)
    today = datetime.now()
    if today.weekday() == 0:  # Monday
        return max(1, current_week - 1)
    return current_week

# =============================================================================
# DATA COLLECTION FUNCTIONS
# =============================================================================

def get_team_stats(lg, week: int) -> Dict:
    """Get team-level aggregate stats for the matchup date window."""
    hitting_stats = []
    pitching_stats = []

    # Get the date range for this week
    try:
        week_start, week_end = lg.week_date_range(week)
        start_str = week_start.strftime("%Y-%m-%d")
        end_str = week_end.strftime("%Y-%m-%d")
        print(f"  Week {week} date range: {start_str} to {end_str}")
    except Exception as e:
        print(f"  Warning: Could not get week date range: {e}")
        return {'hitting': [], 'pitching': []}

    teams = lg.teams()

    for team_key, team_info in teams.items():
        try:
            manager_name = team_info['managers'][0]['manager']['nickname']
            team_name = team_info['name']
            pitching_outs = 0

            hitting = {
                'team_key': team_key,
                'team_name': team_name,
                'manager': manager_name,
                'Points': 0
            }
            pitching = {
                'team_key': team_key,
                'team_name': team_name,
                'manager': manager_name,
                'Points': 0
            }

            current_day = week_start
            while current_day <= week_end:
                day_str = current_day.strftime("%Y-%m-%d")
                raw = lg.yhandler.get(
                    f"team/{team_key}/roster;date={day_str}/players/stats;type=date;date={day_str}"
                )

                players_data = raw['fantasy_content']['team'][1]['roster']['0']['players']
                player_count = int(players_data.get('count', 0))

                for i in range(player_count):
                    player_idx = str(i)
                    if player_idx not in players_data:
                        continue

                    player = players_data[player_idx]['player']
                    selected_position = parse_selected_position(player)
                    if selected_position in ('BN', 'IL', 'IL+', 'DL', 'NA'):
                        continue

                    metadata = extract_player_metadata(player)
                    stats = extract_player_stats(player)
                    points = extract_player_points(player)

                    if metadata['position_type'] == 'B':
                        for stat_id, stat_name in BATTING_STAT_IDS.items():
                            hitting[stat_name] = hitting.get(stat_name, 0) + stats.get(stat_id, 0)
                    elif metadata['position_type'] == 'P':
                        for stat_id, stat_name in PITCHING_STAT_IDS.items():
                            stat_value = stats.get(stat_id, 0)
                            if stat_name == 'IP':
                                pitching_outs += convert_ip_display_to_outs(stat_value)
                            else:
                                pitching[stat_name] = pitching.get(stat_name, 0) + stat_value

                    hitting['Points'] += points if metadata['position_type'] == 'B' else 0
                    pitching['Points'] += points if metadata['position_type'] == 'P' else 0

                current_day += timedelta(days=1)

            pitching['IP'] = convert_outs_to_ip_display(pitching_outs)
            decimal_ip = pitching_outs / 3.0
            if decimal_ip > 0:
                pitching['ERA'] = round((pitching.get('ER', 0) * 9) / decimal_ip, 2)
                pitching['K/9'] = round((pitching.get('K', 0) * 9) / decimal_ip, 2)
            else:
                pitching['ERA'] = 0
                pitching['K/9'] = 0

            hitting['Points'] = round(hitting['Points'], 1)
            pitching['Points'] = round(pitching['Points'], 1)

            hitting_stats.append(hitting)
            pitching_stats.append(pitching)
            print(f"  ✓ {team_name}: Hitting {hitting['Points']}pts, Pitching {pitching['Points']}pts")

        except Exception as e:
            print(f"  Warning: Could not get stats for {team_key}: {e}")
            import traceback
            traceback.print_exc()
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
        
        for i in range(6):
            matchup_key = str(i)
            if matchup_key not in raw_matchups:
                break
            
            matchup = raw_matchups[matchup_key]['matchup']['0']['teams']
            
            team1 = matchup['0']['team']
            team2 = matchup['1']['team']
            
            matchups.append({
                'team1_key': team1[0][0]['team_key'],
                'team1_score': safe_float(team1[1].get('team_points', {}).get('total', 0)),
                'team1_projected': safe_float(team1[1].get('team_projected_points', {}).get('total', 0)),
                'team2_key': team2[0][0]['team_key'],
                'team2_score': safe_float(team2[1].get('team_points', {}).get('total', 0)),
                'team2_projected': safe_float(team2[1].get('team_projected_points', {}).get('total', 0))
            })
            
    except Exception as e:
        print(f"  Warning: Could not get matchups for week {week}: {e}")
    
    return matchups

def get_top_performers(lg, week: int) -> Dict:
    """Get top individual player performances for the matchup date window."""
    all_hitters = []
    all_pitchers = []

    try:
        week_start, week_end = lg.week_date_range(week)
    except Exception as e:
        print(f"  Warning: Could not get week date range for performers: {e}")
        return {'topHitters': [], 'topPitchers': []}

    day_count = (week_end - week_start).days + 1
    week_days = [
        (week_start + timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(day_count)
    ]

    teams = lg.teams()

    for team_key, team_info in teams.items():
        try:
            team_name = team_info['name']
            players_by_id = {}

            for day_str in week_days:
                raw = lg.yhandler.get(
                    f"team/{team_key}/roster;date={day_str}/players/stats;type=date;date={day_str}"
                )

                players_data = raw['fantasy_content']['team'][1]['roster']['0']['players']
                player_count = int(players_data.get('count', 0))

                for i in range(player_count):
                    player_idx = str(i)
                    if player_idx not in players_data:
                        continue

                    player = players_data[player_idx]['player']
                    selected_position = parse_selected_position(player)

                    # Only count days where the player was active in the lineup.
                    if selected_position in ('BN', 'IL', 'IL+', 'DL', 'NA'):
                        continue

                    metadata = extract_player_metadata(player)
                    points = extract_player_points(player)
                    if points <= 0:
                        continue

                    player_id = metadata['player_id'] or metadata['player_key'] or metadata['name']
                    if not player_id:
                        continue

                    entry = players_by_id.setdefault(player_id, {
                        'name': metadata['name'],
                        'team_name': team_name,
                        'headshot': metadata['headshot'],
                        'position_type': metadata['position_type'],
                        'points': 0.0,
                        'stats': {}
                    })
                    entry['points'] += points

                    # Accumulate per-stat values across days
                    raw_stats = extract_player_stats(player)
                    if metadata['position_type'] == 'B':
                        for sid, sname in BATTING_STAT_IDS.items():
                            if sid in raw_stats:
                                entry['stats'][sname] = entry['stats'].get(sname, 0) + raw_stats[sid]
                    elif metadata['position_type'] == 'P':
                        for sid, sname in PITCHING_STAT_IDS.items():
                            if sid in raw_stats:
                                entry['stats'][sname] = entry['stats'].get(sname, 0) + raw_stats[sid]

                    if not entry['headshot'] and metadata['headshot']:
                        entry['headshot'] = metadata['headshot']
                    if not entry['name'] and metadata['name']:
                        entry['name'] = metadata['name']
                    if not entry['position_type'] and metadata['position_type']:
                        entry['position_type'] = metadata['position_type']

            for entry in players_by_id.values():
                # Round stat values for clean output
                clean_stats = {}
                for k, v in entry.get('stats', {}).items():
                    if k == 'IP':
                        clean_stats[k] = round(v, 1)
                    else:
                        clean_stats[k] = int(v) if v == int(v) else round(v, 1)

                player_entry = {
                    'name': entry['name'],
                    'team_name': entry['team_name'],
                    'headshot': entry['headshot'],
                    'points': round(entry['points'], 2),
                    'stats': clean_stats
                }

                if entry['position_type'] == 'B':
                    all_hitters.append(player_entry)
                elif entry['position_type'] == 'P':
                    all_pitchers.append(player_entry)

        except Exception as e:
            print(f"  Warning: Could not get performers for {team_key}: {e}")
            continue

    all_hitters.sort(key=lambda x: x['points'], reverse=True)
    all_pitchers.sort(key=lambda x: x['points'], reverse=True)

    return {
        'topHitters': all_hitters[:10],
        'topPitchers': all_pitchers[:10]
    }

def get_category_leaders(hitting_stats: List, pitching_stats: List) -> Dict:
    """Calculate category leaders from team stats."""
    leaders = {}

    hitting_cats = ['HR', 'RBI', 'SB', '1B', '2B', '3B']
    for cat in hitting_cats:
        sorted_teams = sorted(hitting_stats, key=lambda x: x.get(cat, 0), reverse=True)
        if sorted_teams and sorted_teams[0].get(cat, 0) > 0:
            leaders[cat] = {
                'team_key': sorted_teams[0]['team_key'],
                'team_name': sorted_teams[0].get('team_name', ''),
                'player_name': sorted_teams[0].get('manager', ''),
                'value': sorted_teams[0].get(cat, 0)
            }

    pitching_cats = ['K', 'W', 'SV', 'QS', 'IP']
    for cat in pitching_cats:
        sorted_teams = sorted(pitching_stats, key=lambda x: x.get(cat, 0), reverse=True)
        if sorted_teams and sorted_teams[0].get(cat, 0) > 0:
            leaders[cat] = {
                'team_key': sorted_teams[0]['team_key'],
                'team_name': sorted_teams[0].get('team_name', ''),
                'player_name': sorted_teams[0].get('manager', ''),
                'value': sorted_teams[0].get(cat, 0)
            }

    pitching_with_ip = [p for p in pitching_stats if p.get('IP', 0) > 0]
    if pitching_with_ip:
        sorted_era = sorted(pitching_with_ip, key=lambda x: x.get('ERA', 999))
        leaders['ERA'] = {
            'team_key': sorted_era[0]['team_key'],
            'team_name': sorted_era[0].get('team_name', ''),
            'player_name': sorted_era[0].get('manager', ''),
            'value': sorted_era[0].get('ERA', 0)
        }

    return leaders

def calculate_cumulative_stats(all_weeks: Dict) -> Dict:
    """Calculate cumulative stats across all weeks."""
    cumulative_hitting = {}
    cumulative_pitching = {}
    cumulative_pitching_outs = {}
    
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
                cumulative_pitching_outs[team_key] = 0
            
            for key, value in pitching.items():
                if key in ['team_key', 'team_name', 'manager', 'ERA', 'K/9']:
                    continue
                if key == 'IP':
                    cumulative_pitching_outs[team_key] += convert_ip_display_to_outs(value)
                else:
                    current = cumulative_pitching[team_key].get(key, 0)
                    cumulative_pitching[team_key][key] = current + value
    
    for team_key, stats in cumulative_pitching.items():
        outs = cumulative_pitching_outs.get(team_key, 0)
        stats['IP'] = convert_outs_to_ip_display(outs)
        decimal_ip = outs / 3.0
        if decimal_ip > 0:
            stats['ERA'] = round((stats.get('ER', 0) * 9) / decimal_ip, 2)
            stats['K/9'] = round((stats.get('K', 0) * 9) / decimal_ip, 2)
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

def collect_weekly_stats(target_week=None, collect_all=False):
    """Main function to collect and save weekly stats.

    Args:
        target_week: Specific week number to collect (None = auto-detect last completed week)
        collect_all: If True, collect all weeks from 1 to current
    """
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
    print(f"League: {lg.settings().get('name', 'Unknown')}")

    if collect_all:
        current_week = get_current_week(lg)
        weeks_to_collect = list(range(1, current_week + 1))
        print(f"Collecting ALL weeks: 1 through {current_week}")
    elif target_week is not None:
        weeks_to_collect = [target_week]
        print(f"Collecting specific week: {target_week}")
    else:
        completed_week = get_completed_week(lg)
        weeks_to_collect = [completed_week]
        print(f"Collecting data for Week {completed_week}")
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    existing_data = {
        'currentWeek': weeks_to_collect[-1],
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

    for week_num in weeks_to_collect:
        print(f"\nCollecting Week {week_num} stats...")
        week_stats = get_team_stats(lg, week_num)
        matchups = get_matchups(lg, week_num)
        performers = get_top_performers(lg, week_num)
        leaders = get_category_leaders(week_stats['hitting'], week_stats['pitching'])

        existing_data['weeks'][str(week_num)] = {
            'hitting': week_stats['hitting'],
            'pitching': week_stats['pitching'],
            'matchups': matchups,
            'topHitters': performers['topHitters'],
            'topPitchers': performers['topPitchers'],
            'categoryLeaders': leaders
        }

    existing_data['currentWeek'] = max(
        safe_int(existing_data.get('currentWeek'), 0),
        max(weeks_to_collect)
    )

    print("Calculating cumulative stats...")
    existing_data['cumulative'] = calculate_cumulative_stats(existing_data['weeks'])
    
    existing_data['lastUpdated'] = datetime.now().isoformat()
    existing_data['season'] = SEASON
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    # Also save archival copy to year-specific directory
    os.makedirs(os.path.dirname(OUTPUT_FILE_ARCHIVE), exist_ok=True)
    with open(OUTPUT_FILE_ARCHIVE, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Saved to {OUTPUT_FILE}")
    print(f"  ✓ Archive copy saved to {OUTPUT_FILE_ARCHIVE}")
    print(f"  - Weeks collected: {len(existing_data['weeks'])}")
    print(f"  - Weeks: {', '.join(sorted(existing_data['weeks'].keys(), key=int))}")
    
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

Environment Variables (for GitHub Actions):
    YAHOO_CONSUMER_KEY      - Your Yahoo app consumer key
    YAHOO_CONSUMER_SECRET   - Your Yahoo app consumer secret  
    YAHOO_ACCESS_TOKEN      - Your OAuth access token
    YAHOO_REFRESH_TOKEN     - Your OAuth refresh token
    YAHOO_TOKEN_TIME        - Token timestamp
    GITHUB_PAT              - GitHub Personal Access Token (for auto-updating secrets)
    GITHUB_REPOSITORY       - Auto-set by GitHub Actions (owner/repo)
        """)
    elif len(sys.argv) > 2 and sys.argv[1] == "--week":
        week = int(sys.argv[2])
        collect_weekly_stats(target_week=week)
    elif len(sys.argv) > 1 and sys.argv[1] == "--all":
        collect_weekly_stats(collect_all=True)
    else:
        collect_weekly_stats()
