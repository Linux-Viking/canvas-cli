import json
import os
import stat
import sys

import keyring.errors
import pytest

from canvas_cli import config
from canvas_cli.errors import ConfigError

from .conftest import BASE_URL, CANARY_TOKEN


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://school.instructure.com", BASE_URL),
        ("https://school.instructure.com/", BASE_URL),
        ("  school.instructure.com  ", BASE_URL),
        ("HTTPS://school.instructure.com", BASE_URL),
        ("https://lms.example.edu/canvas/", "https://lms.example.edu/canvas"),
    ],
)
def test_normalize_url(raw, expected):
    assert config.normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["http://school.instructure.com", "ftp://x", "", "https://"])
def test_normalize_url_rejects_insecure_or_invalid(raw):
    with pytest.raises(ConfigError):
        config.normalize_url(raw)


def test_get_url_defaults_when_unconfigured():
    assert config.get_url() == config.DEFAULT_URL


def test_get_url_rejects_legacy_http_url():
    with open(config.CONFIG_FILE, "w") as f:
        json.dump({"url": "http://school.instructure.com"}, f)
    with pytest.raises(ConfigError, match="https"):
        config.get_url()


def test_saving_url_preserves_aliases():
    config.set_alias("cs101", 123)
    config.save_url(BASE_URL)
    config.save_url("https://other.instructure.com")
    assert config.resolve_alias("cs101") == "123"


def test_resolve_alias_passthrough():
    assert config.resolve_alias("999") == "999"


def test_token_is_never_written_to_config_file(configured):
    config.set_alias("cs101", 123)
    with open(config.CONFIG_FILE) as f:
        contents = f.read()
    assert CANARY_TOKEN not in contents
    assert set(json.loads(contents)) == {"url", "aliases"}


def test_write_file_refuses_token_keys():
    with pytest.raises(ValueError):
        config._write_file({"url": BASE_URL, "token": "x"})
    with pytest.raises(ValueError):
        config._write_file({"api_token": "x"})


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_config_file_is_owner_only():
    config.save_url(BASE_URL)
    assert stat.S_IMODE(os.stat(config.CONFIG_FILE).st_mode) == 0o600


def test_corrupt_config_file_gives_friendly_error():
    with open(config.CONFIG_FILE, "w") as f:
        f.write("{not json")
    with pytest.raises(ConfigError, match="Could not read"):
        config.get_url()


def test_token_round_trip_through_keyring(isolated):
    config.set_token("abc")
    assert isolated.store[(config.SERVICE_NAME, config.TOKEN_KEY)] == "abc"
    assert config.get_token() == "abc"


def test_env_var_overrides_keyring(configured, monkeypatch):
    monkeypatch.setenv(config.TOKEN_ENV_VAR, "  from-env  ")
    assert config.get_token() == "from-env"


def test_keyring_failure_is_a_config_error(monkeypatch):
    def broken(*args):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(config.keyring, "get_password", broken)
    monkeypatch.setattr(config.keyring, "set_password", broken)
    with pytest.raises(ConfigError, match="CANVAS_TOKEN"):
        config.get_token()
    with pytest.raises(ConfigError):
        config.set_token("abc")


def test_keyring_warning_secure_backend():
    assert config.keyring_warning() is None


def test_keyring_warning_plaintext_backend(monkeypatch):
    PlaintextKeyring = type("PlaintextKeyring", (), {"__module__": "keyrings.alt.file"})
    monkeypatch.setattr(config.keyring, "get_keyring", lambda: PlaintextKeyring())
    assert "plain-text" in config.keyring_warning()


def test_keyring_warning_no_backend(monkeypatch):
    Fail = type("Keyring", (), {"__module__": "keyring.backends.fail"})
    monkeypatch.setattr(config.keyring, "get_keyring", lambda: Fail())
    assert "No usable system keyring" in config.keyring_warning()
