"""
Claude, reached through the user's own Claude Code subscription.

WHY CLAUDE CODE RATHER THAN THE API
    The person running this assistant already pays for Claude (Pro or Max), and
    Claude Code is how that subscription is used outside the chat window. So
    nothing here needs an Anthropic API key or bills per token: every call is a
    short `claude -p` run, signed in either with the login Claude Code already
    has on this machine, or with the long-lived token `claude setup-token`
    prints, pasted into ⚙ SETUP → CLAUDE. The token is stored in
    config/api_keys.json as "claude_oauth_token" and handed to the child process
    as CLAUDE_CODE_OAUTH_TOKEN; it never goes anywhere else.

WHAT IT DOES HERE
    Every one-shot text call the app used to send to Gemini — core/gemini.py
    asks here first and only walks its own ladder when Claude cannot answer —
    plus the jobs Gemini never did: agent tasks, skills, documents, motion
    design. The voice stays on Gemini Live: Claude has no realtime audio API.

MEASURED (Claude Code 2.1.289, Pro subscription, same afternoon)
    one-word reply, haiku          2.5s end to end, 0.9s of it the model
    one-word reply, sonnet         2.8s
    one-word reply, opus           3.5s   (Opus 5.5, Pro subscription, Oct 2026)
    OCR of a small PNG, haiku      3.1s
    three headlines via WebSearch  20s   <- why search stays on Gemini first
    So a one-shot call costs what the Gemini Live rung did (1.7 - 2.8s).

HOW A CALL IS KEPT LEAN
    --tools ""                 no tools unless the caller asks for them
    --setting-sources ""       the user's own hooks, plugins and CLAUDE.md stay out
    --strict-mcp-config        ...and so do their MCP servers
    --system-prompt-file       replaces Claude Code's large coding prompt
    --no-session-persistence   nothing piles up in ~/.claude/projects
    Agent runs are the exception: they keep Claude Code's own prompt and load
    the project settings of workspace/, which is where the skills live.
"""
from __future__ import annotations

import base64
import glob
import io
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

_KEY_FILE = _BASE / "config" / "api_keys.json"

FAST = "fast"     # classification, extraction, one-line decisions
SMART = "smart"   # reasoning, writing, long documents, images
AGENT = "agent"   # multi-step work with tools

# Opus does the thinking and the long jobs. FAST stays on Haiku: those calls are
# frequent, sit on latency-sensitive paths (a phone ringing) and would spend the
# subscription's Opus allowance on one-word answers. Each tier can be overridden
# in config/api_keys.json ("claude_model_fast" / "_smart" / "_agent").
_DEFAULT_MODELS = {FAST: "haiku", SMART: "opus", AGENT: "opus"}

# What an agent run may use, and what it may use WITHOUT asking. Nobody is at a
# terminal to answer a permission prompt, so the run is started in dontAsk mode:
# anything outside this list is refused outright rather than left hanging.
AGENT_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch",
               "Skill", "Bash", "TodoWrite")
# Bash is limited to running code the agent wrote in its own workspace and the
# converters skills reach for. `rm`, `curl | sh`, `sudo` and the rest are not
# on it, so they are refused without the agent being able to talk its way in.
AGENT_BASH = ("python3 *", "python *", "pip install *", "pip3 install *",
              "node *", "npm install *", "npx *", "ls *", "mkdir *", "cat *",
              "head *", "file *", "pdftoppm *", "soffice *", "libreoffice *")

# Concurrency. A one-shot is a few seconds of one process; an agent can run for
# minutes and spawn its own. Both are capped so a burst of requests cannot fill
# the machine with node processes.
_ONE_SHOT_SLOTS = threading.BoundedSemaphore(4)
_AGENT_SLOTS = threading.BoundedSemaphore(2)
_SLOT_WAIT = 5.0

# Variables a parent Claude Code session sets for ITS children. When MARK LV is
# started from inside one (a terminal in an IDE with Claude Code running), they
# would make every call here look like a sub-session of that one.
_SESSION_VARS = {
    "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_AGENT_SDK_VERSION",
    "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_CODE_EMIT_STARTUP_TIMING", "CLAUDE_CODE_QUESTION_PREVIEW_FORMAT",
    "CLAUDE_CODE_ENABLE_TASKS", "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING",
}

