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
OUTPUT_FILE = f"{DATA_DIR}/{SEASON}/weekly_stats.json"

# Scoring settings (adjust to match your league)
BATTING_SCORING = {
    '1B': 2.6, '2B': 5.2, '3B': 7.8, 'HR': 10.4,
    'RBI': 1.9, 'R': 1.9, 'BB': 2.6, 'HBP': 2.6,
    'SB': 4.2, 'CS': -2.6, 'SO': -1, 'IBB': 0,
    'CYC': 10, 'SLAM': 10
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
    """Get team stats for a specific week."""
    hitting_stats = []
    pitching_stats = []
    
    teams = lg.teams()
    
    for team_key, team_info in teams.items():
        try:
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
            
            for stat in team_stats.get('stats', []):
                stat_id = stat.get('stat_id')
                value = safe_float(stat.get('value', 0))
                
                if stat_id in BATTING_STAT_IDS:
                    stat_name = BATTING_STAT_IDS[stat_id]
                    hitting[stat_name] = value
                    if stat_name in BATTING_SCORING:
                        hitting['Points'] += value * BATTING_SCORING[stat_name]
                
                if stat_id in PITCHING_STAT_IDS:
                    stat_name = PITCHING_STAT_IDS[stat_id]
                    pitching[stat_name] = value
                    if stat_name in PITCHING_SCORING:
                        pitching['Points'] += value * PITCHING_SCORING[stat_name]
            
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
                'team2_key': team2[0][0]['team_key'],
                'team2_score': safe_float(team2[1].get('team_points', {}).get('total', 0))
            })
            
    except Exception as e:
        print(f"  Warning: Could not get matchups for week {week}: {e}")
    
    return matchups

def get_top_performers(lg, week: int) -> Dict:
    """Get top individual player performances for the week."""
    return {
        'topHitters': [],
        'topPitchers': []
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
                'value': sorted_teams[0].get(cat, 0)
            }
    
    pitching_cats = ['K', 'W', 'SV', 'QS']
    for cat in pitching_cats:
        sorted_teams = sorted(pitching_stats, key=lambda x: x.get(cat, 0), reverse=True)
        if sorted_teams and sorted_teams[0].get(cat, 0) > 0:
            leaders[cat] = {
                'team_key': sorted_teams[0]['team_key'],
                'value': sorted_teams[0].get(cat, 0)
            }
    
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
    print(f"League: {lg.settings().get('name', 'Unknown')}")
    
    completed_week = get_completed_week(lg)
    print(f"Collecting data for Week {completed_week}")
    
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
    
    print(f"\nCollecting Week {completed_week} stats...")
    week_stats = get_team_stats(lg, completed_week)
    matchups = get_matchups(lg, completed_week)
    performers = get_top_performers(lg, completed_week)
    leaders = get_category_leaders(week_stats['hitting'], week_stats['pitching'])
    
    existing_data['weeks'][str(completed_week)] = {
        'hitting': week_stats['hitting'],
        'pitching': week_stats['pitching'],
        'matchups': matchups,
        'topHitters': performers['topHitters'],
        'topPitchers': performers['topPitchers'],
        'categoryLeaders': leaders
    }
    
    existing_data['currentWeek'] = completed_week
    
    print("Calculating cumulative stats...")
    existing_data['cumulative'] = calculate_cumulative_stats(existing_data['weeks'])
    
    existing_data['lastUpdated'] = datetime.now().isoformat()
    existing_data['season'] = SEASON
    
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
        print(f"Collecting specific week: {week}")
        collect_weekly_stats()
    elif len(sys.argv) > 1 and sys.argv[1] == "--all":
        print("Collecting all weeks...")
        collect_weekly_stats()
    else:
        collect_weekly_stats()
