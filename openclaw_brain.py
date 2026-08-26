"""Bridge to the headless OpenClaw gateway.

We invoke `node openclaw.mjs agent ... --json` (bypassing the .cmd wrapper so
message text with spaces/quotes/newlines is passed safely as argv). The running
OpenClaw gateway performs the actual model call (OpenRouter / Gemini); this
process only relays the prompt and reads back the reply text.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil

# Default install path for the global npm package on this machine.
_DEFAULT_MJS = os.path.expandvars(
    r"%APPDATA%\npm\node_modules\openclaw\openclaw.mjs"
)


def _resolve_node() -> str:
    return os.getenv("NODE_BIN") or shutil.which("node") or "node"


def _resolve_mjs() -> str:
    explicit = os.getenv("OPENCLAW_MJS")
    if explicit:
        return explicit
    if os.path.isfile(_DEFAULT_MJS):
        return _DEFAULT_MJS
    # Fall back to the .cmd on PATH resolving symlink dir.
    return _DEFAULT_MJS


AGENT = os.getenv("OPENCLAW_AGENT", "main")
NODE = _resolve_node()
MJS = _resolve_mjs()


class BrainError(RuntimeError):
    pass


def _extract_reply(stdout: str) -> str:
    """Parse the agent --json envelope and return the reply text."""
    stdout = stdout.strip()
    if not stdout:
        raise BrainError("empty output from openclaw")
    # The envelope is a single JSON object; tolerate leading noise by slicing
    # from the first opening brace.
    start = stdout.find("{")
    if start == -1:
        raise BrainError(f"no json in output: {stdout[:200]}")
    data = json.loads(stdout[start:])
    payloads = (data.get("result") or {}).get("payloads") or []
    parts = [p.get("text") for p in payloads if p.get("text")]
    reply = "\n\n".join(parts).strip()
    if not reply:
        raise BrainError("agent returned no text")
    return reply


async def ask(text: str, session_id: str, timeout: float = 120.0) -> str:
    """Send `text` to the OpenClaw agent and return its reply.

    `session_id` keeps a separate conversation/memory per Telegram chat.
    """
    args = [
        NODE,
        MJS,
        "agent",
        "--agent", AGENT,
        "--session-id", session_id,
        "--thinking", "off",   # Gemini has no thinking levels; avoids retries
        "--json",
        "-m", text,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise BrainError("openclaw timed out")

    # NOTE: the CLI may exit non-zero even on success, so we parse stdout first
    # and only treat it as an error if no usable JSON came back.
    try:
        return _extract_reply(out.decode("utf-8", "replace"))
    except (BrainError, json.JSONDecodeError) as exc:
        detail = err.decode("utf-8", "replace")[-400:]
        raise BrainError(f"{exc} | stderr: {detail}") from exc
