"""CLI tool for Steam operations (Profile, Wishlist, Game Details, Community Reviews).
Follows the Antigravity Agent Skill CLI pattern with stdlib and file redirection.
"""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.steam_api import SteamClient
from tools.community_reviews import CommunityReviewAnalyzer


def write_output(data, output_file: str):
    """Writes data to a JSON file and prints a brief status message."""
    try:
        path = Path(output_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Success! Data written to: {output_file}")
    except Exception as e:
        print(f"Error writing to file {output_file}: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Steam Game Reviewer CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: profile
    p_profile = subparsers.add_parser("profile", help="Fetch user profile and owned/recent games")
    p_profile.add_argument("--user", required=True, help="Steam vanity username or SteamID64")
    p_profile.add_argument("--output", required=True, help="Path to output JSON file")

    # Subcommand: wishlist
    p_wish = subparsers.add_parser("wishlist", help="Fetch user wishlist games with BRL prices")
    p_wish.add_argument("--user", required=True, help="Steam vanity username or SteamID64")
    p_wish.add_argument("--output", required=True, help="Path to output JSON file")

    # Subcommand: game
    p_game = subparsers.add_parser("game", help="Fetch official Steam store details for an appid")
    p_game.add_argument("--appid", type=int, required=True, help="Steam App ID")
    p_game.add_argument("--output", required=True, help="Path to output JSON file")

    # Subcommand: reviews
    p_rev = subparsers.add_parser("reviews", help="Fetch community reviews and consensus for an appid")
    p_rev.add_argument("--appid", type=int, required=True, help="Steam App ID")
    p_rev.add_argument("--title", required=False, default="", help="Optional game title for Reddit consensus")
    p_rev.add_argument("--output", required=True, help="Path to output JSON file")

    args = parser.parse_args()
    client = SteamClient(user_id=getattr(args, "user", None))
    analyzer = CommunityReviewAnalyzer()

    if args.command == "profile":
        games = client.get_owned_games()
        data = {
            "user": args.user,
            "total_games": len(games),
            "games": games
        }
        write_output(data, args.output)

    elif args.command == "wishlist":
        wishlist = client.get_wishlist()
        data = {
            "user": args.user,
            "count": len(wishlist),
            "wishlist": wishlist
        }
        write_output(data, args.output)

    elif args.command == "game":
        details = client.get_game_details(args.appid)
        if not details:
            print(f"Could not retrieve details for appid {args.appid}", file=sys.stderr)
            sys.exit(1)
        write_output(details, args.output)

    elif args.command == "reviews":
        title = args.title or f"AppID {args.appid}"
        summary = analyzer.summarize_game_consensus(args.appid, title)
        write_output(summary, args.output)

    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
