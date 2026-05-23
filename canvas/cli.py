import click
import html.parser
import os
import mimetypes
import requests
from . import config
from . import api

class MLStripper(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
    def handle_data(self, d):
        self.text.append(d)
    def get_data(self):
        return ''.join(self.text)

def strip_tags(html_content):
    if not html_content:
        return ""
    s = MLStripper()
    s.feed(html_content)
    return s.get_data().strip()

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

class HelpGroup(click.Group):
    def resolve_command(self, ctx, args):
        if args and args[-1] == 'help':
            args[-1] = '--help'
        return super().resolve_command(ctx, args)

@click.group(cls=HelpGroup, context_settings=CONTEXT_SETTINGS)
def cli():
    """A command line interface for Canvas LMS (canvas-cli)."""
    pass

@cli.command(name="config")
@click.option('--token', prompt="Canvas API Token", hide_input=True, help="Your Canvas API Token")
@click.option('--url', prompt="Canvas Domain (e.g., https://canvas.instructure.com)", help="Your Canvas Domain")
def setup_config(token, url):
    """Save your Canvas credentials locally."""
    config.save_config(token, url)
    click.secho("Configuration saved successfully!", fg="green")

@cli.command(name="list")
def list_courses():
    """List all active courses."""
    response = api.make_request('GET', '/api/v1/courses', params={'enrollment_state': 'active', 'per_page': 100})
    courses = [c for c in response.json() if 'name' in c]
    
    click.secho(f"{'ID':<10} | {'Course Name'}", fg="blue", bold=True)
    click.echo("-" * 40)
    for c in courses:
        click.echo(f"{c['id']:<10} | {c['name']}")

# --- Nested Groups for Course -> Module -> List ---

@cli.group(cls=HelpGroup)
@click.argument('course_id')
@click.pass_context
def course(ctx, course_id):
    """Interact with a specific course."""
    ctx.ensure_object(dict)
    ctx.obj['COURSE_ID'] = config.resolve_alias(course_id)

@course.command(name="list")
@click.pass_context
def list_modules(ctx):
    """List modules inside this course."""
    course_id = ctx.obj['COURSE_ID']
    response = api.make_request('GET', f'/api/v1/courses/{course_id}/modules', params={'per_page': 100})
    
    click.secho(f"{'Module ID':<12} | {'Module Name'} (Course: {course_id})", fg="blue", bold=True)
    click.echo("-" * 50)
    for m in response.json():
        click.echo(f"{m['id']:<12} | {m['name']}")

@course.group(cls=HelpGroup)
@click.argument('module_id')
@click.pass_context
def module(ctx, module_id):
    """Interact with a specific module."""
    ctx.obj['MODULE_ID'] = config.resolve_alias(module_id)

@module.command(name="list")
@click.pass_context
def list_assignments(ctx):
    """List items/assignments inside this module."""
    course_id = ctx.obj['COURSE_ID']
    module_id = ctx.obj['MODULE_ID']
    
    response = api.make_request('GET', f'/api/v1/courses/{course_id}/modules/{module_id}/items', params={'per_page': 100})
    
    click.secho(f"{'Item ID':<10} | {'Type':<12} | {'Title'}", fg="blue", bold=True)
    click.echo("-" * 60)
    for item in response.json():
        item_id = item.get('content_id', item['id']) 
        click.echo(f"{item_id:<10} | {item['type']:<12} | {item['title']}")

@module.group(cls=HelpGroup, invoke_without_command=True)
@click.argument('item_id')
@click.pass_context
def item(ctx, item_id):
    """Interact with a specific item."""
    ctx.obj['ITEM_ID'] = config.resolve_alias(item_id)
    if ctx.invoked_subcommand is None:
        ctx.invoke(item_details)

@item.command(name="details")
@click.pass_context
def item_details(ctx):
    """View details for a specific module item."""
    course_id = ctx.obj['COURSE_ID']
    module_id = ctx.obj['MODULE_ID']
    item_id = ctx.obj['ITEM_ID']

    # First, list all items in the module to find the correct item ID 
    # just in case the user passed the content_id (which is what we display in `list`)
    try:
        list_response = api.make_request('GET', f'/api/v1/courses/{course_id}/modules/{module_id}/items', params={'per_page': 100})
        items = list_response.json()
        
        real_item_id = None
        for i in items:
            if str(i['id']) == str(item_id) or str(i.get('content_id')) == str(item_id):
                real_item_id = i['id']
                break
        
        if not real_item_id:
            click.secho(f"API Error: 404 - Could not find an item with ID or Content ID '{item_id}' in module '{module_id}'.", fg="red")
            raise click.Abort()
            
        # Now make the actual request with the guaranteed correct Module Item ID
        response = api.make_request('GET', f'/api/v1/courses/{course_id}/modules/{module_id}/items/{real_item_id}')
        data = response.json()
        
        item_type = data.get('type')
        content_id = data.get('content_id')

        click.secho(f"--- Item Details: {data.get('title', 'Unknown')} ---", fg="blue", bold=True)
        click.echo(f"Type: {item_type}")
        click.echo(f"URL: {data.get('html_url')}")
        
        if item_type == 'Assignment' and content_id:
            # Fetch assignment details
            assign_res = api.make_request('GET', f'/api/v1/courses/{course_id}/assignments/{content_id}')
            assign_data = assign_res.json()
            click.echo("-" * 40)
            click.secho("Description:", bold=True)
            click.echo(strip_tags(assign_data.get('description', 'No description.')))
            click.echo("-" * 40)
            if 'due_at' in assign_data:
                click.echo(f"Due: {assign_data['due_at']}")
            if 'points_possible' in assign_data:
                click.echo(f"Points: {assign_data['points_possible']}")
        elif item_type == 'Page' and 'page_url' in data:
            page_url = data['page_url']
            page_res = api.make_request('GET', f'/api/v1/courses/{course_id}/pages/{page_url}')
            page_data = page_res.json()
            click.echo("-" * 40)
            click.secho("Content:", bold=True)
            click.echo(strip_tags(page_data.get('body', 'No content.')))
            click.echo("-" * 40)
        elif item_type == 'DiscussionTopic' and content_id:
            disc_res = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics/{content_id}')
            disc_data = disc_res.json()
            click.echo("-" * 40)
            click.secho("Prompt:", bold=True)
            click.echo(strip_tags(disc_data.get('message', 'No description.')))
            click.echo("-" * 40)

        if content_id:
            click.echo(f"\nIf you want to submit this item, use Assignment ID: {content_id}")
            click.secho(f"Command: canvas-cli submit <filepath> {course_id} {content_id}", fg="yellow")
            
    except requests.exceptions.RequestException as e:
         click.secho(f"Network Error: {e}", fg="red")
         raise click.Abort()

@cli.command()
@click.argument('filepath', type=click.Path(exists=True))
@click.argument('course_id')
@click.argument('assignment_id')
def submit(filepath, course_id, assignment_id):
    """Submit a file to an assignment (3-step file upload)."""
    # Resolve aliases for display in the confirmation prompt
    resolved_course_id = config.resolve_alias(course_id)
    resolved_assignment_id = config.resolve_alias(assignment_id)
    
    click.secho(f"--- PRE-SUBMISSION CHECK ---", fg="yellow", bold=True)
    click.echo(f"File:       {filepath}")
    click.echo(f"Course:     {course_id} (ID: {resolved_course_id})")
    click.echo(f"Assignment: {assignment_id} (ID: {resolved_assignment_id})")
    
    if not click.confirm("\nAre you sure you want to proceed with this submission?", default=False):
        click.echo("Submission cancelled.")
        return

    # Use resolved IDs for the rest of the function
    course_id = resolved_course_id
    assignment_id = resolved_assignment_id
    
    click.echo(f"\nPreparing to submit '{filepath}' to Course: {course_id}, Assignment: {assignment_id}")
    
    file_size = os.path.getsize(filepath)
    if file_size == 0:
        click.secho(f"Error: The file '{filepath}' is empty (0 bytes). Canvas does not accept empty file submissions.", fg="red")
        return
        
    file_name = os.path.basename(filepath)
    content_type, _ = mimetypes.guess_type(filepath)
    if not content_type:
        content_type = 'application/octet-stream'

    # Step 1: Request Upload URL
    click.echo("Step 1: Requesting upload authorization...")
    upload_req_data = {
        'name': file_name,
        'size': file_size,
        'content_type': content_type,
        'on_duplicate': 'rename'
    }
    
    try:
        response = api.make_request(
            'POST', 
            f'/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self/files',
            data=upload_req_data
        )
    except Exception as e:
        click.secho(f"Failed to request upload URL. Ensure the assignment accepts file uploads.", fg="red")
        return

    upload_data = response.json()
    upload_url = upload_data.get('upload_url')
    upload_params = upload_data.get('upload_params', {})

    if not upload_url:
        click.secho("Error: No upload URL received from Canvas.", fg="red")
        return

    # Step 2: Upload File to AWS S3 (or Canvas storage)
    click.echo("Step 2: Uploading file data...")
    try:
        with open(filepath, 'rb') as f:
            files = {'file': (file_name, f, content_type)}
            # We don't use api.make_request here because this is an external URL and doesn't need our Canvas token
            upload_response = requests.post(upload_url, data=upload_params, files=files)
            if not upload_response.ok:
                click.secho(f"Error during file upload: {upload_response.status_code} - {upload_response.text}", fg="red")
                return
    except Exception as e:
        click.secho(f"Error during file upload network request: {e}", fg="red")
        return

    # Handle redirect (Location header) or JSON response containing file ID
    if upload_response.status_code in (201, 301, 302, 303):
        if 'Location' in upload_response.headers:
            confirm_url = upload_response.headers['Location']
            # Step 2b: Follow the redirect to confirm
            try:
                # Need to use the token for the confirmation redirect if it's back to Canvas
                headers = api.get_headers()
                confirm_response = requests.get(confirm_url, headers=headers)
                confirm_response.raise_for_status()
                file_info = confirm_response.json()
            except Exception as e:
                click.secho(f"Error during upload confirmation redirect: {e}", fg="red")
                return
        else:
            file_info = upload_response.json()
    else:
        try:
            file_info = upload_response.json()
        except:
            click.secho(f"Unexpected response during upload: {upload_response.status_code}", fg="red")
            return

    file_id = file_info.get('id')
    if not file_id:
        click.secho("Error: Could not retrieve uploaded file ID.", fg="red")
        return

    # Step 3: Attach the uploaded file to the assignment submission
    click.echo("Step 3: Attaching file to submission...")
    submission_data = {
        'submission[submission_type]': 'online_upload',
        'submission[file_ids][]': file_id
    }

    try:
        final_response = api.make_request(
            'POST',
            f'/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions',
            data=submission_data
        )
        final_data = final_response.json()
        if final_data.get('workflow_state') in ['submitted', 'graded', 'pending_review']:
             click.secho(f"✅ Successfully submitted '{file_name}'! Submission ID: {final_data.get('id')}", fg="green")
             
             # Post-Submission Verification
             click.echo("🔍 Performing automated verification...")
             verify_res = api.make_request('GET', f'/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self')
             verify_data = verify_res.json()
             
             if verify_data.get('workflow_state') in ['submitted', 'graded', 'pending_review']:
                 click.secho("✅ Verification SUCCESS: Canvas confirms receipt of submission.", fg="green")
                 attachments = verify_data.get('attachments', [])
                 if any(a.get('display_name') == file_name or a.get('filename') == file_name for a in attachments):
                     click.secho(f"✅ Verification SUCCESS: File '{file_name}' is correctly attached.", fg="green")
                 else:
                     click.secho(f"⚠️ Verification WARNING: File name '{file_name}' not found in attachments list. Please check manually.", fg="yellow")
             else:
                 click.secho(f"🚨 Verification FAILURE: Canvas reports state as '{verify_data.get('workflow_state')}'.", fg="red")
        else:
             click.secho(f"⚠️ Submission accepted, but status is '{final_data.get('workflow_state')}'. Please verify on Canvas.", fg="yellow")
    except Exception as e:
        click.secho(f"Error finalizing submission: {e}", fg="red")

@cli.group(cls=HelpGroup)
def alias():
    """Manage Canvas ID aliases."""
    pass

@alias.command(name="set")
@click.argument('name')
@click.argument('target_id')
def set_alias(name, target_id):
    """Map a memorable name to a Canvas ID."""
    config.set_alias(name, target_id)
    click.secho(f"Alias '{name}' -> '{target_id}' saved.", fg="green")

@cli.command(name="todo")
def todo():
    """List upcoming assignments."""
    response = api.make_request('GET', '/api/v1/users/self/todo')
    todos = response.json()
    
    click.secho(f"{'Due Date':<20} | {'Course':<15} | {'Assignment'}", fg="blue", bold=True)
    click.echo("-" * 70)
    for t in todos:
        due = t.get('ignore', t.get('ignore_item', {}).get('due_at', 'No Date'))
        # Usually todo items have a different structure, let's pull typical fields
        if 'assignment' in t:
            due = t['assignment'].get('due_at', 'No Date')
            course_id = t.get('course_id', 'Unknown')
            title = t['assignment'].get('name', 'Unknown')
        else:
             # fallback for other types
            due = "Unknown"
            course_id = "Unknown"
            title = t.get('ignore', 'Unknown item')
            
        click.echo(f"{str(due)[:20]:<20} | {str(course_id):<15} | {title}")

@cli.command(name="grades")
def grades():
    """Display current grades for active courses."""
    response = api.make_request('GET', '/api/v1/courses', params={'enrollment_state': 'active', 'include[]': 'total_scores'})
    courses = [c for c in response.json() if 'name' in c]

    click.secho(f"{'Course Name':<35} | {'Grade':<5} | {'Score'}", fg="blue", bold=True)
    click.echo("-" * 55)
    for c in courses:
        enrollments = c.get('enrollments', [])
        grade = "N/A"
        score = "N/A"
        if enrollments:
            e = enrollments[0]
            grade = e.get('computed_current_grade', 'N/A')
            score = e.get('computed_current_score', 'N/A')
            if grade is None: grade = "N/A"
            if score is None: score = "N/A"
        click.echo(f"{c['name'][:35]:<35} | {str(grade):<5} | {str(score)}")

@cli.group(cls=HelpGroup)
def inbox():
    """Manage Canvas messages."""
    pass

@inbox.command(name="list")
def list_inbox():
    """List unread Canvas messages."""
    response = api.make_request('GET', '/api/v1/conversations', params={'workflow_state': 'unread'})
    msgs = response.json()
    
    click.secho(f"{'ID':<10} | {'Subject':<30} | {'Last Message'}", fg="blue", bold=True)
    click.echo("-" * 65)
    for m in msgs:
        subject = m.get('subject', 'No Subject')
        last_msg = m.get('last_message', '')
        click.echo(f"{m['id']:<10} | {subject[:30]:<30} | {last_msg[:20]}...")

@course.group(name="discuss", cls=HelpGroup)
@click.pass_context
def discuss(ctx):
    """Manage discussion boards."""
    pass

@discuss.command(name="list")
@click.pass_context
def list_discussions(ctx):
    """List discussion topics for the course."""
    course_id = ctx.obj['COURSE_ID']
    response = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics', params={'per_page': 100})
    topics = response.json()

    if not topics:
        click.secho("No discussion topics found.", fg="yellow")
        return

    click.secho(f"{'Topic ID':<12} | {'Title'}", fg="blue", bold=True)
    click.echo("-" * 50)
    for t in topics:
        click.echo(f"{t['id']:<12} | {t.get('title', 'No Title')}")

@discuss.command(name="view")
@click.argument('topic_id')
@click.option('--entry-id', help="The ID of a specific student's reply to view threaded responses.")
@click.pass_context
def view_discussion(ctx, topic_id, entry_id):
    """View the prompt and replies for a discussion topic."""
    course_id = ctx.obj['COURSE_ID']
    topic_id = config.resolve_alias(topic_id)
    
    try:
        if entry_id:
            # Get the specific entry and its replies
            entries_res = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries/{entry_id}/replies', params={'per_page': 50})
            entries = entries_res.json()
            
            if not entries:
                click.secho("\nNo threaded replies yet for this entry.", fg="yellow")
                return
                
            click.secho(f"\n--- {len(entries)} Threaded Replies to Entry {entry_id} ---", fg="cyan", bold=True)
            for entry in entries:
                author = entry.get('user_name', 'Unknown Student')
                date = entry.get('created_at', '')[:10]
                reply_id = entry.get('id')
                click.secho(f"\n>> {author} ({date}) [Reply ID: {reply_id}]:", fg="green")
                click.echo(strip_tags(entry.get('message', '')))
            return

        # Get the main topic prompt
        topic_res = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}')
        topic_data = topic_res.json()
        
        click.secho(f"\n=== {topic_data.get('title', 'Discussion Topic')} ===", fg="blue", bold=True)
        click.secho(f"Author: {topic_data.get('user_name', 'Teacher')} | Posted: {topic_data.get('posted_at', 'Unknown')}")
        click.echo("-" * 60)
        click.echo(strip_tags(topic_data.get('message', 'No description.')))
        click.echo("=" * 60)
        
        # Get the replies
        entries_res = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries', params={'per_page': 50})
        entries = entries_res.json()
        
        if not entries:
            click.secho("\nNo replies yet.", fg="yellow")
            return
            
        click.secho(f"\n--- {len(entries)} Replies ---", fg="cyan", bold=True)
        for entry in entries:
            author = entry.get('user_name', 'Unknown Student')
            date = entry.get('created_at', '')[:10]
            entry_id = entry.get('id')
            
            # Check if there are any threaded replies to this entry
            has_replies = " (Has threaded replies)" if entry.get('has_more_replies') or entry.get('recent_replies') else ""
            
            click.secho(f"\n> {author} ({date}) [Entry ID: {entry_id}]{has_replies}:", fg="green")
            click.echo(strip_tags(entry.get('message', '')))
            
    except Exception as e:
        click.secho(f"Error fetching discussion: {e}", fg="red")

