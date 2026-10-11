import html.parser
import mimetypes
import os
import re
import sys

import click

from . import __version__, api, config
from .errors import AuthError, CanvasCliError, CanvasError

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])
SUBMITTED_STATES = ("submitted", "graded", "pending_review")


class HelpGroup(click.Group):
    def resolve_command(self, ctx, args):
        if args and args[-1] == "help":
            args[-1] = "--help"
        return super().resolve_command(ctx, args)


@click.group(cls=HelpGroup, context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, "-V", "--version")
def cli():
    """A command line interface for Canvas LMS (canvas-term)."""
    api.reset_client()


@cli.command(name="config")
@click.option("--url", help="Your Canvas domain, e.g. https://school.instructure.com")
@click.option(
    "--token-stdin",
    is_flag=True,
    help="Read the API token from standard input instead of prompting (for scripts).",
)
def setup_config(url, token_stdin):
    """Save your Canvas URL and API token.

    The token is stored in your OS keyring, never in the config file. It is
    not accepted as a command-line argument so it can't leak into shell
    history or process listings.
    """
    if url is None:
        try:
            current = config.get_url()
        except CanvasCliError:
            current = config.DEFAULT_URL
        url = click.prompt("Canvas Domain (e.g., https://canvas.instructure.com)", default=current)
    saved_url = config.save_url(url)

    if token_stdin:
        token = sys.stdin.readline().strip()
    else:
        token = click.prompt("Canvas API Token", hide_input=True).strip()
    if not token:
        raise click.UsageError("The API token cannot be empty.")

    warning = config.keyring_warning()
    if warning:
        click.secho(f"Warning: {warning}", fg="yellow", err=True)
    config.set_token(token)
    click.secho(f"Configuration saved for {saved_url}.", fg="green")

    click.echo("Verifying token...")
    try:
        me = api.CanvasClient(base_url=saved_url, token=token).get_json("/api/v1/users/self")
        click.secho(f"Logged in as {me.get('name', 'unknown user')}.", fg="green")
    except CanvasError as e:
        click.secho(f"Warning: token saved, but verification failed: {e.message}", fg="yellow")


@cli.command(name="list")
def list_courses():
    """List all active courses."""
    courses = api.get_client().get_all("/api/v1/courses", params={"enrollment_state": "active"})
    courses = [c for c in courses if "name" in c]

    click.secho(f"{'ID':<10} | {'Course Name'}", fg="blue", bold=True)
    click.echo("-" * 40)
    for c in courses:
        click.echo(f"{c['id']:<10} | {c['name']}")


# --- Nested Groups for Course -> Module -> List ---


@cli.group(cls=HelpGroup)
@click.argument("course_id")
@click.pass_context
def course(ctx, course_id):
    """Interact with a specific course."""
    ctx.ensure_object(dict)
    ctx.obj["COURSE_ID"] = config.resolve_alias(course_id)


@course.command(name="list")
@click.pass_context
def list_modules(ctx):
    """List modules inside this course."""
    course_id = ctx.obj["COURSE_ID"]
    modules = api.get_client().get_all(f"/api/v1/courses/{course_id}/modules")

    click.secho(f"{'Module ID':<12} | {'Module Name'} (Course: {course_id})", fg="blue", bold=True)
    click.echo("-" * 50)
    for m in modules:
        click.echo(f"{m['id']:<12} | {m['name']}")


@course.group(cls=HelpGroup)
@click.argument("module_id")
@click.pass_context
def module(ctx, module_id):
    """Interact with a specific module."""
    ctx.obj["MODULE_ID"] = config.resolve_alias(module_id)


@module.command(name="list")
@click.pass_context
def list_assignments(ctx):
    """List items/assignments inside this module."""
    course_id = ctx.obj["COURSE_ID"]
    module_id = ctx.obj["MODULE_ID"]
    items = api.get_client().get_all(f"/api/v1/courses/{course_id}/modules/{module_id}/items")

    click.secho(f"{'Item ID':<10} | {'Type':<12} | {'Title'}", fg="blue", bold=True)
    click.echo("-" * 60)
    for item in items:
        item_id = item.get("content_id", item["id"])
        click.echo(f"{item_id:<10} | {item['type']:<12} | {item['title']}")


