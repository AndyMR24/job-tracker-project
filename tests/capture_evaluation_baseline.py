"""Regenerate tests/evaluation_baseline.json.

Run this *before* changing evaluation behaviour (for example before moving hard-coded weights into
search configuration) so the golden file records the current implementation's output:

    python -m tests.capture_evaluation_baseline

`tests/test_evaluation_config.py` compares live evaluations against that file, so the fixture set in
`tests/support.py` must not change at the same time as the evaluator.
"""
from __future__ import annotations

import json
from pathlib import Path

from job_agent.evaluator import evaluate
from job_agent.normalizer import normalize
from job_agent.profile import Profile

try:  # works for "python -m tests.capture_evaluation_baseline"
    from support import evaluation_cases, sample_config, sample_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import evaluation_cases, sample_config, sample_profile

OUTPUT = Path(__file__).with_name("evaluation_baseline.json")


def main() -> None:
    profile, config = Profile(sample_profile()), sample_config()
    cases = [
        {"case": case["case"], "evaluation": evaluate(normalize(dict(case["job"])), profile, config).to_dict()}
        for case in evaluation_cases()
    ]
    document = {
        "_note": "Golden evaluation output captured from the implementation before the configurable evaluation weights were added.",
        "_fixtures": "tests/support.py:evaluation_cases",
        "cases": cases,
    }
    OUTPUT.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(cases)} cases")


if __name__ == "__main__":
    main()
