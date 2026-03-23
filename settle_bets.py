#!/usr/bin/env python3
"""
settle_bets.py - Settle weekly sportsbook bets after matchups complete.

Runs as part of the Weekly Fantasy Baseball Update GitHub Action.
Reads completed matchup scores from weekly_stats.json, compares against
pending bets in Firebase, and settles wins/losses with balance updates.

Usage:
    python settle_bets.py [--week N] [--dry-run]

Options:
    --week N    Settle bets for a specific week (default: previous week)
    --dry-run   Print what would happen without making changes

Requires:
    - FIREBASE_SERVICE_ACCOUNT_KEY environment variable (JSON string)
      OR firebase_service_account.json file in the repo root
    - data/current_season/weekly_stats.json (matchup results)
    - data/current_season/teams.json (team key -> manager mapping)
"""

import json
import os
import sys
import re


def sanitize_key(key):
    """Match the frontend's sanitizeSportsbookKey function."""
    return re.sub(r'[.#$\[\]]', '_', key)


def normalize_manager_name(manager, year=2026, team_name='', team_key=''):
    """
    Simplified version of the frontend's normalizeManagerName.
    Maps known Yahoo nicknames to display names.
    """
    name_map = {
        'Josh': 'Josh B',
        'logan': 'Logan S',
        'Logan': 'Logan S',
    }
    normalized = name_map.get(manager, manager)
    return normalized


def load_matchup_results(week):
    """Load completed matchup results for a given week."""
    # Try weekly_stats.json first
    weekly_stats_path = 'data/current_season/weekly_stats.json'
    if os.path.exists(weekly_stats_path):
        with open(weekly_stats_path) as f:
            data = json.load(f)
        weeks = data.get('weeks', {})
        week_data = weeks.get(str(week), {})
        matchups = week_data.get('matchups', [])
        if matchups:
            return matchups

    # Fallback to week_N_scores.json
    scores_path = f'data/current_season/week_{week}_scores.json'
    if os.path.exists(scores_path):
        with open(scores_path) as f:
            scores = json.load(f)
        # Convert score pairs into matchup format (dedup by pair)
        seen = set()
        matchups = []
        for s in scores:
            pair_key = '|'.join(sorted([s['team_key'], s['opponent_key']]))
            if pair_key not in seen:
                seen.add(pair_key)
                matchups.append({
                    'team1_key': s['team_key'],
                    'team1_score': s.get('team_score', 0),
                    'team2_key': s['opponent_key'],
                    'team2_score': s.get('opponent_score', 0),
                })
        return matchups

    return []


def load_team_projections(week):
    """Load team weekly projected points for O/U settlement."""
    proj_path = 'data/current_season/team_weekly_projected_points.json'
    if os.path.exists(proj_path):
        with open(proj_path) as f:
            data = json.load(f)
        weekly = data.get('weekly', {})
        return weekly.get(str(week), {})
    return {}


def load_teams():
    """Load team key -> manager/name mapping."""
    teams_path = 'data/current_season/teams.json'
    if os.path.exists(teams_path):
        with open(teams_path) as f:
            return json.load(f)
    return []


def settle_weekly_bet(bet, matchups, projections, score_lookup):
    """
    Determine if a weekly bet won or lost.

    Returns: 'won', 'lost', or None (if can't determine / not applicable)
    """
    bet_type = bet.get('betType', '')

    # Weekly matchup winner bet (e.g., "weekly_1")
    if bet_type.startswith('weekly_'):
        team_key = bet.get('selection', '')
        if team_key in score_lookup:
            entry = score_lookup[team_key]
            team_score = entry['team_score']
            opp_score = entry['opponent_score']
            if team_score > opp_score:
                return 'won'
            elif team_score < opp_score:
                return 'lost'
            else:
                return 'push'  # Tie
        return None

    # Individual team O/U bet (e.g., "ou_over_469.l.4114.t.1_w1")
    if bet_type.startswith('ou_over_') or bet_type.startswith('ou_under_'):
        parts = bet_type.split('_')
        # Extract team key - it's between over/under and wN
        # Format: ou_over_TEAMKEY_wN or ou_under_TEAMKEY_wN
        is_over = 'over' in bet_type
        # Find the week part (wN)
        week_part_idx = None
        for i, p in enumerate(parts):
            if p.startswith('w') and p[1:].isdigit():
                week_part_idx = i
                break
        if week_part_idx is None:
            return None

        team_key = '_'.join(parts[2:week_part_idx])
        line = projections.get(team_key, 0)
        if not line:
            return None

        proj_line = round(line * 2) / 2  # Round to nearest 0.5

        if team_key in score_lookup:
            actual_score = score_lookup[team_key]['team_score']
            if is_over:
                if actual_score > proj_line:
                    return 'won'
                elif actual_score < proj_line:
                    return 'lost'
                else:
                    return 'push'
            else:
                if actual_score < proj_line:
                    return 'won'
                elif actual_score > proj_line:
                    return 'lost'
                else:
                    return 'push'
        return None

    # Matchup total O/U bet (e.g., "total_over_TEAM1KEY_TEAM2KEY_wN")
    if bet_type.startswith('total_over_') or bet_type.startswith('total_under_'):
        is_over = 'over' in bet_type
        parts = bet_type.split('_')
        # Find the week part
        week_part_idx = None
        for i, p in enumerate(parts):
            if p.startswith('w') and p[1:].isdigit():
                week_part_idx = i
                break
        if week_part_idx is None:
            return None

        # Team keys are between over/under and wN
        key_parts = parts[2:week_part_idx]
        # Need to split into two team keys - they're Yahoo format like 469.l.4114.t.1
        # Try to find two team keys by matching against known teams
        key_str = '_'.join(key_parts)

        # Find the two team keys from matchups
        team1_key = None
        team2_key = None
        for m in matchups:
            if m['team1_key'] in key_str and m['team2_key'] in key_str:
                team1_key = m['team1_key']
                team2_key = m['team2_key']
                break

        if not team1_key or not team2_key:
            return None

        proj1 = projections.get(team1_key, 0)
        proj2 = projections.get(team2_key, 0)
        total_line = round((proj1 + proj2) * 2) / 2

        if team1_key in score_lookup and team2_key in score_lookup:
            actual_total = score_lookup[team1_key]['team_score'] + score_lookup[team2_key]['team_score']
            if is_over:
                if actual_total > total_line:
                    return 'won'
                elif actual_total < total_line:
                    return 'lost'
                else:
                    return 'push'
            else:
                if actual_total < total_line:
                    return 'won'
                elif actual_total > total_line:
                    return 'lost'
                else:
                    return 'push'
        return None

    return None


