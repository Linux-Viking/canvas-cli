import pytest

from canvas_cli import __version__, config
from canvas_cli.cli import cli, safe_filename, strip_tags

from .conftest import BASE_URL, CANARY_TOKEN, api_url

SUBMIT_FILES = "/api/v1/courses/10/assignments/20/submissions/self/files"
SUBMISSIONS = "/api/v1/courses/10/assignments/20/submissions"
UPLOAD_URL = "https://uploads.example/upload"


def test_version(runner):
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_aliases(runner):
    assert runner.invoke(cli, ["help"]).exit_code == 0
    assert "Submit a file" in runner.invoke(cli, ["help", "submit"]).output
    assert runner.invoke(cli, ["help", "nope"]).exit_code != 0


def test_unconfigured_command_explains_setup(runner, mocked):
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 1
    assert "canvas-cli config" in result.output


# --- config ---


def test_config_saves_url_and_token(runner, mocked):
    mocked.get(api_url("/api/v1/users/self"), json={"name": "Ada"})
    result = runner.invoke(cli, ["config"], input="school.instructure.com/\nsecret\n")
    assert result.exit_code == 0, result.output
    assert "Logged in as Ada" in result.output
    assert config.get_url() == BASE_URL
    assert config.get_token() == "secret"


def test_config_token_stdin(runner, mocked):
    mocked.get(api_url("/api/v1/users/self"), json={"name": "Ada"})
    result = runner.invoke(cli, ["config", "--url", BASE_URL, "--token-stdin"], input="secret\n")
    assert result.exit_code == 0, result.output
    assert config.get_token() == "secret"


def test_config_rejects_http(runner):
    result = runner.invoke(cli, ["config", "--url", "http://school.instructure.com"], input="t\n")
    assert result.exit_code == 1
    assert "https" in result.output


def test_config_keeps_aliases(runner, mocked):
    mocked.get(api_url("/api/v1/users/self"), json={})
    config.set_alias("cs101", "123")
    runner.invoke(cli, ["config", "--url", BASE_URL], input="t\n")
    assert config.resolve_alias("cs101") == "123"


def test_config_warns_when_verification_fails(runner, mocked):
    mocked.get(api_url("/api/v1/users/self"), status=401)
    result = runner.invoke(cli, ["config", "--url", BASE_URL], input="t\n")
    assert result.exit_code == 0
    assert "verification failed" in result.output
    assert "expired" in result.output


# --- read commands ---


def test_list_courses_paginates(configured, runner, mocked):
    page2 = api_url("/api/v1/courses?page=2")
    mocked.get(
        api_url("/api/v1/courses"),
        json=[{"id": 1, "name": "Algebra"}],
        headers={"Link": f'<{page2}>; rel="next"'},
    )
    mocked.get(page2, json=[{"id": 2, "name": "Biology"}, {"id": 3}])
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "Algebra" in result.output and "Biology" in result.output


def test_grades(configured, runner, mocked):
    mocked.get(
        api_url("/api/v1/courses"),
        json=[
            {
                "name": "Algebra",
                "enrollments": [{"computed_current_grade": "A", "computed_current_score": 95.1}],
            },
            {"name": "Biology", "enrollments": [{"computed_current_grade": None}]},
        ],
    )
    result = runner.invoke(cli, ["grades"])
    assert result.exit_code == 0
    assert "95.1" in result.output
    assert "N/A" in result.output


def test_todo(configured, runner, mocked):
    mocked.get(
        api_url("/api/v1/users/self/todo"),
        json=[
            {"course_id": 1, "assignment": {"name": "Essay", "due_at": "2026-10-20T23:59:00Z"}},
            {"course_id": 2, "type": "submitting", "quiz": {"title": "Quiz 3"}},
        ],
    )
    result = runner.invoke(cli, ["todo"])
    assert result.exit_code == 0
    assert "Essay" in result.output and "Quiz 3" in result.output


