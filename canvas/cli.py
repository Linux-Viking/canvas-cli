import click
import html.parser
import os
import mimetypes
import requests
from . import config
from . import api
from .utils import echo, secho, style, get_color_setting

class AnsiHtmlRenderer(html.parser.HTMLParser):
    def __init__(self, color=None):
        super().__init__()
        self.reset()
        self.convert_charrefs = True
        self.result = []
        self.tags_stack = []
        self.link_url = None
        self.color = color if color is not None else get_color_setting()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self.tags_stack.append(tag)
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self.result.append('\n\n')
        elif tag == 'p':
            self.result.append('\n\n')
        elif tag == 'br':
            self.result.append('\n')
        elif tag == 'li':
            self.result.append('\n  • ')
        elif tag == 'a':
            for attr, value in attrs:
                if attr == 'href':
                    self.link_url = value
                    break

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.tags_stack:
            # Pop up to and including the tag to handle unclosed tags
            while self.tags_stack:
                popped = self.tags_stack.pop()
                if popped == tag:
                    break
        
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self.result.append('\n')
        elif tag == 'a' and self.link_url:
            self.result.append(f" ({self.link_url})")
            self.link_url = None

    def handle_data(self, data):
        if not data:
            return

        styled_data = data
        if self.color and self.tags_stack:
            if any(h in self.tags_stack for h in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                styled_data = style(data, fg='blue', bold=True)
            elif 'strong' in self.tags_stack or 'b' in self.tags_stack:
                styled_data = style(data, bold=True)
            elif 'em' in self.tags_stack or 'i' in self.tags_stack:
                styled_data = style(data, underline=True)
        
        self.result.append(styled_data)

    def get_data(self):
        return ''.join(self.result).strip()

def strip_tags(html_content, color=None):
    if not html_content:
        return ""
    
    renderer = AnsiHtmlRenderer(color=color)
    renderer.feed(html_content)
    return renderer.get_data()

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

class HelpGroup(click.Group):
    def resolve_command(self, ctx, args):
        if args and args[-1] == 'help':
            args[-1] = '--help'
        return super().resolve_command(ctx, args)

@click.group(cls=HelpGroup, context_settings=CONTEXT_SETTINGS)
@click.option('--no-color', is_flag=True, help="Disable ANSI color output.")
@click.pass_context
def cli(ctx, no_color):
    """
    A command line interface for Canvas LMS (canvas-cli).
    
    Quick Example:
    
    1. List courses:  canvas list
    
    2. List modules:  canvas course <course_id> list
    
    3. View item:    canvas course <course_id> module <module_id> item <item_id> details
    
    4. Discussions:  canvas course <course_id> discuss list
    
    5. View Thread:   canvas course <course_id> discuss view <topic_id>
    """
    ctx.ensure_object(dict)
    ctx.obj['NO_COLOR'] = no_color

@cli.command(name="config")
@click.option('--token', prompt="Canvas API Token", hide_input=True, help="Your Canvas API Token")
@click.option('--url', prompt="Canvas Domain (e.g., https://canvas.instructure.com)", help="Your Canvas Domain")
def setup_config(token, url):
    """Save your Canvas credentials locally."""
    config.save_config(token, url)
    secho("Configuration saved successfully!", fg="green")

@cli.command(name="list")
def list_courses():
    """List all active courses."""
    response = api.make_request('GET', '/api/v1/courses', params={'enrollment_state': 'active', 'per_page': 100})
    courses = [c for c in response.json() if 'name' in c]
    
    secho(f"{'ID':<10} | {'Course Name'}", fg="blue", bold=True)
    echo("-" * 40)
    for c in courses:
        echo(f"{c['id']:<10} | {c['name']}")

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
    
    secho(f"{'Module ID':<12} | {'Module Name'} (Course: {course_id})", fg="blue", bold=True)
    echo("-" * 50)
    for m in response.json():
        echo(f"{m['id']:<12} | {m['name']}")

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
    
    secho(f"{'Item ID':<10} | {'Type':<12} | {'Title'}", fg="blue", bold=True)
    echo("-" * 60)
    for item in response.json():
        item_id = item.get('content_id', item['id']) 
        echo(f"{item_id:<10} | {item['type']:<12} | {item['title']}")

@module.group(cls=HelpGroup)
@click.argument('item_id')
@click.pass_context
def item(ctx, item_id):
    """Interact with a specific item."""
    ctx.obj['ITEM_ID'] = config.resolve_alias(item_id)

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
            secho(f"API Error: 404 - Could not find an item with ID or Content ID '{item_id}' in module '{module_id}'.", fg="red")
            raise click.Abort()
            
        # Now make the actual request with the guaranteed correct Module Item ID
        response = api.make_request('GET', f'/api/v1/courses/{course_id}/modules/{module_id}/items/{real_item_id}')
        data = response.json()
        
        item_type = data.get('type')
        content_id = data.get('content_id')

        secho(f"--- Item Details: {data.get('title', 'Unknown')} ---", fg="blue", bold=True)
        echo(f"Type: {item_type}")
        echo(f"URL: {data.get('html_url')}")
        
        if item_type == 'Assignment' and content_id:
            # Fetch assignment details
            assign_res = api.make_request('GET', f'/api/v1/courses/{course_id}/assignments/{content_id}')
            assign_data = assign_res.json()
            echo("-" * 40)
            secho("Description:", bold=True)
            echo(strip_tags(assign_data.get('description', 'No description.')))
            echo("-" * 40)
            if 'due_at' in assign_data:
                echo(f"Due: {assign_data['due_at']}")
            if 'points_possible' in assign_data:
                echo(f"Points: {assign_data['points_possible']}")
        elif item_type == 'Page' and 'page_url' in data:
            page_url = data['page_url']
            page_res = api.make_request('GET', f'/api/v1/courses/{course_id}/pages/{page_url}')
            page_data = page_res.json()
            echo("-" * 40)
            secho("Content:", bold=True)
            echo(strip_tags(page_data.get('body', 'No content.')))
            echo("-" * 40)
        elif item_type in ['DiscussionTopic', 'Discussion'] and content_id:
            disc_res = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics/{content_id}')
            disc_data = disc_res.json()
            echo("-" * 40)
            secho("Prompt:", bold=True)
            echo(strip_tags(disc_data.get('message', 'No description.')))
            echo("-" * 40)
            secho(f"To view replies, use: canvas course {course_id} discuss view {content_id}", fg="cyan")
        elif item_type == 'Quiz' and content_id:
            quiz_res = api.make_request('GET', f'/api/v1/courses/{course_id}/quizzes/{content_id}')
            quiz_data = quiz_res.json()
            echo("-" * 40)
            secho("Description:", bold=True)
            echo(strip_tags(quiz_data.get('description', 'No description.')))
            echo("-" * 40)
            if 'due_at' in quiz_data:
                echo(f"Due: {quiz_data['due_at']}")
            if 'points_possible' in quiz_data:
                echo(f"Points: {quiz_data['points_possible']}")
        elif item_type == 'File' and content_id:
            file_res = api.make_request('GET', f'/api/v1/courses/{course_id}/files/{content_id}')
            file_data = file_res.json()
            echo("-" * 40)
            echo(f"Filename: {file_data.get('filename')}")
            echo(f"Size:     {file_data.get('size', 0) // 1024} KB")
            echo(f"Created:  {file_data.get('created_at')}")
            echo("-" * 40)

        if content_id and item_type == 'Assignment':
            echo(f"\nIf you want to submit this item, use Assignment ID: {content_id}")
            secho(f"Command: canvas-cli submit <filepath> {course_id} {content_id}", fg="yellow")
            
    except requests.exceptions.RequestException as e:
         secho(f"Network Error: {e}", fg="red")
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
    
    secho(f"--- PRE-SUBMISSION CHECK ---", fg="yellow", bold=True)
    echo(f"File:       {filepath}")
    echo(f"Course:     {course_id} (ID: {resolved_course_id})")
    echo(f"Assignment: {assignment_id} (ID: {resolved_assignment_id})")
    
    if not click.confirm("\nAre you sure you want to proceed with this submission?", default=False):
        echo("Submission cancelled.")
        return

    # Use resolved IDs for the rest of the function
    course_id = resolved_course_id
    assignment_id = resolved_assignment_id
    
    echo(f"\nPreparing to submit '{filepath}' to Course: {course_id}, Assignment: {assignment_id}")
    
    file_size = os.path.getsize(filepath)
    if file_size == 0:
        secho(f"Error: The file '{filepath}' is empty (0 bytes). Canvas does not accept empty file submissions.", fg="red")
        return
        
    file_name = os.path.basename(filepath)
    content_type, _ = mimetypes.guess_type(filepath)
    if not content_type:
        content_type = 'application/octet-stream'

    # Step 1: Request Upload URL
    echo("Step 1: Requesting upload authorization...")
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
        secho(f"Failed to request upload URL. Ensure the assignment accepts file uploads.", fg="red")
        return

    upload_data = response.json()
    upload_url = upload_data.get('upload_url')
    upload_params = upload_data.get('upload_params', {})

    if not upload_url:
        secho("Error: No upload URL received from Canvas.", fg="red")
        return

    # Step 2: Upload File to AWS S3 (or Canvas storage)
    echo("Step 2: Uploading file data...")
    try:
        with open(filepath, 'rb') as f:
            files = {'file': (file_name, f, content_type)}
            # We don't use api.make_request here because this is an external URL and doesn't need our Canvas token
            upload_response = requests.post(upload_url, data=upload_params, files=files)
            if not upload_response.ok:
                secho(f"Error during file upload: {upload_response.status_code} - {upload_response.text}", fg="red")
                return
    except Exception as e:
        secho(f"Error during file upload network request: {e}", fg="red")
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
                secho(f"Error during upload confirmation redirect: {e}", fg="red")
                return
        else:
            file_info = upload_response.json()
    else:
        try:
            file_info = upload_response.json()
        except:
            secho(f"Unexpected response during upload: {upload_response.status_code}", fg="red")
            return

    file_id = file_info.get('id')
    if not file_id:
        secho("Error: Could not retrieve uploaded file ID.", fg="red")
        return

    # Step 3: Attach the uploaded file to the assignment submission
    echo("Step 3: Attaching file to submission...")
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
             secho(f"✅ Successfully submitted '{file_name}'! Submission ID: {final_data.get('id')}", fg="green")
             
             # Post-Submission Verification
             echo("🔍 Performing automated verification...")
             verify_res = api.make_request('GET', f'/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self')
             verify_data = verify_res.json()
             
             if verify_data.get('workflow_state') in ['submitted', 'graded', 'pending_review']:
                 secho("✅ Verification SUCCESS: Canvas confirms receipt of submission.", fg="green")
                 attachments = verify_data.get('attachments', [])
                 if any(a.get('display_name') == file_name or a.get('filename') == file_name for a in attachments):
                     secho(f"✅ Verification SUCCESS: File '{file_name}' is correctly attached.", fg="green")
                 else:
                     secho(f"⚠️ Verification WARNING: File name '{file_name}' not found in attachments list. Please check manually.", fg="yellow")
             else:
                 secho(f"🚨 Verification FAILURE: Canvas reports state as '{verify_data.get('workflow_state')}'.", fg="red")
        else:
             secho(f"⚠️ Submission accepted, but status is '{final_data.get('workflow_state')}'. Please verify on Canvas.", fg="yellow")
    except Exception as e:
        secho(f"Error finalizing submission: {e}", fg="red")

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
    secho(f"Alias '{name}' -> '{target_id}' saved.", fg="green")

@cli.command(name="todo")
def todo():
    """List upcoming assignments."""
    response = api.make_request('GET', '/api/v1/users/self/todo')
    todos = response.json()
    
    secho(f"{'Due Date':<20} | {'Course':<15} | {'Assignment'}", fg="blue", bold=True)
    echo("-" * 70)
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
            
        echo(f"{str(due)[:20]:<20} | {str(course_id):<15} | {title}")

@cli.command(name="grades")
def grades():
    """Display current grades for active courses."""
    response = api.make_request('GET', '/api/v1/courses', params={'enrollment_state': 'active', 'include[]': 'total_scores'})
    courses = [c for c in response.json() if 'name' in c]

    secho(f"{'Course Name':<35} | {'Grade':<5} | {'Score'}", fg="blue", bold=True)
    echo("-" * 55)
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
        echo(f"{c['name'][:35]:<35} | {str(grade):<5} | {str(score)}")

@cli.group(cls=HelpGroup)
def inbox():
    """Manage Canvas messages."""
    pass

@inbox.command(name="list")
def list_inbox():
    """List unread Canvas messages."""
    response = api.make_request('GET', '/api/v1/conversations', params={'workflow_state': 'unread'})
    msgs = response.json()
    
    secho(f"{'ID':<10} | {'Subject':<30} | {'Last Message'}", fg="blue", bold=True)
    echo("-" * 65)
    for m in msgs:
        subject = m.get('subject', 'No Subject')
        last_msg = m.get('last_message', '')
        echo(f"{m['id']:<10} | {subject[:30]:<30} | {last_msg[:20]}...")

@course.group(name="discuss", cls=HelpGroup)
@click.pass_context
def discuss(ctx):
    """Manage discussion boards."""
    pass

@discuss.command(name="list")
@click.pass_context
def list_discussions(ctx):
    """
    List discussion topics for the course.
    
    Example: canvas course cs101 discuss list
    """
    course_id = ctx.obj['COURSE_ID']
    response = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics', params={'per_page': 100})
    topics = response.json()

    if not topics:
        secho("No discussion topics found.", fg="yellow")
        return

    secho(f"{'Topic ID':<12} | {'Title'}", fg="blue", bold=True)
    echo("-" * 50)
    for t in topics:
        echo(f"{t['id']:<12} | {t.get('title', 'No Title')}")

@discuss.command(name="view")
@click.argument('topic_id')
@click.option('--entry-id', help="The ID of a specific student's reply to view threaded responses.")
@click.pass_context
def view_discussion(ctx, topic_id, entry_id):
    """
    View the prompt and replies for a discussion topic.
    
    Example: 
    canvas course cs101 discuss view 555123
    canvas course cs101 discuss view 555123 --entry-id 999888
    """
    course_id = ctx.obj['COURSE_ID']
    topic_id = config.resolve_alias(topic_id)
    
    try:
        if entry_id:
            # Get the specific entry and its replies
            entries_res = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries/{entry_id}/replies', params={'per_page': 50})
            entries = entries_res.json()
            
            if not entries:
                secho("\nNo threaded replies yet for this entry.", fg="yellow")
                return
                
            secho(f"\n--- {len(entries)} Threaded Replies to Entry {entry_id} ---", fg="cyan", bold=True)
            for entry in entries:
                author = entry.get('user_name', 'Unknown Student')
                date = entry.get('created_at', '')[:10]
                reply_id = entry.get('id')
                secho(f"\n>> {author} ({date}) [Reply ID: {reply_id}]:", fg="green")
                echo(strip_tags(entry.get('message', '')))
            return

        # Get the main topic prompt
        topic_res = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}')
        topic_data = topic_res.json()
        
        secho(f"\n=== {topic_data.get('title', 'Discussion Topic')} ===", fg="blue", bold=True)
        secho(f"Author: {topic_data.get('user_name', 'Teacher')} | Posted: {topic_data.get('posted_at', 'Unknown')}")
        echo("-" * 60)
        echo(strip_tags(topic_data.get('message', 'No description.')))
        echo("=" * 60)
        
        # Get the replies
        entries_res = api.make_request('GET', f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries', params={'per_page': 50})
        entries = entries_res.json()
        
        if not entries:
            secho("\nNo replies yet.", fg="yellow")
            return
            
        secho(f"\n--- {len(entries)} Replies ---", fg="cyan", bold=True)
        for entry in entries:
            author = entry.get('user_name', 'Unknown Student')
            date = entry.get('created_at', '')[:10]
            entry_id = entry.get('id')
            
            # Check if there are any threaded replies to this entry
            has_replies = " (Has threaded replies)" if entry.get('has_more_replies') or entry.get('recent_replies') else ""
            
            secho(f"\n> {author} ({date}) [Entry ID: {entry_id}]{has_replies}:", fg="green")
            echo(strip_tags(entry.get('message', '')))
            
    except Exception as e:
        secho(f"Error fetching discussion: {e}", fg="red")

@discuss.command(name="reply")
@click.argument('topic_id')
@click.argument('message', required=False)
@click.option('--file', type=click.Path(exists=True), help="Path to a plain text file (.txt, .md) containing your reply. Newlines are automatically preserved.")
@click.option('--entry-id', help="The ID of a specific student's reply to thread your response under.")
@click.pass_context
def reply_discussion(ctx, topic_id, message, file, entry_id):
    """
    Post a reply to a discussion topic or a specific entry.
    
    Example:
    canvas course cs101 discuss reply 555123 "My response"
    canvas course cs101 discuss reply 555123 --file my_response.md
    """
    if not message and not file:
        secho("Error: You must provide either a MESSAGE argument or use the --file option.", fg="red")
        return
        
    if file:
        with open(file, 'r', encoding='utf-8') as f:
            raw_content = f.read()
    else:
        raw_content = message

    course_id = ctx.obj['COURSE_ID']
    topic_id = config.resolve_alias(topic_id)
    
    if entry_id:
        echo(f"Posting threaded reply to Entry {entry_id} in topic {topic_id}...")
        endpoint = f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries/{entry_id}/replies'
    else:
        echo(f"Posting top-level reply to topic {topic_id}...")
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
        secho(f"✅ Reply posted successfully! New Entry ID: {data.get('id')}", fg="green")
    except Exception as e:
        secho(f"Error posting reply: {e}", fg="red")

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
        secho("No files found or you don't have access.", fg="yellow")
        return

    download_dir = f"./course_{course_id}_files"
    os.makedirs(download_dir, exist_ok=True)
    secho(f"Downloading files to {download_dir}/...", fg="blue")

    for f in files_data:
        url = f.get('url')
        name = f.get('display_name')
        if not url or not name:
            continue
        
        filepath = os.path.join(download_dir, name)
        echo(f"Downloading: {name}")
        
        try:
            # Files download url typically requires auth but the returned URL from API often has a verification token
            # We'll pass the headers just in case
            headers = api.get_headers()
            r = requests.get(url, headers=headers)
            r.raise_for_status()
            with open(filepath, 'wb') as out_f:
                out_f.write(r.content)
        except Exception as e:
             secho(f"Failed to download {name}: {e}", fg="red")

    secho("Done!", fg="green")

@cli.command(name="help")
@click.argument('commands', nargs=-1)
@click.pass_context
def help_cmd(ctx, commands):
    """Show help for a specific command."""
    if not commands:
        echo(ctx.parent.get_help())
        return

    # Traverse the command tree
    cmd = cli
    for cmd_name in commands:
        if isinstance(cmd, click.Group):
            cmd = cmd.get_command(ctx, cmd_name)
        else:
            cmd = None
            
        if cmd is None:
            secho(f"No such command: {' '.join(commands)}", fg="red")
            return

    # Create a new context for the target command to generate the correct help output
    info_name = " ".join(commands)
    cmd_ctx = click.Context(cmd, info_name=info_name, parent=ctx.parent)
    echo(cmd.get_help(cmd_ctx))

if __name__ == '__main__':
    cli()
