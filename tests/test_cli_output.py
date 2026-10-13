"""The CLI must keep printing when a job title is not representable in the console code page."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from io import BytesIO, TextIOWrapper
from pathlib import Path
from unittest.mock import patch

from job_agent.cli import main
from job_agent.normalizer import normalize
from job_agent.storage import Store

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import write_config, write_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import write_config, write_profile

EMOJI_TITLE = "Werkstudent \U0001F525 Data & AI \u2013 Junior"
EVALUATION = {"score": 60, "assessment": "borderline", "excluded": False, "strong_matches": [], "potential_gaps": [], "concerns": [], "uncertainties": []}


def fill(database: Path, count: int = 4000) -> None:
    store = Store(database)
    store.close()
    connection = sqlite3.connect(database)
    payload = json.dumps({"title": EMOJI_TITLE, "source": "adzuna", "requirements": [], "metadata": {}})
    evaluation = json.dumps({"score": 60, "assessment": "borderline", "excluded": False})
    connection.executemany("INSERT INTO jobs(source_url,external_job_id,payload,discovered_at,last_seen_at,viewed,status,rejection_reason) VALUES (?,?,?,?,?,?,?,?)", [(None, f"id-{index}", payload, "2026-01-01", "2026-01-01", 0, "discovered", None) for index in range(count)])
    connection.executemany("INSERT INTO evaluations(job_id,payload,created_at) VALUES (?,?,?)", [(index + 1, evaluation, "2026-01-01") for index in range(count)])
    connection.commit()
    connection.close()


class CliOutputTests(unittest.TestCase):
    def test_redirected_listing_prints_titles_outside_the_console_code_page(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "jobs.sqlite"
            profile_path = write_profile(directory); config_path = write_config(directory)
            store = Store(database)
            store.save_job(normalize({"title": EMOJI_TITLE, "source": "adzuna", "external_job_id": "1", "source_url": "https://example.test/1"}), EVALUATION)
            store.close()
            buffer = BytesIO()
            stream = TextIOWrapper(buffer, encoding="cp1252", errors="strict", newline="")
            arguments = ["--profile", str(profile_path), "--config", str(config_path), "--database", str(database), "list"]
            with patch("sys.stdout", stream), patch("sys.stderr", stream):
                main(arguments)
            stream.flush()
            output = buffer.getvalue().decode("utf-8")
            self.assertIn("60/100", output)
            self.assertIn(EMOJI_TITLE, output)

    def test_reader_closing_the_pipe_early_exits_quietly(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "jobs.sqlite"
            profile_path = write_profile(directory); config_path = write_config(directory)
            fill(database)
            command = [sys.executable, "-m", "job_agent.cli", "--profile", str(profile_path), "--config", str(config_path), "--database", str(database), "list"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            process.stdout.readline()
            process.stdout.close()
            errors = process.stderr.read()
            process.stderr.close()
            process.wait()
            self.assertEqual(errors, b"")


if __name__ == "__main__":
    unittest.main()
