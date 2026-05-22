# canvas-cli

A lightning-fast, terminal-based operating system for your degree. 

`canvas-cli` is a command-line interface for the Canvas Learning Management System (LMS). It allows students to check grades, view upcoming assignments, participate in discussion boards, bulk-download course files, and submit assignments (including PDFs and documents) directly from the terminal without ever opening a web browser.

## Features

* **Submissions**: Upload local files (PDFs, scripts, docs) directly to assignments using the native 3-step Canvas upload protocol.
* **To-Do List**: View all upcoming assignments and due dates across all active courses.
* **Grades**: Check your current computed score and letter grade for all courses instantly.
* **Discussion Boards**: Read discussion prompts, view classmate replies, and post your own threaded replies.
* **Bulk File Downloader**: Download all slides, syllabi, and readings from a course into a local folder with one command.
* **Inbox**: Read your unread Canvas messages.
* **Alias System**: Map complex Canvas IDs (like `123456`) to memorable names (like `cs101`) for rapid navigation.

## Installation

Ensure you have Python 3 installed. You can install the CLI directly from source:

```bash
git clone https://github.com/Linux-Viking/canvas-cli.git
cd canvas-cli
pip install -e .
```

This will make the `canvas-cli` command available globally in your terminal.

## Setup & Authentication

Before using the CLI, you must provide it with your Canvas domain and an API Access Token. 

### 1. Generate an API Token
1. Log into your university's Canvas website.
2. Click **Account** (your profile picture) -> **Settings**.
3. Scroll down to **Approved Integrations** and click the **+ New Access Token** button.
4. Give it a purpose (e.g., "canvas-cli") and click **Generate Token**.
5. Copy the token string immediately (you won't be able to see it again).

### 2. Configure the CLI
Run the configuration command:
```bash
canvas-cli config
```
* **Canvas API Token**: Paste the token you just generated. (Your OS will securely store this in your native keychain/credential manager, not in plain text).
* **Canvas Domain**: Enter your school's Canvas URL (e.g., `https://canvas.instructure.com` or `https://stanford.instructure.com`).

## Quick Start Guide

**1. Find your courses**
```bash
canvas-cli list
```

**2. Setup an alias (Optional)**
```bash
canvas-cli alias set cs101 123456
```

**3. Check your grades and to-do list**
```bash
canvas-cli grades
canvas-cli todo
```

**4. Submit an assignment**
```bash
canvas-cli submit ./my_essay.pdf cs101 987654
```

**5. Participate in a discussion**
```bash
# Read the discussion and replies
canvas-cli course cs101 discuss view 555123

# Reply to the main prompt
canvas-cli course cs101 discuss reply 555123 "Here is my response..."

# Reply to a specific student (threaded)
canvas-cli course cs101 discuss reply 555123 "I agree!" --entry-id 999888
```

## Getting Help

The CLI is fully documented. You can append `help`, `-h`, or `--help` to any command or group to see what it does and what arguments it expects.

```bash
canvas-cli help
canvas-cli course help
canvas-cli submit -h
```

## Security

* Your API token is handled via the `keyring` Python library, meaning it is encrypted and stored safely by your operating system's native secret manager (e.g., macOS Keychain, Windows Credential Locker, Linux Secret Service). It is never written to a plain text file.
* Aliases and your Canvas URL are stored in `~/.canvas_cli.json`.

## Safety First

*   **Verify Critical Submissions**: While `canvas-cli` is designed for reliability, it is **highly recommended** that you manually verify high-stakes submissions (like finals or midterms) in the Canvas web UI after uploading.
*   **Disclaimer**: This is an independent, personal project and is **not affiliated**, associated, authorized, endorsed by, or in any way officially connected with Instructure, the Canvas LMS, or any specific university. Use of this tool is at your own risk.
*   **Academic Integrity**: Always ensure your use of automation tools complies with your university's Acceptable Use Policy and Academic Integrity guidelines.