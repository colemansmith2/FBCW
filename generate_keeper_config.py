#!/usr/bin/env python3
"""
Keeper Configuration Generator

This script generates the keeper_config.json file with password hashes for each team.
Passwords are formatted as: {ManagerName}{YearJoined}
Example: "Josh2019"

Usage:
    python generate_keeper_config.py
"""

import json
import hashlib
import os
from pathlib import Path

def hash_password(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def load_json(filepath: str) -> dict:
    """Load JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)

def save_json(filepath: str, data: dict):
    """Save JSON file with pretty printing."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Saved: {filepath}")

def get_manager_join_years(manager_history_path: str) -> dict:
    """Get the first year each manager joined the league."""
    join_years = {}
    
    try:
        history = load_json(manager_history_path)
        for manager in history:
            name = manager.get('manager_name', '')
            seasons = manager.get('seasons', [])
            if seasons:
                first_year = min(s.get('year', 9999) for s in seasons)
                join_years[name] = first_year
    except FileNotFoundError:
        print(f"Warning: {manager_history_path} not found")
    
    return join_years

def generate_keeper_config(
    teams_path: str = 'data/current_season/teams.json',
    manager_history_path: str = 'data/managers/manager_history.json',
    output_path: str = 'data/keepers/keeper_config.json',
    season: int = 2026,
    max_keepers: int = 5,
    deadline: str = "2026-03-15T23:59:59"
):
    """Generate keeper configuration with password hashes."""
    
    # Load teams
    try:
        teams = load_json(teams_path)
    except FileNotFoundError:
        print(f"Error: {teams_path} not found")
        return
    
    # Get manager join years
    join_years = get_manager_join_years(manager_history_path)
    
    # Build config
    config = {
        "season": season,
        "max_keepers": max_keepers,
        "deadline": deadline,
        "teams": {}
    }
    
    print("\nGenerating keeper config...")
    print("-" * 50)
    
    for team in teams:
        team_key = team.get('team_key', '')
        team_name = team.get('team_name', '')
        manager = team.get('manager', '')
        team_logo = team.get('team_logo', '')
        
        # Get join year (default to 2020 if unknown)
        join_year = join_years.get(manager, 2020)
        
        # Generate password: ManagerName + JoinYear
        password = f"{manager}{join_year}"
        password_hash = hash_password(password)
        
        config["teams"][team_key] = {
            "team_name": team_name,
            "manager": manager,
            "password_hash": password_hash,
            "team_logo": team_logo,
            "keepers_locked": False
        }
        
        print(f"  {manager:15} | Password: {password:20} | Team: {team_name}")
    
    print("-" * 50)
    
    # Save config
    save_json(output_path, config)
    
    # Also create empty keepers file if it doesn't exist
    keepers_path = f'data/keepers/keepers_{season}.json'
    if not os.path.exists(keepers_path):
        keepers_data = {
            "last_updated": "",
            "keepers": {team_key: [] for team_key in config["teams"].keys()}
        }
        save_json(keepers_path, keepers_data)
    
    print(f"\nConfig generated for {len(config['teams'])} teams")
    print(f"Max keepers: {max_keepers}")
    print(f"Deadline: {deadline}")

def merge_local_keepers(
    config_path: str = 'data/keepers/keeper_config.json',
    keepers_path: str = 'data/keepers/keepers_2026.json',
    local_submissions_dir: str = 'data/keepers/submissions'
):
    """
    Merge locally submitted keeper selections into the master keepers file.
    
    This would be used if managers export their selections to JSON files
    that you collect and merge.
    """
    
    if not os.path.exists(keepers_path):
        print(f"Error: {keepers_path} not found")
        return
    
    keepers = load_json(keepers_path)
    
    if not os.path.exists(local_submissions_dir):
        print(f"No submissions directory found at {local_submissions_dir}")
        return
    
    # Load each submission file
    for filename in os.listdir(local_submissions_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(local_submissions_dir, filename)
            try:
                submission = load_json(filepath)
                team_key = submission.get('team_key')
                team_keepers = submission.get('keepers', [])
                
                if team_key and team_key in keepers['keepers']:
                    keepers['keepers'][team_key] = team_keepers
                    print(f"Merged keepers for {team_key} from {filename}")
            except Exception as e:
                print(f"Error loading {filename}: {e}")
    
    # Update timestamp
    from datetime import datetime
    keepers['last_updated'] = datetime.now().isoformat()
    
    save_json(keepers_path, keepers)
    print(f"\nMerged keepers saved to {keepers_path}")

def print_current_keepers(keepers_path: str = 'data/keepers/keepers_2026.json'):
    """Print a summary of current keeper selections."""
    
    try:
        keepers = load_json(keepers_path)
    except FileNotFoundError:
        print(f"No keepers file found at {keepers_path}")
        return
    
    print("\nCurrent Keeper Selections")
    print("=" * 60)
    
    for team_key, team_keepers in keepers.get('keepers', {}).items():
        print(f"\n{team_key}:")
        if not team_keepers:
            print("  (no keepers selected)")
        else:
            for k in team_keepers:
                print(f"  - {k.get('player_name', 'Unknown')} ({k.get('position', '?')})")
    
    print("\n" + "=" * 60)
    print(f"Last updated: {keepers.get('last_updated', 'Never')}")

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == 'generate':
            generate_keeper_config()
        elif command == 'merge':
            merge_local_keepers()
        elif command == 'status':
            print_current_keepers()
        else:
            print(f"Unknown command: {command}")
            print("Usage: python generate_keeper_config.py [generate|merge|status]")
    else:
        # Default: generate config
        generate_keeper_config()