@module.group(cls=HelpGroup)
@click.argument("item_id")
@click.pass_context
def item(ctx, item_id):
    """Interact with a specific item."""
    ctx.obj["ITEM_ID"] = config.resolve_alias(item_id)


@item.command(name="details")
@click.pass_context
def item_details(ctx):
    """View details for a specific module item."""
    course_id = ctx.obj["COURSE_ID"]
    module_id = ctx.obj["MODULE_ID"]
    item_id = ctx.obj["ITEM_ID"]
    client = api.get_client()

    # `module list` displays content_id, so accept either that or the module item ID.
    items = client.get_all(f"/api/v1/courses/{course_id}/modules/{module_id}/items")
    real_item_id = next(
        (i["id"] for i in items if item_id in (str(i["id"]), str(i.get("content_id")))),
        None,
    )
    if not real_item_id:
        raise CanvasError(
            f"Could not find an item with ID or Content ID '{item_id}' in module '{module_id}'."
        )

    data = client.get_json(f"/api/v1/courses/{course_id}/modules/{module_id}/items/{real_item_id}")

    click.secho(f"--- Item Details: {data.get('title', 'Unknown')} ---", fg="blue", bold=True)
    click.echo(f"Type: {data.get('type')}")
    click.echo(f"URL: {data.get('html_url')}")

    if "content_id" in data:
        click.echo(f"\nIf you want to submit this item, use Assignment ID: {data['content_id']}")
        click.secho(
            f"Command: canvas-term submit <filepath> {course_id} {data['content_id']}", fg="yellow"
        )

        if data.get("type") == "Assignment":
            try:
                assignment = client.get_json(
                    f"/api/v1/courses/{course_id}/assignments/{data['content_id']}"
                )
            except AuthError:
                raise
            except CanvasError as e:
                click.secho(
                    f"\nWarning: Could not fetch assignment details: {e.message}", fg="yellow"
                )
                return

            text = strip_tags(assignment.get("description"))
            if text:
                text = re.sub(r"\n\s*\n", "\n\n", text)
                click.secho("\n--- Assignment Description ---", fg="cyan", bold=True)
                click.echo(text)