def test_course_alias_resolution(configured, runner, mocked):
    config.set_alias("cs101", "10")
    mocked.get(api_url("/api/v1/courses/10/modules"), json=[{"id": 5, "name": "Week 1"}])
    result = runner.invoke(cli, ["course", "cs101", "list"])
    assert result.exit_code == 0
    assert "Week 1" in result.output


def test_item_details_shows_description(configured, runner, mocked):
    mocked.get(
        api_url("/api/v1/courses/10/modules/5/items"),
        json=[{"id": 77, "content_id": 20, "type": "Assignment", "title": "Essay"}],
    )
    mocked.get(
        api_url("/api/v1/courses/10/modules/5/items/77"),
        json={"id": 77, "content_id": 20, "type": "Assignment", "title": "Essay"},
    )
    mocked.get(
        api_url("/api/v1/courses/10/assignments/20"),
        json={"description": "<p>Write 500 words.</p><p>Cite &amp; source.</p>"},
    )
    result = runner.invoke(cli, ["course", "10", "module", "5", "item", "20", "details"])
    assert result.exit_code == 0, result.output
    assert "Write 500 words." in result.output
    assert "Cite & source." in result.output


def test_item_details_unknown_item(configured, runner, mocked):
    mocked.get(api_url("/api/v1/courses/10/modules/5/items"), json=[])
    result = runner.invoke(cli, ["course", "10", "module", "5", "item", "99", "details"])
    assert result.exit_code == 1


def test_discussion_view(configured, runner, mocked):
    mocked.get(
        api_url("/api/v1/courses/10/discussion_topics/3"),
        json={"title": "Week 1", "message": "<p>Introduce yourself</p>"},
    )
    mocked.get(
        api_url("/api/v1/courses/10/discussion_topics/3/entries"),
        json=[
            {"id": 9, "user_name": "Sam", "created_at": "2026-10-01T00:00:00Z", "message": "Hi!"}
        ],
    )
    result = runner.invoke(cli, ["course", "10", "discuss", "view", "3"])
    assert result.exit_code == 0
    assert "Introduce yourself" in result.output and "Sam" in result.output


# --- write commands ---


def test_discussion_reply_formats_newlines(configured, runner, mocked):
    mocked.post(api_url("/api/v1/courses/10/discussion_topics/3/entries"), json={"id": 11})
    result = runner.invoke(cli, ["course", "10", "discuss", "reply", "3", "line1\nline2"])
    assert result.exit_code == 0
    assert "message=line1%3Cbr%3Eline2" in mocked.calls[0].request.body


def test_discussion_reply_failure_exits_nonzero(configured, runner, mocked):
    mocked.post(api_url("/api/v1/courses/10/discussion_topics/3/entries"), status=403, json={})
    result = runner.invoke(cli, ["course", "10", "discuss", "reply", "3", "hi"])
    assert result.exit_code == 1
    assert len(mocked.calls) == 1


def test_discussion_reply_requires_message(configured, runner):
    result = runner.invoke(cli, ["course", "10", "discuss", "reply", "3"])
    assert result.exit_code == 2


@pytest.fixture
def essay(tmp_path):
    path = tmp_path / "essay.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    return str(path)


def mock_submission_flow(mocked, upload_kwargs, final_state="submitted"):
    mocked.post(
        api_url(SUBMIT_FILES),
        json={"upload_url": UPLOAD_URL, "upload_params": {"key": "abc"}},
    )
    mocked.post(UPLOAD_URL, **upload_kwargs)
    mocked.post(api_url(SUBMISSIONS), json={"id": 500, "workflow_state": final_state})
    mocked.get(
        api_url(f"{SUBMISSIONS}/self"),
        json={"workflow_state": final_state, "attachments": [{"display_name": "essay.pdf"}]},
    )


