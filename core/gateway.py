"""
A free LLM gateway — OmniRoute or FreeLLMAPI — as one more rung for text calls.

WHY
    Every one-shot text call (core/gemini.py) went to Claude first, and the FAST
    ones are the frequent ones: a phone ringing, a button to find on screen, a
    line to classify. Each is a `claude -p` run counted against the
    subscription's usage limit — the same limit the long jobs (documents,
    projects) need. A self-hosted gateway pools the free tiers of dozens of
    providers (Groq, Cerebras, Mistral, OpenRouter's free models, ...) behind one
    OpenAI-compatible endpoint and fails over between them on its own. Sending
    the cheap calls there first leaves the subscription for work that needs
    Claude.

TWO GATEWAYS, ONE CLIENT
    OmniRoute   github.com/diegosouzapw/OmniRoute    http://localhost:20128/v1
    FreeLLMAPI  github.com/tashfeenahmed/freellmapi  http://localhost:3001/v1
    Both speak /v1/chat/completions with a Bearer key and route a virtual model
    ("auto...") across whatever providers the user connected on their dashboard.
    They differ only in the names of those virtual models and in their
    compression header, which is all _PRESETS holds. Any other OpenAI-compatible
    server (LiteLLM, llama.cpp, LM Studio) works as kind "openai", given model
    names. The kind is read from the port when it is not set.

WHAT GOES THERE  (config/api_keys.json)
    gateway_url          "" switches all of this off
    gateway_key          the gateway's own key, never a provider's
    gateway_tiers        ["fast"] by default — those tiers try the gateway
                         BEFORE Claude. Every other text call still goes Claude,
                         then the Gemini ladder, and reaches the gateway only
                         when both failed.
    gateway_model_fast / gateway_model_smart     override the preset's models
    gateway_vision       false by default: "auto" can land on a model that
                         cannot see, and it would answer anyway
    gateway_compression  sent as the gateway's per-request compression header
                         when set. Unset by default, on purpose: these prompts
                         often say "copy this exactly", and lossy rewriting is
                         the operator's call on the gateway dashboard, not this
                         file's.
    gateway_headers      any other headers, as a dict
"""
from __future__ import annotations

import base64
import json
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

_KEY_FILE = _BASE / "config" / "api_keys.json"

FAST = "fast"
SMART = "smart"

_PRESETS = {
    # auto/fast: lowest latency first. auto: the balanced default, which sticks
    # to the last provider that answered (fewer cold starts, more cache hits).
    "omniroute": {"fast": "auto/fast", "smart": "auto",
                  "compress_header": "x-omniroute-compression", "port": 20128},
    # auto:fast ranks by measured speed, auto:smart by intelligence.
    "freellmapi": {"fast": "auto:fast", "smart": "auto:smart",
                   "compress_header": "X-FreeLLM-Compress", "port": 3001},
    "openai": {"fast": "", "smart": "", "compress_header": "", "port": 0},
}

# Same reasoning as core/claude.py: a burst of side calls must not open twenty
# sockets at once, and a call that cannot get a slot falls to the next rung.
_SLOTS = threading.BoundedSemaphore(4)
_SLOT_WAIT = 3.0

# How long a failure is believed. A gateway that is not running fails in
# milliseconds, but printing that on every call is noise; one that times out
# costs the whole timeout, which must be paid once, not on every call.
_DOWN_SECONDS = 2 * 60          # connection refused: not started yet
_TIMEOUT_SECONDS = 10 * 60      # no answer in time
_EXHAUSTED_SECONDS = 5 * 60     # 429 / 5xx: every free route behind it is spent
_AUTH_SECONDS = 30 * 60         # 401 / 403: the key is wrong
_CONFIG_SECONDS = 30 * 60       # 400 / 404 on the model: the name is wrong


class GatewayError(RuntimeError):
    pass


# ── Configuration ────────────────────────────────────────────────────────────

