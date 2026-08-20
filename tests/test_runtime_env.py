from __future__ import annotations

import os
from pathlib import Path

from jobradar_app.runtime_env import load_env_file


def test_load_env_file_sets_missing_values_only(tmp_path: Path) -> None:
    env_file = tmp_path / "jobradar.env"
    env_file.write_text(
        "# comment\n"
        "JOBRADAR_SERVICE_TOKEN=abc123\n"
        "JOBRADAR_CAREEROPS_ROOT='/tmp/career-ops'\n"
        "INVALID_LINE\n",
        encoding="utf-8",
    )

    os.environ.pop("JOBRADAR_SERVICE_TOKEN", None)
    os.environ["JOBRADAR_CAREEROPS_ROOT"] = "/already/set"

    loaded = load_env_file(env_file)

    assert loaded["JOBRADAR_SERVICE_TOKEN"] == "abc123"
    assert loaded["JOBRADAR_CAREEROPS_ROOT"] == "/tmp/career-ops"
    assert os.environ["JOBRADAR_SERVICE_TOKEN"] == "abc123"
    assert os.environ["JOBRADAR_CAREEROPS_ROOT"] == "/already/set"


def test_load_env_file_returns_empty_for_missing_path(tmp_path: Path) -> None:
    loaded = load_env_file(tmp_path / "missing.env")
    assert loaded == {}