# The Messages API refuses an image over 5 MB of base64 or 8000 px on a side.
_IMAGE_MAX_B64 = 5 * 1024 * 1024
_IMAGE_MAX_SIDE = 7900
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class ClaudeError(RuntimeError):
    pass


@dataclass
class Result:
    text: str
    is_error: bool = False
    cost_usd: float = 0.0
    turns: int = 0
    duration_s: float = 0.0
    denials: list = field(default_factory=list)
    tokens_in: int = 0       # input, including what was written to the cache
    tokens_out: int = 0
    tokens_cached: int = 0   # read back from the prompt cache: far cheaper


def _usage_of(result: dict) -> tuple[int, int, int]:
    u = result.get("usage") or {}
    return (int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0),
            int(u.get("output_tokens") or 0),
            int(u.get("cache_read_input_tokens") or 0))


# ── Configuration ────────────────────────────────────────────────────────────

def _config() -> dict:
    try:
        return json.loads(_KEY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def engine() -> str:
    """'claude' (default) or 'gemini' — which one answers the text calls."""
    return "gemini" if str(_config().get("ai_engine", "claude")).lower() == "gemini" else "claude"


def model_for(tier: str) -> str:
    cfg = _config()
    key = {FAST: "claude_model_fast", SMART: "claude_model_smart",
           AGENT: "claude_model_agent"}.get(tier)
    return str(cfg.get(key) or _DEFAULT_MODELS.get(tier, "opus")) if key else tier


def workspace() -> Path:
    """Where agent runs work and where skills live (.claude/skills/<name>/)."""
    ws = _BASE / "workspace"
    (ws / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    return ws


def skills_dir() -> Path:
    return workspace() / ".claude" / "skills"


# ── Finding the binary ───────────────────────────────────────────────────────

_bin_lock = threading.Lock()
_bin_cached: str | None = None


def _version_key(path: str) -> tuple:
    m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", path)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _candidates() -> list[str]:
    home = Path.home()
    exe = ".exe" if sys.platform == "win32" else ""
    out = [str(home / ".local" / "bin" / f"claude{exe}"),
           str(home / ".claude" / "local" / f"claude{exe}"),
           str(home / ".npm-global" / "bin" / "claude"),
           "/usr/local/bin/claude", "/opt/homebrew/bin/claude"]
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            out.append(str(Path(appdata) / "npm" / "claude.cmd"))
    out += sorted(glob.glob(str(home / ".nvm" / "versions" / "node" / "*" / "bin" / "claude")),
                  reverse=True)
    # The IDE extensions ship their own native build. Newest first, because an
    # update leaves the old folder behind until the editor restarts.
    ext = []
    for editor in (".vscode", ".vscode-server", ".cursor", ".windsurf", ".vscode-oss"):
        ext += glob.glob(str(home / editor / "extensions" / "anthropic.claude-code-*"
                             / "resources" / "native-binary" / f"claude{exe}"))
    out += sorted(ext, key=_version_key, reverse=True)
    return out


def binary(refresh: bool = False) -> str | None:
    """Path of the claude executable, or None when Claude Code is not installed."""
    global _bin_cached
    with _bin_lock:
        if _bin_cached and not refresh and Path(_bin_cached).exists():
            return _bin_cached
        _bin_cached = None
        custom = str(_config().get("claude_path") or "").strip()
        found = [custom] if custom else []
        which = shutil.which("claude")
        if which:
            found.append(which)
        found += _candidates()
        for p in found:
            if p and Path(p).is_file() and os.access(p, os.X_OK):
                _bin_cached = p
                break
        return _bin_cached


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SESSION_VARS}
    # An agent's `python3` should be this app's Python, with python-pptx, PIL and
    # the rest of requirements.txt, not a bare system one: MARK LV is usually
    # started as .venv/bin/python main.py without the venv being activated.
    if not getattr(sys, "frozen", False):
        here = str(Path(sys.executable).parent)
        path = env.get("PATH", "")
        if here not in path.split(os.pathsep):
            env["PATH"] = here + (os.pathsep + path if path else "")
    # The subscription is the point. An API key in the environment would win
    # over it in -p mode and quietly start billing per token instead.
    env.pop("ANTHROPIC_API_KEY", None)
    token = str(_config().get("claude_oauth_token") or "").strip()
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


# ── Cooldown ─────────────────────────────────────────────────────────────────
# A Claude that is signed out or over its usage limit fails the same way on the
# next call and the one after. Asking again each time puts a 3-second failure in
# front of every request before Gemini gets to answer, so it is rested instead.

_cool_lock = threading.Lock()
_cool_until = 0.0
_cool_reason = ""

_AUTH_SECONDS = 10 * 60
_LIMIT_SECONDS = 30 * 60


def _classify(msg: str) -> tuple[str, float]:
    low = msg.lower()
    if any(s in low for s in ("not logged in", "/login", "invalid api key", "oauth",
                              "authentication", "401", "unauthorized")):
        return ("not signed in — run `claude setup-token` and paste the token in "
                "⚙ SETUP → CLAUDE", _AUTH_SECONDS)
    if any(s in low for s in ("usage limit", "rate limit", "limit reached", "429",
                              "overloaded", "credit balance")):
        return "usage limit reached", _LIMIT_SECONDS
    return "", 0.0


def _note_failure(msg: str) -> None:
    global _cool_until, _cool_reason
    reason, seconds = _classify(msg)
    if seconds:
        with _cool_lock:
            _cool_until = time.monotonic() + seconds
            _cool_reason = reason
        print(f"[Claude] {reason} — falling back to Gemini for {int(seconds // 60)} minutes")


def cooling() -> str:
    """Why Claude is resting, or '' when it is available."""
    with _cool_lock:
        if _cool_until and time.monotonic() < _cool_until:
            return _cool_reason
        return ""


def reset_cooldown() -> None:
    global _cool_until, _cool_reason
    with _cool_lock:
        _cool_until, _cool_reason = 0.0, ""


def enabled() -> bool:
    """True when text calls should go to Claude right now."""
    return engine() == "claude" and binary() is not None and not cooling()


# ── Images ───────────────────────────────────────────────────────────────────

def image_block(data: bytes, mime: str) -> tuple[dict, str]:
    """An API image block for these bytes, plus a note to add to the prompt when
    the picture had to be shrunk to fit the API's limits ('' otherwise)."""
    mime = (mime or "").lower()
    note = ""
    need_reencode = mime not in _IMAGE_TYPES or len(data) * 4 / 3 > _IMAGE_MAX_B64
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        w, h = im.size
        if max(w, h) > _IMAGE_MAX_SIDE:
            need_reencode = True
        if need_reencode:
            im = im.convert("RGB")
            if max(w, h) > _IMAGE_MAX_SIDE:
                im.thumbnail((_IMAGE_MAX_SIDE, _IMAGE_MAX_SIDE))
            quality = 90
            while True:
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=quality)
                if len(buf.getvalue()) * 4 / 3 <= _IMAGE_MAX_B64 or quality <= 40:
                    break
                quality -= 15
                im.thumbnail((int(im.width * 0.8), int(im.height * 0.8)))
            data, mime = buf.getvalue(), "image/jpeg"
            if im.size != (w, h):
                note = (f"(The image was resized from {w}x{h} to {im.width}x{im.height} "
                        f"pixels to fit; give any coordinates in the original "
                        f"{w}x{h} space.)")
    except Exception:
        if mime not in _IMAGE_TYPES:
            raise ClaudeError(f"unsupported image type {mime!r}")
    return ({"type": "image",
             "source": {"type": "base64", "media_type": mime,
                        "data": base64.b64encode(data).decode("ascii")}}, note)