def _config() -> dict:
    try:
        return json.loads(_KEY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _base_url(raw: str) -> str:
    """'localhost:20128', 'http://localhost:20128/' and '.../v1' all mean the
    same endpoint. A URL with a path of its own is left alone."""
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    if urlparse(url).path in ("", "/"):
        url += "/v1"
    return url


def _kind(cfg: dict, url: str) -> str:
    kind = str(cfg.get("gateway_kind") or "").strip().lower()
    if kind in _PRESETS:
        return kind
    try:
        port = urlparse(url).port
    except ValueError:
        port = None
    for name, preset in _PRESETS.items():
        if preset["port"] and port == preset["port"]:
            return name
    return "openai"


def settings() -> dict:
    """The gateway as configured, with the preset's defaults filled in."""
    cfg = _config()
    url = _base_url(str(cfg.get("gateway_url") or ""))
    kind = _kind(cfg, url)
    preset = _PRESETS[kind]
    tiers = cfg.get("gateway_tiers")
    if not isinstance(tiers, (list, tuple)):
        tiers = [FAST]
    headers = cfg.get("gateway_headers")
    return {
        "url": url,
        "key": str(cfg.get("gateway_key") or "").strip(),
        "kind": kind,
        "models": {FAST: str(cfg.get("gateway_model_fast") or preset["fast"]),
                   SMART: str(cfg.get("gateway_model_smart") or preset["smart"])},
        "tiers": [str(t).lower() for t in tiers],
        "vision": bool(cfg.get("gateway_vision", False)),
        "compression": str(cfg.get("gateway_compression") or "").strip(),
        "compress_header": preset["compress_header"],
        "headers": headers if isinstance(headers, dict) else {},
    }


def configured() -> bool:
    s = settings()
    return bool(s["url"] and s["models"][FAST] and s["models"][SMART])


# ── Cooldown ─────────────────────────────────────────────────────────────────

_cool_lock = threading.Lock()
_cool_until = 0.0
_cool_reason = ""


def _rest(reason: str, seconds: float) -> None:
    global _cool_until, _cool_reason
    with _cool_lock:
        _cool_until = time.monotonic() + seconds
        _cool_reason = reason
    print(f"[Gateway] {reason} — skipping it for {int(seconds // 60)} minutes")


def cooling() -> str:
    """Why the gateway is resting, or '' when it is available."""
    with _cool_lock:
        if _cool_until and time.monotonic() < _cool_until:
            return _cool_reason
        return ""


def reset_cooldown() -> None:
    global _cool_until, _cool_reason
    with _cool_lock:
        _cool_until, _cool_reason = 0.0, ""


def enabled() -> bool:
    return configured() and not cooling()


def prefers(tier: str) -> bool:
    """True when `tier` should try the gateway before Claude."""
    return enabled() and tier in settings()["tiers"]


# ── The call ─────────────────────────────────────────────────────────────────

def _content(prompt: str, images) -> str | list:
    if not images:
        return prompt
    parts: list[dict] = []
    for data, mime in images:
        b64 = base64.b64encode(data).decode("ascii")
        parts.append({"type": "image_url",
                      "image_url": {"url": f"data:{mime or 'image/png'};base64,{b64}"}})
    parts.append({"type": "text", "text": prompt})
    return parts


def _error_of(resp: requests.Response) -> str:
    try:
        err = resp.json().get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)[:200]
        if err:
            return str(err)[:200]
    except Exception:
        pass
    return (resp.text or "").strip()[:200]


