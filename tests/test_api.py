import pytest
import requests
import responses

from canvas_cli import api
from canvas_cli.errors import AuthError, CanvasError, RateLimitError

from .conftest import BASE_URL, CANARY_TOKEN, api_url


@pytest.fixture
def client(configured):
    return api.CanvasClient()


def auth_header(call):
    return call.request.headers.get("Authorization")


def test_sends_bearer_token_to_canvas(client, mocked):
    mocked.get(api_url("/api/v1/courses"), json=[])
    client.request("GET", "/api/v1/courses")
    assert auth_header(mocked.calls[0]) == f"Bearer {CANARY_TOKEN}"
    assert mocked.calls[0].request.headers["User-Agent"].startswith("canvas-term/")


@pytest.mark.parametrize(
    "url",
    [
        "https://s3.amazonaws.com/bucket/file.pdf",
        "https://school.instructure.com.evil.example/file",
        "http://school.instructure.com/files/1/download",
    ],
)
def test_never_sends_token_to_other_hosts(client, mocked, url):
    mocked.get(url, body=b"data")
    client.request("GET", url)
    assert auth_header(mocked.calls[0]) is None


def test_applies_timeout(client, monkeypatch):
    seen = {}

    def fake_request(method, url, **kwargs):
        seen.update(kwargs)
        raise requests.exceptions.ConnectTimeout()

    monkeypatch.setattr(client.session, "request", fake_request)
    with pytest.raises(CanvasError):
        client.request("GET", "/api/v1/courses")
    assert seen["timeout"] == api.TIMEOUT


def test_missing_token_is_auth_error(mocked):
    client = api.CanvasClient(base_url=BASE_URL)
    with pytest.raises(AuthError, match="canvas-cli config"):
        client.request("GET", "/api/v1/courses")
    assert len(mocked.calls) == 0


def test_401_explains_expired_token(client, mocked):
    mocked.get(
        api_url("/api/v1/courses"),
        status=401,
        json={"errors": [{"message": "Invalid access token."}]},
    )
    with pytest.raises(AuthError, match="expired") as exc:
        client.request("GET", "/api/v1/courses")
    assert "canvas-cli config" in exc.value.message
    assert len(mocked.calls) == 1  # never retried


def test_404_message(client, mocked):
    mocked.get(
        api_url("/api/v1/courses/1"), status=404, json={"errors": [{"message": "not found"}]}
    )
    with pytest.raises(CanvasError, match="Not found"):
        client.request("GET", "/api/v1/courses/1")


def test_error_detail_from_canvas_errors_list(client, mocked):
    mocked.get(api_url("/x"), status=400, json={"errors": [{"message": "bad thing"}]})
    with pytest.raises(CanvasError, match="400.*bad thing"):
        client.request("GET", "/x")


def test_403_permission_is_not_rate_limit(client, mocked):
    mocked.get(api_url("/x"), status=403, json={"status": "unauthorized"})
    with pytest.raises(CanvasError, match="Permission denied"):
        client.request("GET", "/x")
    assert len(mocked.calls) == 1


def test_canvas_rate_limit_retries_then_succeeds(client, mocked):
    mocked.get(api_url("/x"), status=403, body="403 Forbidden (Rate Limit Exceeded)")
    mocked.get(api_url("/x"), status=403, body="403 Forbidden (Rate Limit Exceeded)")
    mocked.get(api_url("/x"), json={"ok": True})
    assert client.get_json("/x") == {"ok": True}
    assert len(mocked.calls) == 3


def test_rate_limit_retries_post_too(client, mocked):
    # Throttled requests are rejected before processing, so retrying is safe.
    mocked.post(api_url("/x"), status=429, headers={"Retry-After": "2"})
    mocked.post(api_url("/x"), json={"id": 1})
    assert client.request("POST", "/x").json() == {"id": 1}


def test_rate_limit_honours_retry_after(client, mocked, monkeypatch):
    slept = []
    monkeypatch.setattr(api, "_sleep", slept.append)
    mocked.get(api_url("/x"), status=429, headers={"Retry-After": "7"})
    mocked.get(api_url("/x"), json={})
    client.request("GET", "/x")
    assert slept == [7]