@cli.command()
@click.argument("filepath", type=click.Path(exists=True, dir_okay=False))
@click.argument("course_id")
@click.argument("assignment_id")
def submit(filepath, course_id, assignment_id):
    """Submit a file to an assignment (3-step file upload)."""
    # Resolve aliases for display in the confirmation prompt
    resolved_course_id = config.resolve_alias(course_id)
    resolved_assignment_id = config.resolve_alias(assignment_id)

    click.secho("--- PRE-SUBMISSION CHECK ---", fg="yellow", bold=True)
    click.echo(f"File:       {filepath}")
    click.echo(f"Course:     {course_id} (ID: {resolved_course_id})")
    click.echo(f"Assignment: {assignment_id} (ID: {resolved_assignment_id})")

    if not click.confirm("\nAre you sure you want to proceed with this submission?", default=False):
        click.echo("Submission cancelled.")
        return

    # Use resolved IDs for the rest of the function
    course_id = resolved_course_id
    assignment_id = resolved_assignment_id
    client = api.get_client()

    click.echo(
        f"\nPreparing to submit '{filepath}' to Course: {course_id}, Assignment: {assignment_id}"
    )

    file_size = os.path.getsize(filepath)
    if file_size == 0:
        raise click.ClickException(
            f"The file '{filepath}' is empty (0 bytes). Canvas does not accept empty file submissions."
        )

    file_name = os.path.basename(filepath)
    content_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"

    # Step 1: Request Upload URL
    click.echo("Step 1: Requesting upload authorization...")
    try:
        response = client.request(
            "POST",
            f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self/files",
            data={
                "name": file_name,
                "size": file_size,
                "content_type": content_type,
                "on_duplicate": "rename",
            },
        )
    except AuthError:
        raise
    except CanvasError as e:
        raise CanvasError(
            f"{e.message}\nFailed to request upload URL. Ensure the assignment accepts file uploads."
        ) from e

    upload_data = api.parse_json(response)
    upload_url = upload_data.get("upload_url")
    if not upload_url:
        raise CanvasError("No upload URL received from Canvas.")

    # Step 2: Upload file data. The upload URL is usually external storage, so
    # the client only attaches the token if it happens to be the Canvas host.
    # Redirects are handled manually: Canvas requires an authenticated GET to confirm.
    click.echo("Step 2: Uploading file data...")
    with open(filepath, "rb") as f:
        upload_response = client.request(
            "POST",
            upload_url,
            data=upload_data.get("upload_params", {}),
            files={"file": (file_name, f, content_type)},
            allow_redirects=False,
        )

    if upload_response.is_redirect and "Location" in upload_response.headers:
        confirm_url = upload_response.headers["Location"]
        file_info = client.get_json(confirm_url)
    else:
        file_info = api.parse_json(upload_response)

    file_id = file_info.get("id")
    if not file_id:
        raise CanvasError("Could not retrieve uploaded file ID.")

    # Step 3: Attach the uploaded file to the assignment submission
    click.echo("Step 3: Attaching file to submission...")
    final_data = api.parse_json(
        client.request(
            "POST",
            f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions",
            data={
                "submission[submission_type]": "online_upload",
                "submission[file_ids][]": file_id,
            },
        )
    )

    if final_data.get("workflow_state") not in SUBMITTED_STATES:
        click.secho(
            f"⚠️ Submission accepted, but status is '{final_data.get('workflow_state')}'. "
            "Please verify on Canvas.",
            fg="yellow",
        )
        return

    click.secho(
        f"✅ Successfully submitted '{file_name}'! Submission ID: {final_data.get('id')}",
        fg="green",
    )

    # Post-Submission Verification
    click.echo("🔍 Performing automated verification...")
    verify_data = client.get_json(
        f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self"
    )
    if verify_data.get("workflow_state") not in SUBMITTED_STATES:
        raise CanvasError(
            f"🚨 Verification FAILURE: Canvas reports state as '{verify_data.get('workflow_state')}'."
        )

    click.secho("✅ Verification SUCCESS: Canvas confirms receipt of submission.", fg="green")
    attachments = verify_data.get("attachments", [])
    if any(file_name in (a.get("display_name"), a.get("filename")) for a in attachments):
        click.secho(
            f"✅ Verification SUCCESS: File '{file_name}' is correctly attached.", fg="green"
        )
    else:
        click.secho(
            f"⚠️ Verification WARNING: File name '{file_name}' not found in attachments list. "
            "Please check manually.",
            fg="yellow",
        )


@cli.group(cls=HelpGroup)
def alias():
    """Manage Canvas ID aliases."""


@alias.command(name="set")
@click.argument("name")
@click.argument("target_id")
def set_alias(name, target_id):
    """Map a memorable name to a Canvas ID."""
    config.set_alias(name, target_id)
    click.secho(f"Alias '{name}' -> '{target_id}' saved.", fg="green")


@cli.command(name="todo")
def todo():
    """List upcoming assignments."""
    todos = api.get_client().get_all("/api/v1/users/self/todo")

    click.secho(f"{'Due Date':<20} | {'Course':<15} | {'Assignment'}", fg="blue", bold=True)
    click.echo("-" * 70)
    for t in todos:
        if "assignment" in t:
            due = t["assignment"].get("due_at") or "No Date"
            course_id = t.get("course_id", "Unknown")
            title = t["assignment"].get("name", "Unknown")
        else:
            # Quizzes and other to-do types have a different structure
            due = "Unknown"
            course_id = t.get("course_id", "Unknown")
            title = (t.get("quiz") or {}).get("title") or t.get("type", "Unknown item")

        click.echo(f"{str(due)[:20]:<20} | {str(course_id):<15} | {title}")


