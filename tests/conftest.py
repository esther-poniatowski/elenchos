"""Pytest configuration and shared fixtures for elenchos tests."""

# The fake checks under fixtures/ are scripts that write a log and exit on import, so that
# `--doctest-modules` must not collect them.
collect_ignore = ["fixtures"]
