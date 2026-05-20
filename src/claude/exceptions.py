from __future__ import annotations


class ClaudeError(Exception):
    """Base Claude error."""


class ClaudeTimeoutError(ClaudeError):
    """Operation timed out."""


class ClaudeProcessError(ClaudeError):
    """Process execution failed."""


class ClaudeParsingError(ClaudeError):
    """Failed to parse output."""


class ClaudeSessionError(ClaudeError):
    """Session management error."""


class ClaudeBudgetError(ClaudeError):
    """Budget limit exceeded."""
