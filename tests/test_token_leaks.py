"""Regression guard: the API token must never reach output, errors, or disk.

Each scenario uses a worst-case server that echoes the token back in its
error body, then checks stdout, stderr, and every file under the temp home.
"""

import pytest
import requests

from canvas_cli import config
from canvas_cli.cli import cli

from .conftest import CANARY_TOKEN, api_url

ECHO_BODY = (
    f'{{"errors": [{{"message": "bad token {CANARY_TOKEN}"}}], "auth": "Bearer {CANARY_TOKEN}"}}'
)


def assert_no_leak(result, tmp_path):
    assert CANARY_TOKEN not in result.output
    assert CANARY_TOKEN not in (result.stderr or "")
    assert CANARY_TOKEN not in repr(result.exception or "")
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert CANARY_TOKEN.encode() not in path.read_bytes(), path


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 500])
def test_http_errors_do_not_leak_token(configured, mocked, runner, tmp_path, status):
    mocked.get(api_url("/api/v1/courses"), status=status, body=ECHO_BODY)
    result = runner.invoke(cli, ["list"])
    assert result.exit_code != 0
    assert_no_leak(result, tmp_path)


@pytest.mark.parametrize(
    "exc",
    [
        requests.exceptions.ConnectionError(f"failed with header Bearer {CANARY_TOKEN}"),
        requests.exceptions.ReadTimeout(f"timeout {CANARY_TOKEN}"),
        requests.exceptions.InvalidHeader(f"invalid {CANARY_TOKEN}"),
    ],
)
def test_network_errors_do_not_leak_token(configured, mocked, runner, tmp_path, exc):
    mocked.get(api_url("/api/v1/courses"), body=exc)
    result = runner.invoke(cli, ["list"])
    assert result.exit_code != 0
    assert_no_leak(result, tmp_path)


def test_config_command_does_not_echo_or_store_token(mocked, runner, tmp_path):
    mocked.get(api_url("/api/v1/users/self"), status=401, body=ECHO_BODY)
    result = runner.invoke(
        cli, ["config", "--url", "school.instructure.com"], input=f"{CANARY_TOKEN}\n"
    )
    assert result.exit_code == 0, result.output
    assert config.get_token() == CANARY_TOKEN
    assert_no_leak(result, tmp_path)


def test_token_not_accepted_as_cli_argument(runner):
    result = runner.invoke(cli, ["config", "--token", CANARY_TOKEN])
    assert result.exit_code == 2
    assert "No such option" in result.output


def test_aliases_and_errors_with_env_token(monkeypatch, mocked, runner, tmp_path):
    monkeypatch.setenv(config.TOKEN_ENV_VAR, CANARY_TOKEN)
    config.save_url("https://school.instructure.com")
    mocked.get(api_url("/api/v1/users/self/todo"), status=500, body=ECHO_BODY)
    runner.invoke(cli, ["alias", "set", "cs101", "42"])
    result = runner.invoke(cli, ["todo"])
    assert result.exit_code != 0
    assert_no_leak(result, tmp_path)