@cli.command(name="grades")
def grades():
    """Display current grades for active courses."""
    courses = api.get_client().get_all(
        "/api/v1/courses", params={"enrollment_state": "active", "include[]": "total_scores"}
    )
    courses = [c for c in courses if "name" in c]

    click.secho(f"{'Course Name':<35} | {'Grade':<5} | {'Score'}", fg="blue", bold=True)
    click.echo("-" * 55)
    for c in courses:
        grade = score = "N/A"
        enrollments = c.get("enrollments", [])
        if enrollments:
            e = enrollments[0]
            if e.get("computed_current_grade") is not None:
                grade = e["computed_current_grade"]
            if e.get("computed_current_score") is not None:
                score = e["computed_current_score"]
        click.echo(f"{c['name'][:35]:<35} | {str(grade):<5} | {str(score)}")


@cli.group(cls=HelpGroup)
def inbox():
    """Manage Canvas messages."""


@inbox.command(name="list")
def list_inbox():
    """List unread Canvas messages."""
    msgs = api.get_client().get_all("/api/v1/conversations", params={"workflow_state": "unread"})

    click.secho(f"{'ID':<10} | {'Subject':<30} | {'Last Message'}", fg="blue", bold=True)
    click.echo("-" * 65)
    for m in msgs:
        subject = m.get("subject") or "No Subject"
        last_msg = m.get("last_message") or ""
        click.echo(f"{m['id']:<10} | {subject[:30]:<30} | {last_msg[:20]}...")


@course.group(name="discuss", cls=HelpGroup)
def discuss():
    """Manage discussion boards."""


@discuss.command(name="list")
@click.pass_context
def list_discussions(ctx):
    """List discussion topics for the course."""
    course_id = ctx.obj["COURSE_ID"]
    topics = api.get_client().get_all(f"/api/v1/courses/{course_id}/discussion_topics")

    if not topics:
        click.secho("No discussion topics found.", fg="yellow")
        return

    click.secho(f"{'Topic ID':<12} | {'Title'}", fg="blue", bold=True)
    click.echo("-" * 50)
    for t in topics:
        click.echo(f"{t['id']:<12} | {t.get('title', 'No Title')}")