def ask(prompt: str, tier: str = FAST, system: str = "",
        images: list[tuple[bytes, str]] | None = None,
        timeout: float = 30.0) -> str:
    """One chat completion through the gateway. Raises GatewayError; the caller
    moves on to the next rung."""
    s = settings()
    if not configured():
        raise GatewayError("no gateway is configured")
    if images and not s["vision"]:
        raise GatewayError("images are not sent to the gateway (gateway_vision is off)")
    if not _SLOTS.acquire(timeout=_SLOT_WAIT):
        raise GatewayError("every gateway slot is busy")

    model = s["models"][SMART if tier == SMART else FAST]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": _content(prompt, images)})
    headers = {"Content-Type": "application/json", **{str(k): str(v) for k, v in s["headers"].items()}}
    if s["key"]:
        headers["Authorization"] = f"Bearer {s['key']}"
    if s["compression"] and s["compress_header"]:
        headers[s["compress_header"]] = s["compression"]

    t0 = time.monotonic()
    try:
        resp = requests.post(f"{s['url']}/chat/completions", headers=headers, timeout=timeout,
                             json={"model": model, "messages": messages, "stream": False})
    except requests.exceptions.ConnectionError as e:
        _rest(f"not reachable at {s['url']}", _DOWN_SECONDS)
        raise GatewayError(f"not reachable: {e}") from e
    except requests.exceptions.Timeout as e:
        _rest(f"no answer within {int(timeout)}s", _TIMEOUT_SECONDS)
        raise GatewayError("timed out") from e
    except requests.exceptions.RequestException as e:
        raise GatewayError(f"{type(e).__name__}: {e}") from e
    finally:
        _SLOTS.release()

    code = resp.status_code
    if code != 200:
        detail = _error_of(resp)
        if code in (401, 403):
            _rest(f"key refused ({code})", _AUTH_SECONDS)
        elif code == 429 or code >= 500:
            _rest(f"no free route left ({code}: {detail[:80]})", _EXHAUSTED_SECONDS)
        elif code in (400, 404) and re.search(r"model", detail, re.I):
            _rest(f"model {model!r} refused ({detail[:80]})", _CONFIG_SECONDS)
        raise GatewayError(f"HTTP {code}: {detail}")

    try:
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = str((choice.get("message") or {}).get("content") or "").strip()
    except Exception as e:
        raise GatewayError(f"unreadable reply: {e}") from e
    # A reply cut off by the provider's output cap is worse than none: half a
    # JSON object parses as nothing, half a function looks complete. The next
    # rung answers instead.
    if choice.get("finish_reason") == "length":
        raise GatewayError("reply was truncated (finish_reason=length)")
    if not text:
        raise GatewayError("empty reply")

    usage = data.get("usage") or {}
    served = data.get("model") or model
    tin, tout = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    try:
        from core import usage as _usage
        _usage.record("gateway", tin, tout)
    except Exception:
        pass
    print(f"[Gateway] {model} -> {served} · {tin} in / {tout} out · "
          f"{time.monotonic() - t0:.1f}s")
    return text


# ── Status, for the settings panel ───────────────────────────────────────────

def status(timeout: float = 5.0) -> dict:
    """Reachability and model count from /v1/models. Never raises."""
    s = settings()
    out = {"configured": configured(), "url": s["url"], "kind": s["kind"],
           "models": s["models"], "tiers": s["tiers"], "reachable": False,
           "model_count": 0, "cooling": cooling(), "error": ""}
    if not s["url"]:
        return out
    headers = {"Authorization": f"Bearer {s['key']}"} if s["key"] else {}
    try:
        r = requests.get(f"{s['url']}/models", headers=headers, timeout=timeout)
        out["reachable"] = r.status_code == 200
        if r.status_code == 200:
            out["model_count"] = len(r.json().get("data") or [])
        else:
            out["error"] = f"HTTP {r.status_code}: {_error_of(r)}"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out


def test() -> tuple[bool, str]:
    """One real round trip on the FAST model. (ok, message for the user)."""
    reset_cooldown()
    if not configured():
        return False, "No gateway URL (or no model names for kind 'openai')."
    t0 = time.monotonic()
    try:
        reply = ask("Reply with exactly the word OK and nothing else.", FAST,
                    system="Output only what is asked.", timeout=30)
    except GatewayError as e:
        return False, str(e)[:200]
    ok = "ok" in reply.lower()
    s = settings()
    return ok, (f"Gateway ({s['kind']}) answered in {time.monotonic() - t0:.1f}s "
                f"with {s['models'][FAST]}" if ok else f"Unexpected reply: {reply[:80]}")
