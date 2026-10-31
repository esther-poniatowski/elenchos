"""
Errors raised by `elenchos` when an input breaks the findings profile or a format of the consumer.

Classes
-------
ProfileError
    A component of an identity, an identity string or a SARIF result breaks the findings profile.
ConfigurationError
    The configuration or the suppressions file of a consumer breaks its published format.
"""


class ProfileError(ValueError):
    """A component, an identity string or a SARIF result breaks the findings profile."""


class ConfigurationError(ValueError):
    """The configuration or the suppressions file of a consumer breaks its published format."""
