"""Backward-compatibility guards for users upgrading from earlier releases."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from canvas_cli import config

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_both_command_names_are_installed():
    scripts = tomllib.loads(PYPROJECT.read_text())["project"]["scripts"]
    assert scripts["canvas-term"] == "canvas_cli.cli:cli"
    assert scripts["canvas-cli"] == "canvas_cli.cli:cli"  # legacy alias from 0.2.x


@pytest.mark.parametrize("prog_name", ["canvas-term", "canvas-cli"])
def test_version_reports_invoked_name(prog_name):
    # Run in a fresh process: Click caches the program name after the first --version.
    code = f"from canvas_cli.cli import cli; cli.main(['--version'], prog_name={prog_name!r})"
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"{prog_name}, version ")


def test_storage_names_unchanged():
    # Renaming these would orphan users' saved tokens and aliases.
    assert config.SERVICE_NAME == "canvas_cli"
    assert config.TOKEN_KEY == "api_token"
    assert os.path.basename(os.path.expanduser("~/.canvas_cli.json")) == ".canvas_cli.json"
    assert config.CONFIG_FILE.endswith(".canvas_cli.json")
