import json
import os
import keyring

CONFIG_FILE = os.path.expanduser("~/.canvas_cli.json")
SERVICE_NAME = "canvas_cli"

def save_config(token, url):
    """Saves the URL to a config file and the token to the OS keychain."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"url": url}, f)
    
    keyring.set_password(SERVICE_NAME, "api_token", token)

def load_config():
    """Loads the URL from the config file and the token from the OS keychain."""
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            
    token = keyring.get_password(SERVICE_NAME, "api_token")
    if token:
        config['token'] = token
        
    return config

def set_alias(name, target_id):
    """Sets an alias name to a target ID."""
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            
    if 'aliases' not in config:
        config['aliases'] = {}
        
    config['aliases'][name] = str(target_id)
    
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

def resolve_alias(name_or_id):
    """Attempts to resolve a given string using the alias dictionary."""
    config = load_config()
    aliases = config.get('aliases', {})
    return aliases.get(str(name_or_id), str(name_or_id))

def resolve_course_id(course_id):
    """
    Resolves a course ID, automatically adding sis_course_id prefix
     if it's alphanumeric and not a known alias or internal numeric ID.
    """
    resolved = resolve_alias(course_id)
    
    # If it's already a prefixed ID, numeric, or 'self', leave it alone
    if (not resolved.isdigit() and 
        ':' not in resolved and 
        resolved.lower() != 'self' and
        len(resolved) > 0):
        return f"sis_course_id:{resolved}"
    
    return resolved

def get_url():
    """Helper to get just the URL with a default."""
    config = load_config()
    return config.get("url", "https://canvas.instructure.com")

def get_token():
    """Helper to get just the token."""
    config = load_config()
    return config.get("token")
