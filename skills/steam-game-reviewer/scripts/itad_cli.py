"""CLI tool for IsThereAnyDeal Historical Low Price checks in BRL.
Implements the strict filter: if current_price <= historical_low trigger alert, otherwise exit silently.
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

from tools.itad_api import ITADClient, evaluate_price_alert


def write_output(data, output_file: str):
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
    parser = argparse.ArgumentParser(description="IsThereAnyDeal Lowest Price CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: check-lowest
    p_check = subparsers.add_parser("check-lowest", help="Check if current price matches or beats historical low")
    p_check.add_argument("--title", required=True, help="Game title")
    p_check.add_argument("--appid", type=int, required=False, default=None, help="Steam App ID")
    p_check.add_argument("--price", type=float, required=True, help="Current price in BRL")
    p_check.add_argument("--discount", type=int, required=True, help="Discount percentage (e.g. 50)")
    p_check.add_argument("--output", required=True, help="Path to output JSON file")

    # Subcommand: history
    p_hist = subparsers.add_parser("history", help="Look up historical low price in BRL for a game")
    p_hist.add_argument("--title", required=True, help="Game title")
    p_hist.add_argument("--output", required=True, help="Path to output JSON file")

    args = parser.parse_args()
    client = ITADClient()

    if args.command == "check-lowest":
        res = evaluate_price_alert(
            game_title=args.title,
            current_price=args.price,
            discount_percent=args.discount,
            appid=args.appid,
            itad_client=client
        )
        write_output(res, args.output)

    elif args.command == "history":
        game_id = client.lookup_game(args.title)
        low_info = client.get_historical_low(game_id) if game_id else None
        data = {
            "game_title": args.title,
            "itad_game_id": game_id,
            "historical_low": low_info
        }
        write_output(data, args.output)

    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