class MLStripper(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.text.append("\n")

    def handle_data(self, d):
        self.text.append(d)

    def get_data(self):
        return "".join(self.text)


def strip_tags(html_content):
    if not html_content:
        return ""
    s = MLStripper()
    s.feed(html_content)
    s.close()
    return s.get_data().strip()


@discuss.command(name="view")
@click.argument("topic_id")
@click.option("--entry-id", help="The ID of a specific student's reply to view threaded responses.")
@click.pass_context
def view_discussion(ctx, topic_id, entry_id):
    """View the prompt and replies for a discussion topic."""
    course_id = ctx.obj["COURSE_ID"]
    topic_id = config.resolve_alias(topic_id)
    client = api.get_client()
    topic_path = f"/api/v1/courses/{course_id}/discussion_topics/{topic_id}"

    if entry_id:
        # Get the specific entry and its replies
        entries = client.get_all(f"{topic_path}/entries/{entry_id}/replies")
        if not entries:
            click.secho("\nNo threaded replies yet for this entry.", fg="yellow")
            return

        click.secho(
            f"\n--- {len(entries)} Threaded Replies to Entry {entry_id} ---", fg="cyan", bold=True
        )
        for entry in entries:
            author = entry.get("user_name", "Unknown Student")
            date = (entry.get("created_at") or "")[:10]
            click.secho(f"\n>> {author} ({date}) [Reply ID: {entry.get('id')}]:", fg="green")
            click.echo(strip_tags(entry.get("message", "")))
        return

    # Get the main topic prompt
    topic_data = client.get_json(topic_path)
    click.secho(f"\n=== {topic_data.get('title', 'Discussion Topic')} ===", fg="blue", bold=True)
    click.secho(
        f"Author: {topic_data.get('user_name', 'Teacher')} | Posted: {topic_data.get('posted_at', 'Unknown')}"
    )
    click.echo("-" * 60)
    click.echo(strip_tags(topic_data.get("message") or "No description."))
    click.echo("=" * 60)

    # Get the replies
    entries = client.get_all(f"{topic_path}/entries")
    if not entries:
        click.secho("\nNo replies yet.", fg="yellow")
        return

    click.secho(f"\n--- {len(entries)} Replies ---", fg="cyan", bold=True)
    for entry in entries:
        author = entry.get("user_name", "Unknown Student")
        date = (entry.get("created_at") or "")[:10]
        has_replies = (
            " (Has threaded replies)"
            if entry.get("has_more_replies") or entry.get("recent_replies")
            else ""
        )
        click.secho(
            f"\n> {author} ({date}) [Entry ID: {entry.get('id')}]{has_replies}:", fg="green"
        )
        click.echo(strip_tags(entry.get("message", "")))


@discuss.command(name="reply")
@click.argument("topic_id")
@click.argument("message", required=False)
@click.option(
    "--file",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a plain text file (.txt, .md) containing your reply. Newlines are automatically preserved.",
)
@click.option(
    "--entry-id", help="The ID of a specific student's reply to thread your response under."
)
@click.pass_context
def reply_discussion(ctx, topic_id, message, file, entry_id):
    """Post a reply to a discussion topic or a specific entry."""
    if not message and not file:
        raise click.UsageError(
            "You must provide either a MESSAGE argument or use the --file option."
        )

    if file:
        with open(file, encoding="utf-8") as f:
            raw_content = f.read()
    else:
        raw_content = message

    course_id = ctx.obj["COURSE_ID"]
    topic_id = config.resolve_alias(topic_id)

    if entry_id:
        click.echo(f"Posting threaded reply to Entry {entry_id} in topic {topic_id}...")
        endpoint = (
            f"/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries/{entry_id}/replies"
        )
    else:
        click.echo(f"Posting top-level reply to topic {topic_id}...")
        endpoint = f"/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries"

    # Canvas expects HTML. Convert literal newlines or escaped '\n' to <br> tags.
    formatted_message = raw_content.replace("\\n", "<br>").replace("\n", "<br>")

    response = api.get_client().request("POST", endpoint, data={"message": formatted_message})
    click.secho(
        f"✅ Reply posted successfully! New Entry ID: {api.parse_json(response).get('id')}",
        fg="green",
    )


@course.group(name="files", cls=HelpGroup)
def files():
    """Manage course files."""


def safe_filename(name):
    """Reduce a server-supplied file name to a safe, single path component."""
    name = name.replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[\x00-\x1f]", "", name)
    if name in ("", ".", ".."):
        return None
    return name


@files.command(name="download")
@click.pass_context
def download_files(ctx):
    """Bulk download all files for the course."""
    course_id = ctx.obj["COURSE_ID"]
    client = api.get_client()
    files_data = client.get_all(f"/api/v1/courses/{course_id}/files")

    if not files_data:
        click.secho("No files found or you don't have access.", fg="yellow")
        return

    download_dir = f"./course_{course_id}_files"
    os.makedirs(download_dir, exist_ok=True)
    click.secho(f"Downloading files to {download_dir}/...", fg="blue")

    failures = 0
    for f in files_data:
        url = f.get("url")
        name = safe_filename(f.get("display_name") or "")
        if not url or not name:
            continue

        click.echo(f"Downloading: {name}")
        try:
            client.download(url, os.path.join(download_dir, name))
        except AuthError:
            raise
        except (CanvasError, OSError) as e:
            failures += 1
            message = e.message if isinstance(e, CanvasError) else str(e)
            click.secho(f"Failed to download {name}: {message}", fg="red")

    if failures:
        raise click.ClickException(f"{failures} file(s) failed to download.")
    click.secho("Done!", fg="green")


@cli.command(name="help")
@click.argument("commands", nargs=-1)
@click.pass_context
def help_cmd(ctx, commands):
    """Show help for a specific command."""
    if not commands:
        click.echo(ctx.parent.get_help())
        return

    # Traverse the command tree
    cmd = cli
    for cmd_name in commands:
        cmd = cmd.get_command(ctx, cmd_name) if isinstance(cmd, click.Group) else None
        if cmd is None:
            raise click.UsageError(f"No such command: {' '.join(commands)}")

    # Create a new context for the target command to generate the correct help output
    info_name = " ".join(commands)
    cmd_ctx = click.Context(cmd, info_name=info_name, parent=ctx.parent)
    click.echo(cmd.get_help(cmd_ctx))


if __name__ == "__main__":
    cli()