def test_submit_happy_path(configured, runner, mocked, essay):
    mock_submission_flow(mocked, {"status": 201, "json": {"id": 900}})
    result = runner.invoke(cli, ["submit", essay, "10", "20"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "correctly attached" in result.output

    upload_call = next(c for c in mocked.calls if c.request.url == UPLOAD_URL)
    assert "Authorization" not in upload_call.request.headers
    final_call = next(c for c in mocked.calls if c.request.url == api_url(SUBMISSIONS))
    assert "900" in final_call.request.body


def test_submit_follows_redirect_with_auth(configured, runner, mocked, essay):
    confirm = api_url("/api/v1/files/900/create_success")
    mock_submission_flow(mocked, {"status": 303, "headers": {"Location": confirm}})
    mocked.get(confirm, json={"id": 900})
    result = runner.invoke(cli, ["submit", essay, "10", "20"], input="y\n")
    assert result.exit_code == 0, result.output
    confirm_call = next(c for c in mocked.calls if c.request.url == confirm)
    assert confirm_call.request.headers["Authorization"] == f"Bearer {CANARY_TOKEN}"


def test_submit_cancelled(configured, runner, mocked, essay):
    result = runner.invoke(cli, ["submit", essay, "10", "20"], input="n\n")
    assert result.exit_code == 0
    assert "cancelled" in result.output
    assert len(mocked.calls) == 0


def test_submit_empty_file(configured, runner, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    result = runner.invoke(cli, ["submit", str(empty), "10", "20"], input="y\n")
    assert result.exit_code == 1
    assert "empty" in result.output


def test_submit_upload_slot_failure(configured, runner, mocked, essay):
    mocked.post(api_url(SUBMIT_FILES), status=400, json={"errors": [{"message": "no uploads"}]})
    result = runner.invoke(cli, ["submit", essay, "10", "20"], input="y\n")
    assert result.exit_code == 1
    assert "accepts file uploads" in result.output


def test_submit_upload_storage_failure(configured, runner, mocked, essay):
    mock_submission_flow(mocked, {"status": 500, "body": "storage down"})
    result = runner.invoke(cli, ["submit", essay, "10", "20"], input="y\n")
    assert result.exit_code == 1
    assert not any(c.request.url == api_url(SUBMISSIONS) for c in mocked.calls)


def test_submit_unexpected_state_warns(configured, runner, mocked, essay):
    mock_submission_flow(mocked, {"status": 201, "json": {"id": 900}}, final_state="unsubmitted")
    result = runner.invoke(cli, ["submit", essay, "10", "20"], input="y\n")
    assert "Please verify on Canvas" in result.output


# --- files ---


def test_files_download(configured, runner, mocked, tmp_path):
    mocked.get(
        api_url("/api/v1/courses/10/files"),
        json=[
            {"display_name": "syllabus.pdf", "url": api_url("/files/1/download?verifier=x")},
            {"display_name": "../../evil.sh", "url": "https://cdn.example/evil"},
        ],
    )
    mocked.get(api_url("/files/1/download"), body=b"syllabus")
    mocked.get("https://cdn.example/evil", body=b"payload")

    result = runner.invoke(cli, ["course", "10", "files", "download"])
    assert result.exit_code == 0, result.output

    out = tmp_path / "course_10_files"
    assert (out / "syllabus.pdf").read_bytes() == b"syllabus"
    assert (out / "evil.sh").read_bytes() == b"payload"
    assert not (tmp_path / "evil.sh").exists()

    cdn_call = next(c for c in mocked.calls if c.request.url.startswith("https://cdn.example"))
    assert "Authorization" not in cdn_call.request.headers


def test_files_download_partial_failure_exits_nonzero(configured, runner, mocked):
    mocked.get(
        api_url("/api/v1/courses/10/files"),
        json=[{"display_name": "a.pdf", "url": "https://cdn.example/a"}],
    )
    mocked.get("https://cdn.example/a", status=404)
    result = runner.invoke(cli, ["course", "10", "files", "download"])
    assert result.exit_code == 1
    assert "1 file(s) failed" in result.output


# --- helpers ---


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("notes.pdf", "notes.pdf"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\win.ini", "win.ini"),
        ("..", None),
        ("", None),
        ("bad\x00name.txt", "badname.txt"),
    ],
)
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected


def test_strip_tags():
    assert strip_tags("<p>One</p><p>Two &amp; three</p>") == "One\nTwo & three"
    assert strip_tags(None) == ""
