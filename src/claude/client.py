from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    Message,
    PermissionResultAllow,
    PermissionResultDeny,
    ProcessError,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk._errors import MessageParseError
from claude_agent_sdk._internal.message_parser import parse_message

from src.config import Settings
from src.security.validators import SecurityValidator

from .exceptions import (
    ClaudeProcessError,
    ClaudeTimeoutError,
)

logger = structlog.get_logger()

TASK_COMPLETED_MSG = "Task completed. Tools used: {tools_summary}"


@dataclass
class ClaudeResponse:
    content: str
    session_id: str
    cost: float
    duration_ms: int
    num_turns: int
    is_error: bool = False
    error_type: Optional[str] = None
    tools_used: list[dict[str, Any]] = field(default_factory=list)
    interrupted: bool = False


@dataclass
class StreamUpdate:
    type: str  # 'assistant', 'tool', 'result'
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None


def _make_can_use_tool_callback(
    security_validator: SecurityValidator,
    working_directory: Path,
    approved_directory: Path,
) -> Any:
    _FILE_TOOLS = {"Write", "Edit", "Read", "MultiEdit"}
    _BASH_TOOLS = {"Bash", "bash", "shell"}

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> Any:
        if tool_name in _FILE_TOOLS:
            file_path = tool_input.get("file_path") or tool_input.get("path")
            if file_path:
                valid, _resolved, error = security_validator.validate_path(
                    file_path, working_directory
                )
                if not valid:
                    logger.warning(
                        "tool_denied_file",
                        tool=tool_name,
                        path=file_path,
                        error=error,
                    )
                    return PermissionResultDeny(message=error or "Invalid file path")

        if tool_name in _BASH_TOOLS:
            command = tool_input.get("command", "")
            if command:
                valid, error = security_validator.validate_bash_boundary(
                    command, working_directory, approved_directory
                )
                if not valid:
                    logger.warning(
                        "tool_denied_bash",
                        tool=tool_name,
                        command=command,
                        error=error,
                    )
                    return PermissionResultDeny(
                        message=error or "Bash directory boundary violation"
                    )

        return PermissionResultAllow()

    return can_use_tool


