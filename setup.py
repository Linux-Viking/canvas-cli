from setuptools import setup, find_packages

setup(
    name='canvas_cli',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'click',
        'requests',
        'keyring',
    ],
    entry_points='''
        [console_scripts]
        canvas-cli=canvas.cli:cli
    ''',
)
