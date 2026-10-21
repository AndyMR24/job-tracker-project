"""Profile and search-config validation plus database-free CLI validation."""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_agent.cli import main
from job_agent.profile import ValidationError, load_config, load_profile

try:
    from support import sample_config, sample_profile, write_config, write_profile
except ImportError:  # pragma: no cover
    from tests.support import sample_config, sample_profile, write_config, write_profile


class ValidationTests(unittest.TestCase):
    def test_cli_validate_does_not_create_or_modify_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = write_profile(root)
            config = write_config(root)
            missing_database = root / "missing.sqlite3"
            with patch("job_agent.cli.Store", side_effect=AssertionError("Store must not be constructed")):
                main(["--profile", str(profile), "--config", str(config), "--database", str(missing_database), "validate"])
            self.assertFalse(missing_database.exists())

            existing_database = root / "existing.sqlite3"
            connection = sqlite3.connect(existing_database)
            connection.execute("CREATE TABLE sentinel(value TEXT)")
            connection.execute("INSERT INTO sentinel VALUES ('keep')")
            connection.execute("PRAGMA user_version = 7")
            connection.commit()
            connection.close()
            with patch("job_agent.cli.Store", side_effect=AssertionError("Store must not be constructed")):
                main(["--profile", str(profile), "--config", str(config), "--database", str(existing_database), "validate"])
            connection = sqlite3.connect(existing_database)
            self.assertEqual(connection.execute("SELECT value FROM sentinel").fetchone()[0], "keep")
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(
                [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")],
                ["sentinel"],
            )
            connection.close()

    def test_profile_nested_values_are_validated_with_field_paths(self):
        cases = []
        data = copy.deepcopy(sample_profile())
        data["skills"][0]["name"] = 123
        cases.append((data, "skills[0]"))
        data = copy.deepcopy(sample_profile())
        del data["identity"]["city"]
        cases.append((data, "identity"))
        data = copy.deepcopy(sample_profile())
        data["education"][0] = "not an object"
        cases.append((data, "education[0]"))
        data = copy.deepcopy(sample_profile())
        data["projects"][0]["technologies"] = ["Python", None]
        cases.append((data, "projects[0].technologies[1]"))
        data = copy.deepcopy(sample_profile())
        data["thesis"]["name"] = 4
        cases.append((data, "thesis"))
        data = copy.deepcopy(sample_profile())
        data["languages"] = ["English"]
        cases.append((data, "languages"))
        data = copy.deepcopy(sample_profile())
        data["certifications"] = [None]
        cases.append((data, "certifications[0]"))
        data = copy.deepcopy(sample_profile())
        data["technical_practice"]["Python"] = 3
        cases.append((data, "technical_practice"))
        data = copy.deepcopy(sample_profile())
        data["employment_eligibility"] = "Germany"
        cases.append((data, "employment_eligibility"))

        with tempfile.TemporaryDirectory() as directory:
            for index, (data, expected) in enumerate(cases):
                with self.subTest(field=expected):
                    path = write_profile(directory, data)
                    with self.assertRaisesRegex(ValidationError, expected.replace("[", "\\[").replace("]", "\\]")):
                        load_profile(path)

    def test_valid_profile_with_optional_fields_still_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = load_profile(write_profile(directory, sample_profile()))
        self.assertTrue(profile.skills)
        self.assertTrue(profile.languages)

    def test_technical_practice_accepts_compatible_string_lists(self):
        data = copy.deepcopy(sample_profile())
        data["technical_practice"] = {"Python": ["Practice A", "Practice B"]}
        with tempfile.TemporaryDirectory() as directory:
            profile = load_profile(write_profile(directory, data))
        self.assertEqual(profile.data["technical_practice"]["Python"], ["Practice A", "Practice B"])

    def test_configuration_list_contents_are_validated(self):
        cases = []
        for field in ("target_roles", "locations", "work_arrangements", "preferred_languages"):
            data = copy.deepcopy(sample_config())
            data[field] = [None]
            cases.append((data, field))
        data = copy.deepcopy(sample_config())
        data["maximum_commute_note"] = 3
        cases.append((data, "maximum_commute_note"))
        data = copy.deepcopy(sample_config())
        data["search_queries"]["secondary"] = []
        cases.append((data, "search_queries.secondary"))

        with tempfile.TemporaryDirectory() as directory:
            for data, expected in cases:
                with self.subTest(field=expected):
                    path = write_config(directory, data)
                    with self.assertRaisesRegex(ValidationError, expected):
                        load_config(path)

    def test_configuration_and_profile_must_be_json_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "array.json"
            path.write_text(json.dumps([]), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "must contain a JSON object"):
                load_profile(path)
            with self.assertRaisesRegex(ValidationError, "must contain a JSON object"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
