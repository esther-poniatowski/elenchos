"""
Entry point for the `elenchos` package, invoked as a module.

Usage
-----
To launch the command-line interface, execute::

    python -m elenchos


See Also
--------
elenchos.cli: Module implementing the application's command-line interface.
"""

from .cli import app

app()