@discuss.command(name="reply")
@click.argument('topic_id')
@click.argument('message', required=False)
@click.option('--file', type=click.Path(exists=True), help="Path to a plain text file (.txt, .md) containing your reply. Newlines are automatically preserved.")
@click.option('--entry-id', help="The ID of a specific student's reply to thread your response under.")
@click.pass_context
def reply_discussion(ctx, topic_id, message, file, entry_id):
    """Post a reply to a discussion topic or a specific entry."""
    if not message and not file:
        click.secho("Error: You must provide either a MESSAGE argument or use the --file option.", fg="red")
        return
        
    if file:
        with open(file, 'r', encoding='utf-8') as f:
            raw_content = f.read()
    else:
        raw_content = message

    course_id = ctx.obj['COURSE_ID']
    topic_id = config.resolve_alias(topic_id)
    
    if entry_id:
        click.echo(f"Posting threaded reply to Entry {entry_id} in topic {topic_id}...")
        endpoint = f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries/{entry_id}/replies'
    else:
        click.echo(f"Posting top-level reply to topic {topic_id}...")
        endpoint = f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries'
    
    # Canvas expects HTML. Convert literal newlines or escaped '\n' to <br> tags.
    formatted_message = raw_content.replace('\\n', '<br>').replace('\n', '<br>')
    
    payload = {
        'message': formatted_message
    }
    
    try:
        response = api.make_request(
            'POST', 
            endpoint,
            data=payload
        )
        data = response.json()
        click.secho(f"✅ Reply posted successfully! New Entry ID: {data.get('id')}", fg="green")
    except Exception as e:
        click.secho(f"Error posting reply: {e}", fg="red")

