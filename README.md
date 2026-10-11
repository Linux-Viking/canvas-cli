# canvas-term

[![CI](https://github.com/Linux-Viking/canvas-term/actions/workflows/ci.yml/badge.svg)](https://github.com/Linux-Viking/canvas-term/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/canvas-term)](https://pypi.org/project/canvas-term/)
[![Python](https://img.shields.io/pypi/pyversions/canvas-term)](https://pypi.org/project/canvas-term/)

A lightning-fast, terminal-based operating system for your degree.

`canvas-term` is a command-line interface for the Canvas Learning Management System (LMS). It lets students check grades, view upcoming assignments, take part in discussion boards, bulk-download course files, and submit assignments (PDFs, documents, code) from the terminal without opening a web browser.

## Features

* **Submissions**: Upload local files directly to assignments using Canvas's native 3-step upload protocol, with automatic post-submission verification.
* **To-Do List**: View upcoming assignments and due dates across all active courses.
* **Grades**: Check your current score and letter grade for every course.
* **Discussion Boards**: Read prompts and replies, and post top-level or threaded replies.
* **Bulk File Downloader**: Download all slides, syllabi, and readings from a course with one command.
* **Inbox**: List your unread Canvas messages.
* **Aliases**: Map Canvas IDs (like `123456`) to memorable names (like `cs101`).

## Quick start

```bash
pipx install canvas-term
canvas-term config     # paste your Canvas URL and API token (see Configuration)
canvas-term grades
```

```text
Course Name                         | Grade | Score
-------------------------------------------------------
CS 101: Intro to Programming        | A     | 94.2
MATH 221: Calculus II               | B+    | 88.5
ENGL 110: College Writing           | A-    | 91.0
HIST 150: World History             | N/A   | N/A
```

## Installation

Requires **Python 3.11 or newer**.

### Recommended: pipx

[pipx](https://pipx.pypa.io/) installs the CLI into its own isolated environment and puts `canvas-term` on your `PATH`.

```bash
pipx install canvas-term
```

> **Upgrading from 0.2.x?** The command is now **`canvas-term`**. The old **`canvas-cli`** command still works as an alias, and your saved token, Canvas URL, and aliases carry over unchanged.

### pip

Many Linux distributions block system-wide `pip` installs ([PEP 668](https://peps.python.org/pep-0668/)), so install into a virtual environment:

```bash
python3 -m venv ~/.venvs/canvas-term
~/.venvs/canvas-term/bin/pip install canvas-term
~/.venvs/canvas-term/bin/canvas-term --version
```

Add `~/.venvs/canvas-term/bin` to your `PATH`, or symlink `canvas-term` into a directory that's already on it.

### Latest development version

```bash
pipx install git+https://github.com/Linux-Viking/canvas-term.git
```

### Upgrading and uninstalling

```bash
pipx upgrade canvas-term
pipx uninstall canvas-term
```

## Configuration

### 1. Generate an API token

1. Log into your school's Canvas website.
2. Click **Account** (your profile picture) → **Settings**.
3. Scroll to **Approved Integrations** and click **+ New Access Token**.
4. Give it a purpose (e.g. `canvas-term`), optionally an expiry date, and click **Generate Token**.
5. Copy the token immediately. Canvas won't show it again.

### 2. Configure the CLI

```bash
canvas-term config
```

You'll be prompted for:

* **Canvas Domain**: your school's Canvas URL, e.g. `https://school.instructure.com`. Must be `https://`; a bare hostname is fine.
* **Canvas API Token**: paste the token. Input is hidden.

The CLI then checks the token by asking Canvas who you are:

```text
Configuration saved for https://school.instructure.com.
Verifying token...
Logged in as Ada Lovelace.
```

Re-run `canvas-term config` whenever your token expires. Your aliases are kept.

#### Non-interactive setup

The token is deliberately **not** accepted as a command-line argument, because arguments end up in shell history and process listings. For scripts, pipe it on stdin:

```bash
pass show canvas/token | canvas-term config --url https://school.instructure.com --token-stdin
```

#### Using an environment variable instead of the keyring

If `CANVAS_TOKEN` is set, it takes priority over the keyring. This is useful on servers, in containers, or where no keyring is available:

```bash
export CANVAS_TOKEN="$(pass show canvas/token)"
canvas-term grades
```

### Where things are stored

| What | Where |
| --- | --- |
| API token | Your OS keyring (macOS Keychain, Windows Credential Locker, or Linux Secret Service such as GNOME Keyring or KWallet), or `$CANVAS_TOKEN` |
| Canvas URL and aliases | `~/.canvas_cli.json` (permissions `0600`, never contains the token) |

## Usage

Every command and group accepts `-h`, `--help`, or a trailing `help`:

```bash
canvas-term help
canvas-term course help
canvas-term submit -h
canvas-term --version
```

### Courses, modules, and items

```bash
canvas-term list                                  # active courses and their IDs
canvas-term course 123456 list                    # modules in a course
canvas-term course 123456 module 7890 list        # items in a module
canvas-term course 123456 module 7890 item 555 details   # item info + assignment description
```

### Aliases

```bash
canvas-term alias set cs101 123456
canvas-term course cs101 list
```

Aliases work anywhere a course, module, item, assignment, or topic ID is expected.

### Grades, to-dos, and inbox

```bash
canvas-term grades
canvas-term todo
canvas-term inbox list
```

### Submitting an assignment

```bash
canvas-term submit ./my_essay.pdf cs101 987654
```

You'll see a pre-submission summary and must confirm. After uploading, the CLI asks Canvas to confirm that the submission was received and the file is attached.

> **Find the assignment ID** with `canvas-term course <course> module <module> item <item> details`, which prints the exact `submit` command to run.

### Discussions

```bash
# List topics, then read a topic and its replies
canvas-term course cs101 discuss list
canvas-term course cs101 discuss view 555123

# Read the threaded replies under one entry
canvas-term course cs101 discuss view 555123 --entry-id 999888

# Reply to the main prompt (\n becomes a line break)
canvas-term course cs101 discuss reply 555123 "Here is my response...\nSecond paragraph."

# Reply from a file (newlines are preserved)
canvas-term course cs101 discuss reply 555123 --file ./response.md

# Threaded reply to a specific student
canvas-term course cs101 discuss reply 555123 "I agree!" --entry-id 999888
```

### Downloading course files

```bash
canvas-term course cs101 files download    # saves to ./course_<id>_files/
```

## Errors and troubleshooting

Commands exit with status `0` on success and non-zero on failure, so you can use them in scripts.

| Message | What to do |
| --- | --- |
| `No API token configured` | Run `canvas-term config`. |
| `Canvas rejected your API token (401 Unauthorized)…` | Your token expired or was revoked. Generate a new one and run `canvas-term config`. |
| `Canvas is rate limiting requests…` | The CLI already retried with backoff. Wait a minute and try again. |
| `Could not connect to …` / `… timed out` | Check your network connection and Canvas URL. Read-only requests are retried automatically. Submissions and replies are **never** retried automatically, so they can't be posted twice. |
| `Permission denied (403)` | Your account doesn't have access to that resource (e.g. the course is concluded or the item is locked). |
| `Not found (404)` | Check the ID or alias. In `module list`, use the ID shown in the first column. |
| `Canvas URL must use https://` | Re-run `canvas-term config` with an `https://` URL. |

### Keyring troubleshooting (Linux)

`canvas-term` uses the [`keyring`](https://pypi.org/project/keyring/) library. On a desktop with GNOME Keyring or KWallet running, it works out of the box. On headless servers, WSL, or minimal installs, there may be no keyring service:

* **`Could not read/save the API token to the system keyring`**: either start a Secret Service provider (e.g. `gnome-keyring-daemon`) or use the `CANVAS_TOKEN` environment variable.
* **Warning about a plain-text keyring backend**: some setups fall back to `keyrings.alt`, which stores secrets unencrypted on disk. `canvas-term config` warns you if so. Prefer a real keyring or `CANVAS_TOKEN`.
* Run `pipx run keyring --list-backends` to see which keyring backends are available.

## Security

* Your API token is stored only in the OS keyring (or read from `$CANVAS_TOKEN`). It is never written to the config file, accepted as a command-line argument, or printed in output. Error messages are redacted.
* The token is sent only over `https://`, and only to your configured Canvas host. File downloads and uploads to external storage (e.g. S3) never receive it.
* Treat your token like a password: it grants full access to your Canvas account. Set an expiry date when you generate it and revoke it in Canvas settings if it's ever exposed.

Found a security issue? Please open a private [security advisory](https://github.com/Linux-Viking/canvas-term/security/advisories/new) rather than a public issue.

## Development

```bash
git clone https://github.com/Linux-Viking/canvas-term.git
cd canvas-term
python3 -m venv .venv
source .venv/bin/activate
pip install --editable ".[dev]"

pytest                 # run the test suite (no network or real keyring needed)
ruff check .           # lint
black . && isort .     # format
```

CI runs linting, tests on Python 3.11–3.14 (plus macOS and Windows), a build and `pipx install` smoke test, and a [gitleaks](https://github.com/gitleaks/gitleaks) secret scan of the full git history.

### Releasing

Releases are published to PyPI by `.github/workflows/publish.yml` using [trusted publishing](https://docs.pypi.org/trusted-publishers/), so no PyPI API token is stored anywhere.

1. Bump `__version__` in `canvas_cli/__init__.py` and merge to `main`.
2. Create a GitHub release with a matching tag: `gh release create v<version> --generate-notes`. The workflow fails if the tag and `__version__` differ.
3. Approve the `pypi` deployment in the Actions tab. The publish job waits for a reviewer.

## Safety First

* **Verify critical submissions**: `canvas-term` verifies submissions automatically, but for high-stakes work (finals, midterms) you should still check the Canvas web UI after uploading.
* **Disclaimer**: This is an independent, personal project and is **not affiliated** with, authorized, or endorsed by Instructure, the Canvas LMS, or any university. Use at your own risk.
* **Academic integrity**: Make sure your use of automation tools complies with your university's acceptable use policy and academic integrity guidelines.

## License

[MIT](LICENSE)
