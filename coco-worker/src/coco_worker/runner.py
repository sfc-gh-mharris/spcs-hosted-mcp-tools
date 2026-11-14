"""One Cortex Code run through the Cortex Agent SDK's query(), shaped into a small JSON result."""

import logging
import time
from collections import deque
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

import anyio
from cortex_agent_sdk.cortexcode import (
    AssistantMessage,
    CortexCodeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from coco_worker.policy import DISALLOWED_TOOLS, ReadOnlyPolicy

logger = logging.getLogger("coco_worker")

SYSTEM_PROMPT = (
    "You run unattended inside a Snowflake service; nobody can answer questions. "
    "Use read-only SQL (SELECT, SHOW, DESCRIBE) to answer, one statement per call. "
    "Do not create, change, or delete anything. Answer concisely."
)


@dataclass(frozen=True)
class RunSettings:
    connection: str
    model: str
    cli_path: str | None
    workdir: str
    max_seconds: int = 300
    effort: str = "low"
    # Extra environment for the CLI process only, e.g. a writable SNOWFLAKE_HOME (see cli_home).
    cli_env: dict[str, str] = field(default_factory=dict)


def _options(settings: RunSettings, max_turns: int, policy: ReadOnlyPolicy,
             stderr: deque[str]) -> CortexCodeAgentOptions:
    return CortexCodeAgentOptions(
        connection=settings.connection,
        model=settings.model,
        effort=settings.effort,
        max_turns=max_turns,
        cli_path=settings.cli_path,
        cwd=settings.workdir,
        env=dict(settings.cli_env),
        can_use_tool=policy.can_use_tool,
        disallowed_tools=list(DISALLOWED_TOOLS),
        append_system_prompt=SYSTEM_PROMPT,
        no_mcp=True,
        only_explicit_skills=True,
        only_explicit_plugins=True,
        # Without a stderr callback the SDK drops the CLI's error output, and a failed start
        # shows only "exit code 1". Keep the tail for the error message.
        stderr=stderr.append,
    )


async def run_task(prompt: str, max_turns: int, timeout_s: float, settings: RunSettings, query_fn=query) -> dict[str, Any]:
    policy = ReadOnlyPolicy()
    stderr: deque[str] = deque(maxlen=40)
    texts: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    model: str | None = None
    result: ResultMessage | None = None
    error: str | None = None
    started = time.perf_counter()

    with anyio.move_on_after(timeout_s) as scope:
        try:
            # aclosing() makes sure the SDK disconnects (and stops the CLI) even on timeout.
            async with aclosing(query_fn(prompt=prompt, options=_options(settings, max_turns, policy, stderr))) as messages:
                async for message in messages:
                    if isinstance(message, SystemMessage) and message.subtype == "init":
                        model = message.data.get("model")
                    elif isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock) and block.text:
                                texts.append(block.text)
                            elif isinstance(block, ToolUseBlock):
                                tool_uses.append({"name": block.name, "input": block.input})
                    elif isinstance(message, ResultMessage):
                        result = message
        except Exception as exc:  # CLI missing, auth failure, protocol error
            error = f"{type(exc).__name__}: {exc}"
            if stderr:
                error += "\nCLI stderr (last lines):\n" + "\n".join(list(stderr)[-15:])

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if scope.cancelled_caught:
        subtype, ok = "timeout", False
        error = f"stopped after {timeout_s} s"
    elif error:
        subtype, ok = "exception", False
    elif result is None:
        subtype, ok, error = "no_result", False, "the CLI ended without a result message"
    else:
        subtype, ok = result.subtype, not result.is_error

    answer = (result.result if result and result.result else None) or (texts[-1] if texts else "")
    out = {
        "ok": ok,
        "subtype": subtype,
        "answer": answer,
        "error": error or (", ".join(result.errors) if result and result.errors else None),
        "turns": result.num_turns if result else None,
        "duration_ms": result.duration_ms if result else elapsed_ms,
        "model": model,
        "usage": result.usage if result else None,
        "tool_uses": tool_uses,
        "denials": policy.denials,
    }
    logger.info("run ok=%s subtype=%s turns=%s tools=%d denials=%d ms=%s", ok, subtype, out["turns"],
                len(tool_uses), len(policy.denials), out["duration_ms"])
    return out