class ClaudeClient:
    def __init__(
        self,
        config: Settings,
        security_validator: Optional[SecurityValidator] = None,
    ) -> None:
        self.config = config
        self.security_validator = security_validator

        if config.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = config.anthropic_api_key
            logger.info("claude_auth_api_key", key_prefix=config.anthropic_api_key[:8] + "...")
        else:
            logger.info("claude_auth_cli")

    def _is_retryable(self, exc: BaseException) -> bool:
        if isinstance(exc, CLIConnectionError):
            return "mcp" not in str(exc).lower()
        return False

    async def execute(
        self,
        prompt: str,
        working_directory: Path,
        session_id: Optional[str] = None,
        continue_session: bool = False,
        stream_callback: Optional[Callable[[StreamUpdate], Any]] = None,
        interrupt_event: Optional[asyncio.Event] = None,
        model_override: Optional[str] = None,
        system_override: Optional[str] = None,
        effort: Optional[str] = None,
        permission_mode: Optional[str] = None,
        output_format: Optional[dict] = None,
        allowed_tools_override: Optional[list[str]] = None,
        disallowed_tools_override: Optional[list[str]] = None,
        max_turns_override: Optional[int] = None,
    ) -> ClaudeResponse:
        start_time = asyncio.get_event_loop().time()

        logger.info(
            "claude_execute",
            cwd=str(working_directory),
            session_id=session_id,
            resume=continue_session,
        )

        try:
            stderr_lines: list[str] = []

            def _on_stderr(line: str) -> None:
                if len(stderr_lines) < 500:
                    stderr_lines.append(line)
                logger.debug("claude_stderr", line=line)

            # Build system prompt with CLAUDE.md
            system_prompt = (
                f"All file operations must stay within {working_directory}. "
                "Use relative paths."
            )
            base_system = system_override or self.config.claude_system_prompt
            if base_system:
                system_prompt = base_system + "\n\n" + system_prompt

            claude_md = working_directory / "CLAUDE.md"
            try:
                claude_md_content = await asyncio.to_thread(claude_md.read_text, "utf-8")
                system_prompt += "\n\n" + claude_md_content
            except FileNotFoundError:
                pass

            options = ClaudeAgentOptions(
                max_turns=max_turns_override or self.config.claude_max_turns,
                model=model_override or self.config.claude_model or None,
                max_budget_usd=self.config.claude_max_cost_per_request,
                cwd=str(working_directory),
                allowed_tools=allowed_tools_override or self.config.allowed_tools_list,
                disallowed_tools=disallowed_tools_override or self.config.disallowed_tools_list,
                cli_path=self.config.claude_cli_path or None,
                include_partial_messages=stream_callback is not None,
                sandbox={
                    "enabled": self.config.sandbox_enabled,
                    "autoAllowBashIfSandboxed": True,
                    "excludedCommands": self.config.excluded_commands_list,
                },
                system_prompt=system_prompt,
                setting_sources=["project"],
                stderr=_on_stderr,
            )

            effective_effort = effort or self.config.claude_effort
            if effective_effort:
                options.effort = effective_effort
            effective_perm = permission_mode or self.config.claude_permission_mode
            if effective_perm:
                options.permission_mode = effective_perm
            if output_format:
                options.output_format = output_format

            if self.security_validator:
                options.can_use_tool = _make_can_use_tool_callback(
                    security_validator=self.security_validator,
                    working_directory=working_directory,
                    approved_directory=self.config.approved_path,
                )

            if session_id and continue_session:
                options.resume = session_id

            messages: list[Message] = []
            interrupted = False

            async def _run() -> None:
                client = ClaudeSDKClient(options)
                try:
                    await client.connect()
                    await client.query(prompt)

                    async for raw_data in client._query.receive_messages():
                        try:
                            message = parse_message(raw_data)
                        except MessageParseError:
                            continue

                        messages.append(message)

                        if isinstance(message, ResultMessage):
                            break

                        if stream_callback and isinstance(message, AssistantMessage):
                            await self._handle_stream(message, stream_callback)
                finally:
                    await client.disconnect()

            # Retry loop
            max_attempts = max(1, self.config.claude_retry_max_attempts)
            last_exc: Optional[BaseException] = None

            for attempt in range(max_attempts):
                messages.clear()

                if attempt > 0:
                    delay = min(
                        self.config.claude_retry_base_delay
                        * (self.config.claude_retry_backoff_factor ** (attempt - 1)),
                        self.config.claude_retry_max_delay,
                    )
                    logger.warning("claude_retry", attempt=attempt + 1, delay=delay)
                    await asyncio.sleep(delay)

                run_task = asyncio.create_task(_run())

                # Interrupt watcher — cancels run_task if event is set
                interrupt_watcher: Optional[asyncio.Task[None]] = None
                if interrupt_event is not None:
                    async def _cancel_on_interrupt() -> None:
                        nonlocal interrupted
                        await interrupt_event.wait()
                        interrupted = True
                        run_task.cancel()

                    interrupt_watcher = asyncio.create_task(_cancel_on_interrupt())

                try:
                    await asyncio.wait_for(
                        asyncio.shield(run_task),
                        timeout=self.config.claude_timeout_seconds,
                    )
                    break
                except asyncio.CancelledError:
                    if not interrupted:
                        raise
                    try:
                        await run_task
                    except asyncio.CancelledError:
                        pass
                    break  # user interrupted — don't retry
                except asyncio.TimeoutError:
                    run_task.cancel()
                    try:
                        await run_task
                    except asyncio.CancelledError:
                        pass
                    raise
                except CLIConnectionError as exc:
                    if self._is_retryable(exc) and attempt < max_attempts - 1:
                        last_exc = exc
                        continue
                    raise
                finally:
                    if interrupt_watcher is not None:
                        interrupt_watcher.cancel()
            else:
                if last_exc is not None:
                    raise last_exc

            # Extract results
            cost = 0.0
            tools_used: list[dict[str, Any]] = []
            claude_session_id = None
            result_content = None

            for msg in messages:
                if isinstance(msg, ResultMessage):
                    cost = getattr(msg, "total_cost_usd", 0.0) or 0.0
                    claude_session_id = getattr(msg, "session_id", None)
                    result_content = getattr(msg, "result", None)

                    for m in messages:
                        if isinstance(m, AssistantMessage):
                            for block in getattr(m, "content", []) or []:
                                if isinstance(block, ToolUseBlock):
                                    tools_used.append({
                                        "name": getattr(block, "name", "unknown"),
                                        "input": getattr(block, "input", {}),
                                    })
                    break

            # Fallback session_id from stream events
            if not claude_session_id:
                for msg in messages:
                    sid = getattr(msg, "session_id", None)
                    if sid and not isinstance(msg, ResultMessage):
                        claude_session_id = sid
                        break

            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            final_session_id = claude_session_id or session_id or ""

            # Extract content
            if result_content is not None:
                content = str(result_content).strip()
            else:
                parts = []
                for m in messages:
                    if isinstance(m, AssistantMessage):
                        for block in getattr(m, "content", []) or []:
                            if hasattr(block, "text"):
                                parts.append(block.text)
                content = "\n".join(parts).strip()

            if not content and tools_used:
                names = list(dict.fromkeys(
                    t["name"] for t in tools_used if t.get("name")
                ))
                content = TASK_COMPLETED_MSG.format(
                    tools_summary=", ".join(names) or "unknown"
                )

            return ClaudeResponse(
                content=content,
                session_id=final_session_id,
                cost=cost,
                duration_ms=duration_ms,
                num_turns=len([
                    m for m in messages
                    if isinstance(m, (UserMessage, AssistantMessage))
                ]),
                tools_used=tools_used,
                interrupted=interrupted,
            )

        except asyncio.TimeoutError:
            logger.error("claude_timeout", timeout=self.config.claude_timeout_seconds)
            raise ClaudeTimeoutError(
                f"Claude timed out after {self.config.claude_timeout_seconds}s"
            )
        except CLINotFoundError as e:
            logger.error("claude_cli_not_found", error=str(e))
            raise ClaudeProcessError(
                "Claude Code CLI not found. Install: npm install -g @anthropic-ai/claude-code"
            )
        except (ProcessError, CLIConnectionError, CLIJSONDecodeError) as e:
            logger.error("claude_sdk_error", error=str(e), type=type(e).__name__)
            raise ClaudeProcessError(f"Claude SDK error: {e}")
        except ClaudeSDKError as e:
            logger.error("claude_error", error=str(e))
            raise ClaudeProcessError(f"Claude error: {e}")

    async def _handle_stream(
        self,
        message: AssistantMessage,
        callback: Callable[[StreamUpdate], Any],
    ) -> None:
        content = getattr(message, "content", [])
        if not content or not isinstance(content, list):
            return

        for block in content:
            if isinstance(block, ToolUseBlock):
                update = StreamUpdate(
                    type="tool",
                    tool_name=block.name,
                    tool_input=block.input,
                )
                await callback(update)
            elif isinstance(block, TextBlock):
                update = StreamUpdate(type="assistant", content=block.text)
                await callback(update)
