import click

def get_color_setting():
    ctx = click.get_current_context(silent=True)
    if ctx and ctx.obj:
        return not ctx.obj.get('NO_COLOR', False)
    return True

def echo(*args, **kwargs):
    if 'color' not in kwargs:
        kwargs['color'] = get_color_setting()
    click.echo(*args, **kwargs)

def secho(*args, **kwargs):
    if 'color' not in kwargs:
        kwargs['color'] = get_color_setting()
    click.secho(*args, **kwargs)

def style(*args, **kwargs):
    if not get_color_setting():
        return args[0] if args else ""
    return click.style(*args, **kwargs)
