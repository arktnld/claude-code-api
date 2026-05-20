from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

_DANGEROUS_PATH_PATTERNS = [
    r"\.\.",           # parent directory traversal
    r"~",              # home directory expansion
    r"\$\{",           # variable expansion ${...}
    r"\$\(",           # command substitution $(...)
    r"\$[A-Za-z_]",   # env var $VAR
    r"`",              # backtick command substitution
    r"\x00",           # null byte
]

_FS_MODIFYING_COMMANDS = {
    "mkdir", "touch", "cp", "mv", "rm", "rmdir", "ln", "install", "tee", "cd",
}
_READ_ONLY_COMMANDS = {
    "cat", "ls", "head", "tail", "less", "more", "which", "whoami", "pwd",
    "echo", "printf", "env", "printenv", "date", "wc", "sort", "uniq",
    "diff", "file", "stat", "du", "df", "tree", "realpath", "dirname", "basename",
}
_FIND_MUTATING = {"-delete", "-exec", "-execdir", "-ok", "-okdir"}
_CMD_SEPARATORS = {"&&", "||", ";", "|", "&"}


class SecurityValidator:
    def __init__(self, approved_directory: Path) -> None:
        self.approved_directory = approved_directory.resolve()

    def validate_path(
        self, user_path: str, current_dir: Optional[Path] = None
    ) -> tuple[bool, Optional[Path], Optional[str]]:
        if not user_path or not user_path.strip():
            return False, None, "Empty path"

        user_path = user_path.strip()

        for pattern in _DANGEROUS_PATH_PATTERNS:
            if re.search(pattern, user_path):
                logger.warning("dangerous_path_pattern", path=user_path, pattern=pattern)
                return False, None, f"Path contains forbidden pattern"

        base = current_dir or self.approved_directory

        try:
            target = Path(user_path) if user_path.startswith("/") else base / user_path
            target = target.resolve()

            if not target.is_relative_to(self.approved_directory):
                logger.warning("path_traversal", path=user_path, resolved=str(target))
                return False, None, "Path outside approved directory"

            return True, target, None
        except Exception as e:
            return False, None, f"Invalid path: {e}"

    def validate_bash_boundary(
        self,
        command: str,
        working_directory: Path,
        approved_directory: Path,
    ) -> tuple[bool, Optional[str]]:
        try:
            tokens = shlex.split(command)
        except ValueError:
            return True, None

        if not tokens:
            return True, None

        chains: list[list[str]] = []
        current: list[str] = []
        for token in tokens:
            if token in _CMD_SEPARATORS:
                if current:
                    chains.append(current)
                current = []
            else:
                current.append(token)
        if current:
            chains.append(current)

        resolved_approved = approved_directory.resolve()

        for cmd_tokens in chains:
            if not cmd_tokens:
                continue

            base_cmd = Path(cmd_tokens[0]).name

            if base_cmd in _READ_ONLY_COMMANDS:
                continue

            needs_check = False
            if base_cmd == "find":
                needs_check = any(t in _FIND_MUTATING for t in cmd_tokens[1:])
            elif base_cmd in _FS_MODIFYING_COMMANDS:
                needs_check = True

            if not needs_check:
                continue

            for token in cmd_tokens[1:]:
                if token.startswith("-"):
                    continue
                try:
                    resolved = (
                        Path(token).resolve()
                        if token.startswith("/")
                        else (working_directory / token).resolve()
                    )
                    if not resolved.is_relative_to(resolved_approved):
                        return False, (
                            f"Boundary violation: '{base_cmd}' targets '{token}' "
                            f"outside {resolved_approved}"
                        )
                except (ValueError, OSError):
                    continue

        return True, None