def settle_parlay(bet, matchups, projections, score_lookup):
    """
    Settle a parlay bet. All legs must win for the parlay to win.
    If any leg loses, the parlay loses. If any leg pushes, reduce legs.
    """
    legs = bet.get('legs', [])
    if not legs:
        return None

    results = []
    for leg in legs:
        # Create a pseudo-bet for each leg
        leg_bet = {
            'betType': leg.get('betType', ''),
            'selection': leg.get('selection', ''),
        }
        result = settle_weekly_bet(leg_bet, matchups, projections, score_lookup)
        if result is None:
            return None  # Can't settle yet
        results.append(result)

    if 'lost' in results:
        return 'lost'
    if all(r == 'won' for r in results):
        return 'won'
    if all(r in ('won', 'push') for r in results):
        # Pushed legs reduce the parlay but remaining wins still count
        won_count = results.count('won')
        if won_count == 0:
            return 'push'
        return 'won'  # Remaining legs all won
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Settle weekly sportsbook bets')
    parser.add_argument('--week', type=int, default=None, help='Week to settle (default: previous week)')
    parser.add_argument('--dry-run', action='store_true', help='Print changes without applying')
    args = parser.parse_args()

    # Determine which week to settle
    weekly_stats_path = 'data/current_season/weekly_stats.json'
    if os.path.exists(weekly_stats_path):
        with open(weekly_stats_path) as f:
            stats = json.load(f)
        current_week = stats.get('currentWeek', 1)
    else:
        current_week = 1

    settle_week = args.week if args.week else max(1, current_week - 1)
    print(f"Settling bets for Week {settle_week} (current week: {current_week})")

    # Load matchup results
    matchups = load_matchup_results(settle_week)
    if not matchups:
        print(f"No matchup results found for week {settle_week}. Skipping.")
        return

    # Check if scores are actually populated (non-zero)
    has_scores = any(m.get('team1_score', 0) > 0 or m.get('team2_score', 0) > 0 for m in matchups)
    if not has_scores:
        print(f"Week {settle_week} scores are all 0.0 - matchups haven't been played yet. Skipping.")
        return

    # Build score lookup: team_key -> {team_score, opponent_score, opponent_key}
    score_lookup = {}
    for m in matchups:
        score_lookup[m['team1_key']] = {
            'team_score': m['team1_score'],
            'opponent_score': m['team2_score'],
            'opponent_key': m['team2_key'],
        }
        score_lookup[m['team2_key']] = {
            'team_score': m['team2_score'],
            'opponent_score': m['team1_score'],
            'opponent_key': m['team1_key'],
        }

    # Load projections for O/U settlement
    projections = load_team_projections(settle_week)

    # Load teams for manager mapping
    teams = load_teams()

    print(f"Loaded {len(matchups)} matchups, {len(projections)} projections, {len(teams)} teams")
    for m in matchups:
        print(f"  {m['team1_key']}: {m['team1_score']} vs {m['team2_key']}: {m['team2_score']}")

    # Initialize Firebase
    try:
        import firebase_admin
        from firebase_admin import credentials, db
    except ImportError:
        print("ERROR: firebase-admin package not installed. Run: pip install firebase-admin")
        sys.exit(1)

    # Load service account credentials
    cred_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY')
    if cred_json:
        cred_dict = json.loads(cred_json)
        cred = credentials.Certificate(cred_dict)
    elif os.path.exists('firebase_service_account.json'):
        cred = credentials.Certificate('firebase_service_account.json')
    else:
        print("ERROR: No Firebase credentials found.")
        print("Set FIREBASE_SERVICE_ACCOUNT_KEY env var or place firebase_service_account.json in repo root.")
        sys.exit(1)

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://fantasy-baseball-civil-war-default-rtdb.firebaseio.com'
        })

    # Read all bets
    bets_ref = db.reference('sportsbook_bets')
    all_bets = bets_ref.get() or {}

    # Read all balances
    balances_ref = db.reference('sportsbook_balances')
    all_balances = balances_ref.get() or {}

    print(f"Found {len(all_bets)} total bets in Firebase")

    # Filter to pending bets for this week
    settled_count = 0
    won_count = 0
    lost_count = 0
    push_count = 0
    balance_updates = {}  # manager_key -> amount to add

    for bet_id, bet in all_bets.items():
        if bet.get('status') != 'pending':
            continue

        bet_type = bet.get('betType', '')
        is_parlay = bet.get('isParlay', False)

        # Check if this bet is for the week we're settling
        is_weekly_bet = False
        if is_parlay:
            # Check if any leg is a weekly bet for this week
            legs = bet.get('legs', [])
            for leg in legs:
                lt = leg.get('betType', '')
                if lt.startswith(f'weekly_{settle_week}') or f'_w{settle_week}' in lt:
                    is_weekly_bet = True
                    break
        else:
            if bet_type.startswith(f'weekly_{settle_week}') or f'_w{settle_week}' in bet_type:
                is_weekly_bet = True

        if not is_weekly_bet:
            continue

        # Settle the bet
        if is_parlay:
            result = settle_parlay(bet, matchups, projections, score_lookup)
        else:
            result = settle_weekly_bet(bet, matchups, projections, score_lookup)

        if result is None:
            print(f"  SKIP: {bet_id} - could not determine result for {bet_type}")
            continue

        manager_key = bet.get('managerSanitized', '')
        wager = bet.get('wager', 0)
        potential_payout = bet.get('potentialPayout', 0)

        if result == 'won':
            # Winner gets their payout (which includes the wager back)
            winnings = potential_payout  # potentialPayout already includes wager + profit
            balance_updates[manager_key] = balance_updates.get(manager_key, 0) + winnings
            won_count += 1
            print(f"  WON: {bet_id} | {bet.get('selectionName', '?')} | +{winnings:.1f} units -> {manager_key}")
        elif result == 'lost':
            # Wager already deducted at time of bet, nothing to do
            lost_count += 1
            print(f"  LOST: {bet_id} | {bet.get('selectionName', '?')} | {manager_key}")
        elif result == 'push':
            # Refund the wager
            balance_updates[manager_key] = balance_updates.get(manager_key, 0) + wager
            push_count += 1
            print(f"  PUSH: {bet_id} | {bet.get('selectionName', '?')} | refund {wager} units -> {manager_key}")

        # Update bet status
        if not args.dry_run:
            bets_ref.child(bet_id).update({
                'status': result,
                'settledWeek': settle_week,
                'settledAt': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
            })

        settled_count += 1

    print(f"\nSettlement Summary: {settled_count} bets processed")
    print(f"  Won: {won_count} | Lost: {lost_count} | Push: {push_count}")

    # Apply balance updates
    if balance_updates:
        print(f"\nBalance updates:")
        for mgr_key, amount in balance_updates.items():
            current = all_balances.get(mgr_key, {})
            current_total = current.get('total', 0) if isinstance(current, dict) else 0
            new_total = current_total + amount
            print(f"  {mgr_key}: {current_total:.1f} + {amount:.1f} = {new_total:.1f}")
            if not args.dry_run:
                balances_ref.child(mgr_key).update({'total': new_total})

    # Enforce 10-unit minimum balance for all managers
    print(f"\nChecking minimum balance (10 units):")
    # Reload balances after updates
    if not args.dry_run:
        all_balances = balances_ref.get() or {}

    for team in teams:
        manager = normalize_manager_name(team.get('manager', ''))
        mgr_key = sanitize_key(manager)
        current = all_balances.get(mgr_key, {})
        current_total = current.get('total', 0) if isinstance(current, dict) else 0

        # Apply pending balance update for dry-run accuracy
        if args.dry_run and mgr_key in balance_updates:
            current_total += balance_updates[mgr_key]

        if current_total < 10:
            print(f"  {manager} ({mgr_key}): {current_total:.1f} -> 10.0 (topped up)")
            if not args.dry_run:
                balances_ref.child(mgr_key).update({
                    'total': 10,
                    'manager': manager,
                    'topUpWeek': settle_week,
                })
        else:
            print(f"  {manager} ({mgr_key}): {current_total:.1f} (OK)")

    if args.dry_run:
        print("\n[DRY RUN] No changes were made to Firebase.")
    else:
        print("\nBet settlement complete!")


if __name__ == '__main__':
    main()
