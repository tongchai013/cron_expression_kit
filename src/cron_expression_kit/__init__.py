"""Cron expression parsing and next-fire time computation.

This package exposes a small, dependency-free API for working with standard
five-field cron expressions. The public surface is intentionally narrow:
:class:`CronExpression` and :class:`CronError`.
"""

from .core import CronError, CronExpression

__all__ = ["CronError", "CronExpression"]
