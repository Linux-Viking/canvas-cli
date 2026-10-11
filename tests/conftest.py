import keyring
import keyring.backend
import pytest
import responses
from click.testing import CliRunner

from canvas_cli import api, config

BASE_URL = "https://school.instructure.com"
# A recognisable fake token. Leak tests assert it never appears in output or on disk.
CANARY_TOKEN = "7~CANARYtokenDoNotLeak0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKL"


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Never touch the real keyring, config file, environment, or clock."""
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / ".canvas_cli.json"))
    monkeypatch.delenv(config.TOKEN_ENV_VAR, raising=False)
    monkeypatch.setattr(api, "_sleep", lambda seconds: None)
    monkeypatch.chdir(tmp_path)

    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    api.reset_client()
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def configured():
    config.save_url(BASE_URL)
    config.set_token(CANARY_TOKEN)
    return CANARY_TOKEN


@pytest.fixture
def mocked():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def runner():
    return CliRunner()


def api_url(path):
    return f"{BASE_URL}{path}"
