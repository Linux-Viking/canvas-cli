import requests
import click
from . import config

def get_headers():
    token = config.get_token()
    if not token:
        click.secho("Error: No token configured. Run 'canvas setup' first.", fg="red")
        raise click.Abort()
    return {"Authorization": f"Bearer {token}"}

def make_request(method, endpoint, **kwargs):
    """Makes a request to the Canvas API."""
    url = f"{config.get_url()}{endpoint}"
    headers = get_headers()
    
    # Merge existing headers if provided
    if 'headers' in kwargs:
        headers.update(kwargs['headers'])
        kwargs['headers'] = headers
    else:
        kwargs['headers'] = headers

    try:
        response = requests.request(method, url, **kwargs)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        click.secho(f"API Error: {e.response.status_code} - {e.response.text}", fg="red")
        raise click.Abort()
    except requests.exceptions.RequestException as e:
        click.secho(f"Network Error: {e}", fg="red")
        raise click.Abort()
