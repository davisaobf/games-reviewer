"""CLI tool for Gaming News Radar.
Scans RSS feeds and filters news by user taste profile (mechanical precision & logic puzzles).
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

from tools.news_radar import NewsRadar


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
    parser = argparse.ArgumentParser(description="Gaming News Radar CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: radar
    p_radar = subparsers.add_parser("radar", help="Scan gaming feeds and return news matching user profile")
    p_radar.add_argument("--min-score", type=int, default=2, help="Minimum relevance score (default: 2)")
    p_radar.add_argument("--limit", type=int, default=10, help="Maximum number of news items to return")
    p_radar.add_argument("--output", required=True, help="Path to output JSON file")

    args = parser.parse_args()
    radar = NewsRadar()

    if args.command == "radar":
        news = radar.get_relevant_news(min_score=args.min_score, max_items=args.limit)
        data = {
            "total_matches": len(news),
            "news": news
        }
        write_output(data, args.output)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