def test_rate_limit_gives_up(client, mocked):
    mocked.get(api_url("/x"), status=403, body="Rate Limit Exceeded")
    with pytest.raises(RateLimitError):
        client.request("GET", "/x")
    assert len(mocked.calls) == api.MAX_RETRIES + 1


def test_5xx_retried_for_get(client, mocked):
    mocked.get(api_url("/x"), status=503)
    mocked.get(api_url("/x"), json=[1])
    assert client.get_json("/x") == [1]


def test_5xx_not_retried_for_post(client, mocked):
    mocked.post(api_url("/x"), status=502)
    with pytest.raises(CanvasError, match="502"):
        client.request("POST", "/x")
    assert len(mocked.calls) == 1


def test_connection_error_retried_for_get(client, mocked):
    mocked.get(api_url("/x"), body=requests.exceptions.ConnectionError("boom"))
    mocked.get(api_url("/x"), json=[])
    assert client.get_json("/x") == []


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (requests.exceptions.ConnectionError("boom"), "Could not connect"),
        (requests.exceptions.ReadTimeout("slow"), "timed out"),
    ],
)
def test_network_failures_have_clear_messages(client, mocked, exc, message):
    mocked.get(api_url("/x"), body=exc)
    with pytest.raises(CanvasError, match=message):
        client.request("GET", "/x")


def test_connection_error_not_retried_for_post(client, mocked):
    mocked.post(api_url("/x"), body=requests.exceptions.ConnectionError("boom"))
    with pytest.raises(CanvasError):
        client.request("POST", "/x")
    assert len(mocked.calls) == 1


def test_non_json_response(client, mocked):
    mocked.get(api_url("/x"), body="<html>maintenance</html>")
    with pytest.raises(CanvasError, match="non-JSON"):
        client.get_json("/x")


def test_get_all_follows_pagination(client, mocked):
    page2 = api_url("/api/v1/courses?page=2&per_page=100")
    mocked.get(
        api_url("/api/v1/courses"),
        json=[{"id": 1}],
        headers={"Link": f'<{page2}>; rel="next"'},
        match=[
            responses.matchers.query_param_matcher(
                {"per_page": "100", "enrollment_state": "active"}
            )
        ],
    )
    mocked.get(page2, json=[{"id": 2}])
    result = client.get_all("/api/v1/courses", params={"enrollment_state": "active"})
    assert result == [{"id": 1}, {"id": 2}]


def test_get_all_does_not_follow_next_link_off_host(client, mocked):
    mocked.get(
        api_url("/api/v1/courses"),
        json=[{"id": 1}],
        headers={"Link": '<https://evil.example/steal?page=2>; rel="next"'},
    )
    assert client.get_all("/api/v1/courses") == [{"id": 1}]
    assert len(mocked.calls) == 1


def test_download_streams_to_file(client, mocked, tmp_path):
    mocked.get("https://files.example/abc", body=b"hello")
    dest = tmp_path / "out.txt"
    client.download("https://files.example/abc", str(dest))
    assert dest.read_bytes() == b"hello"
    assert auth_header(mocked.calls[0]) is None


def test_failed_download_leaves_no_partial_file(client, mocked, tmp_path):
    mocked.get(api_url("/files/1/download"), status=500)
    with pytest.raises(CanvasError):
        client.download(api_url("/files/1/download"), str(tmp_path / "out.txt"))
    assert list(tmp_path.iterdir()) == [tmp_path / ".canvas_cli.json"]


@pytest.mark.parametrize(
    "text",
    [
        f"token {CANARY_TOKEN} here",
        "Authorization: Bearer sometoken123",
        "https://x/?access_token=abc123&page=2",
    ],
)
def test_redact(text):
    out = api.redact(text, [CANARY_TOKEN])
    assert "[REDACTED]" in out
    assert CANARY_TOKEN not in out
    assert "sometoken123" not in out
    assert "abc123" not in out