@course.group(name="files", cls=HelpGroup)
@click.pass_context
def files(ctx):
    """Manage course files."""
    pass

@files.command(name="download")
@click.pass_context
def download_files(ctx):
    """Bulk download all files for the course."""
    course_id = ctx.obj['COURSE_ID']
    response = api.make_request('GET', f'/api/v1/courses/{course_id}/files', params={'per_page': 100})
    files_data = response.json()

    if not files_data:
        click.secho("No files found or you don't have access.", fg="yellow")
        return

    download_dir = f"./course_{course_id}_files"
    os.makedirs(download_dir, exist_ok=True)
    click.secho(f"Downloading files to {download_dir}/...", fg="blue")

    for f in files_data:
        url = f.get('url')
        name = f.get('display_name')
        if not url or not name:
            continue
        
        filepath = os.path.join(download_dir, name)
        click.echo(f"Downloading: {name}")
        
        try:
            # Files download url typically requires auth but the returned URL from API often has a verification token
            # We'll pass the headers just in case
            headers = api.get_headers()
            r = requests.get(url, headers=headers)
            r.raise_for_status()
            with open(filepath, 'wb') as out_f:
                out_f.write(r.content)
        except Exception as e:
             click.secho(f"Failed to download {name}: {e}", fg="red")

    click.secho("Done!", fg="green")

@cli.command(name="help")
@click.argument('commands', nargs=-1)
@click.pass_context
def help_cmd(ctx, commands):
    """Show help for a specific command."""
    if not commands:
        click.echo(ctx.parent.get_help())
        return

    # Traverse the command tree
    cmd = cli
    for cmd_name in commands:
        if isinstance(cmd, click.Group):
            cmd = cmd.get_command(ctx, cmd_name)
        else:
            cmd = None
            
        if cmd is None:
            click.secho(f"No such command: {' '.join(commands)}", fg="red")
            return

    # Create a new context for the target command to generate the correct help output
    info_name = " ".join(commands)
    cmd_ctx = click.Context(cmd, info_name=info_name, parent=ctx.parent)
    click.echo(cmd.get_help(cmd_ctx))

if __name__ == '__main__':
    cli()
