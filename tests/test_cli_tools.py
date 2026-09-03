"""Unit tests for the Agent Skill CLI scripts."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestCLITools(unittest.TestCase):
    def setUp(self):
        self.python_bin = sys.executable
        self.project_root = Path(__file__).resolve().parent.parent

    def test_itad_cli_check_lowest(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        cmd = [
            self.python_bin,
            str(self.project_root / "skills" / "steam-game-reviewer" / "scripts" / "itad_cli.py"),
            "check-lowest",
            "--title", "Test Automation Game",
            "--price", "10.00",
            "--discount", "50",
            "--output", tmp_path
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.project_root))
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")

        with open(tmp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["game_title"], "Test Automation Game")
        self.assertTrue(data["trigger_alert"])

    def test_news_cli_radar(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        cmd = [
            self.python_bin,
            str(self.project_root / "skills" / "steam-game-reviewer" / "scripts" / "news_cli.py"),
            "radar",
            "--limit", "3",
            "--output", tmp_path
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.project_root))
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")

        with open(tmp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("news", data)


if __name__ == "__main__":
    unittest.main()
