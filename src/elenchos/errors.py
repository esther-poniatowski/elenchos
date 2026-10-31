"""
Errors raised by `elenchos` when an input breaks the findings profile.

Classes
-------
ProfileError
    A component of an identity, an identity string or a SARIF result breaks the findings profile.
"""


class ProfileError(ValueError):
    """A component, an identity string or a SARIF result breaks the findings profile."""