# ── Running claude -p ────────────────────────────────────────────────────────

def _kill(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run(prompt: str, *, model: str, system: str = "", append_system: str = "",
        images: list[tuple[bytes, str]] | None = None,
        tools: tuple[str, ...] | list[str] = (), allowed: tuple[str, ...] | list[str] = (),
        cwd: Path | None = None, add_dirs: list[str] | None = None,
        setting_sources: str = "", skills: bool = False,
        timeout: float = 60.0, on_event: Callable[[dict], None] | None = None,
        usage_tag: str = "claude") -> Result:
    """One `claude -p` run, start to finish. Raises ClaudeError on any failure.

    `system` replaces Claude Code's own system prompt (one-shot calls);
    `append_system` adds to it (agent runs, which want the agentic prompt).
    `on_event` sees every stream-json event, for progress reporting.
    `usage_tag` is the engine name its tokens are counted under (core/usage)."""
    exe = binary()
    if not exe:
        raise ClaudeError("Claude Code is not installed (no `claude` command found)")

    content: list[dict] = []
    for data, mime in images or ():
        block, note = image_block(data, mime)
        content.append(block)
        if note:
            prompt = f"{prompt}\n\n{note}"
    content.append({"type": "text", "text": prompt})
    message = {"type": "user", "message": {"role": "user", "content": content}}

    tmp_files: list[str] = []

    def _tmp(text: str) -> str:
        fd, path = tempfile.mkstemp(prefix="jarvis-claude-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        tmp_files.append(path)
        return path

    args = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--verbose", "--model", model, "--no-session-persistence",
            "--strict-mcp-config", "--setting-sources", setting_sources,
            "--tools", ",".join(tools)]
    if allowed:
        args += ["--allowedTools", ",".join(allowed), "--permission-mode", "dontAsk"]
    if not skills:
        args.append("--disable-slash-commands")
    # Prompts travel through files, not argv: a multi-line system prompt does
    # not survive a Windows .cmd shim, and argv has a length limit stdin does not.
    if system:
        args += ["--system-prompt-file", _tmp(system)]
    if append_system:
        args += ["--append-system-prompt-file", _tmp(append_system)]
    for d in add_dirs or ():
        args += ["--add-dir", str(d)]

    popen_kw: dict = {}
    if sys.platform == "win32":
        popen_kw["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                     | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        popen_kw["start_new_session"] = True   # so a timeout kills its children too

    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(args, cwd=str(cwd or workspace()), env=_env(),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", **popen_kw)
    except OSError as e:
        for p in tmp_files:
            Path(p).unlink(missing_ok=True)
        raise ClaudeError(f"could not start Claude Code: {e}")

    lines: queue.Queue = queue.Queue()
    err_tail: list[str] = []

    def _pump_out():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def _pump_err():
        for line in proc.stderr:
            err_tail.append(line)
            del err_tail[:-20]

    threading.Thread(target=_pump_out, daemon=True, name="claude-out").start()
    threading.Thread(target=_pump_err, daemon=True, name="claude-err").start()

    result: dict | None = None
    try:
        try:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.close()
        except OSError:
            pass
        deadline = t0 + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                _kill(proc)
                raise ClaudeError(f"Claude did not answer within {int(timeout)}s")
            try:
                line = lines.get(timeout=min(left, 1.0))
            except queue.Empty:
                continue
            if line is None:
                break
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result":
                result = ev
            if on_event:
                try:
                    on_event(ev)
                except Exception:
                    pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill(proc)
    finally:
        for p in tmp_files:
            Path(p).unlink(missing_ok=True)

    if result is None:
        tail = "".join(err_tail).strip()[-300:]
        raise ClaudeError(tail or f"Claude Code exited ({proc.returncode}) without an answer")

    # Counted before the error check: a run that ended badly was still billed.
    tin, tout, tcached = _usage_of(result)
    try:
        from core import usage
        usage.record(usage_tag, tin, tout, tcached)
    except Exception:
        pass

    text = str(result.get("result") or "").strip()
    if result.get("is_error") or result.get("subtype", "success") != "success":
        raise ClaudeError(text or str(result.get("subtype") or "Claude reported an error"))
    return Result(text=text, cost_usd=float(result.get("total_cost_usd") or 0.0),
                  turns=int(result.get("num_turns") or 0),
                  duration_s=time.monotonic() - t0,
                  denials=list(result.get("permission_denials") or []),
                  tokens_in=tin, tokens_out=tout, tokens_cached=tcached)


def ask(prompt: str, tier: str = FAST, system: str = "",
        images: list[tuple[bytes, str]] | None = None,
        web: bool = False, timeout: float = 60.0) -> str:
    """A one-shot answer: no tools (web search only when asked), no skills, no
    project context. Raises ClaudeError; core/gemini.py turns that into a
    fallback to its own ladder."""
    if not _ONE_SHOT_SLOTS.acquire(timeout=_SLOT_WAIT):
        raise ClaudeError("every Claude slot is busy")
    try:
        tools = ("WebSearch", "WebFetch") if web else ()
        res = run(prompt, model=model_for(tier), system=system, images=images,
                  tools=tools, allowed=tools, timeout=timeout)
    except ClaudeError as e:
        _note_failure(str(e))
        raise
    finally:
        _ONE_SHOT_SLOTS.release()
    if not res.text:
        raise ClaudeError("Claude returned an empty reply")
    return res.text


def agent(task: str, *, append_system: str = "", model: str = "",
          add_dirs: list[str] | None = None, allow_bash: bool = True,
          timeout: float = 600.0,
          on_event: Callable[[dict], None] | None = None,
          cwd: Path | None = None, extra_bash: tuple[str, ...] = ()) -> Result:
    """Claude Code doing a multi-step job in workspace/ — or in `cwd`, with the
    skills found in its .claude/skills — plus `extra_bash` patterns on top of
    AGENT_BASH. Blocks until it is done; call it from a worker thread."""
    if not _AGENT_SLOTS.acquire(timeout=_SLOT_WAIT):
        raise ClaudeError("two Claude tasks are already running — wait for one to finish")
    try:
        tools = tuple(t for t in AGENT_TOOLS if allow_bash or t != "Bash")
        allowed = tuple(t for t in tools if t != "Bash")
        if allow_bash:
            allowed += tuple(f"Bash({p})" for p in AGENT_BASH + tuple(extra_bash))
        return run(task, model=model or model_for(AGENT), append_system=append_system,
                   tools=tools, allowed=allowed, add_dirs=add_dirs, cwd=cwd,
                   setting_sources="project", skills=True, timeout=timeout,
                   on_event=on_event, usage_tag="claude-agent")
    except ClaudeError as e:
        _note_failure(str(e))
        raise
    finally:
        _AGENT_SLOTS.release()


def tool_activity(ev: dict) -> str:
    """A short human label for an agent's tool call ('' for anything else), so
    the activity log can show what a long task is doing."""
    if ev.get("type") != "assistant":
        return ""
    for block in (ev.get("message") or {}).get("content") or ():
        if block.get("type") != "tool_use":
            continue
        name, inp = block.get("name", ""), block.get("input") or {}
        detail = (inp.get("file_path") or inp.get("command") or inp.get("query")
                  or inp.get("url") or inp.get("skill") or inp.get("pattern") or "")
        detail = " ".join(str(detail).split())
        if "/" in detail and name in ("Read", "Write", "Edit"):
            detail = detail.rsplit("/", 1)[-1]
        return f"{name} {detail[:60]}".strip()
    return ""


# ── Status, for the settings panel ───────────────────────────────────────────

def status(timeout: float = 20.0) -> dict:
    """What the settings panel shows. Runs `claude auth status`; never raises."""
    out = {"installed": False, "path": "", "version": "", "logged_in": False,
           "auth": "", "subscription": "", "email": "",
           "token_configured": bool(str(_config().get("claude_oauth_token") or "").strip()),
           "engine": engine(), "cooling": cooling(), "error": ""}
    exe = binary(refresh=True)
    if not exe:
        out["error"] = "Claude Code is not installed"
        return out
    out["installed"], out["path"] = True, exe
    kw: dict = {"capture_output": True, "text": True, "timeout": timeout, "env": _env()}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        v = subprocess.run([exe, "--version"], **kw)
        out["version"] = (v.stdout or "").strip().split(" ")[0]
        s = subprocess.run([exe, "auth", "status"], **kw)
        data = json.loads(s.stdout or "{}")
        out["logged_in"] = bool(data.get("loggedIn"))
        out["auth"] = str(data.get("authMethod") or "")
        out["subscription"] = str(data.get("subscriptionType") or "")
        out["email"] = str(data.get("email") or "")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out


def test() -> tuple[bool, str]:
    """One real round trip. (ok, message for the user)."""
    reset_cooldown()
    t0 = time.monotonic()
    try:
        reply = ask("Reply with exactly the word OK and nothing else.", FAST,
                    system="Output only what is asked.", timeout=60)
    except ClaudeError as e:
        return False, str(e)[:200]
    ok = "ok" in reply.lower()
    return ok, (f"Claude answered in {time.monotonic() - t0:.1f}s ({model_for(FAST)})"
                if ok else f"Unexpected reply: {reply[:80]}")
