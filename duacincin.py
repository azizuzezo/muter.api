#!/usr/bin/env python3
"""
DuaCincin - Gemini Web to OpenAI API proxy.

Converts Google Gemini's web interface into an OpenAI-compatible API server.
Zero authentication required. Works on any platform (Windows/macOS/Linux).

Usage:
    pip install httpx
    python duacincin.py [--port 8081] [--config config.json]

Client configuration (Cherry Studio, ChatBox, etc.):
    Base URL: http://localhost:8081/v1
    API Key: (anything or empty)

How it works:
    Sends requests directly to Gemini's public StreamGenerate endpoint.
    The backend does not verify authentication for basic text generation.
    Model selection via MODE_CATEGORY field [79] in the request payload.
    This is NOT a user-tier spoofing attack - the endpoint simply doesn't
    require auth for anonymous access.
"""
import json
import urllib.request
import urllib.parse
import time
import ssl
import sys
import uuid
import re
import os
import hashlib
import argparse
import base64
import threading
import random
import itertools
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

__version__ = "1.1.0"

# ─── Configuration ───────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "port": 8081,
    "host": "0.0.0.0",
    "retry_attempts": 3,
    "retry_delay_sec": 2,
    "request_timeout_sec": 180,
    "gemini_bl": "boq_assistant-bard-web-server_20260825.12_p0",
    "auth_user": None,
    "xsrf_token": None,
    "default_model": "gemini-3.7-flash",
    "log_requests": True,
    "cookie_file": None,
    "proxy": None,
    "api_keys": [],
    "temporary_chats": False,
    "max_concurrent_requests": 3,
}

CONFIG = dict(DEFAULT_CONFIG)

# Caps how many requests are in-flight to Gemini's backend at once. Extra
# requests queue here instead of firing in parallel, since bursts of
# simultaneous requests are what trip Google's rate limiting (429s cascading
# into 502s), not the total requests-per-minute on their own.
_upstream_semaphore = threading.BoundedSemaphore(max(1, CONFIG["max_concurrent_requests"]))
_reqid_lock = threading.Lock()
_reqid_counter = itertools.count(int(time.time()) % 1000000)


def next_reqid() -> int:
    """Monotonically increasing _reqid, safe under concurrent requests.

    Plain int(time.time()) % 1_000_000 gives two requests in the same
    wall-clock second an identical _reqid, which the backend can reject.
    """
    with _reqid_lock:
        return next(_reqid_counter) % 1000000


def retry_sleep_sec(attempt: int, err: Exception = None) -> float:
    """Exponential backoff with jitter; extra cautious on 429s so concurrent
    retrying threads spread out instead of hammering the same window again."""
    status = getattr(err, "code", None) or getattr(getattr(err, "response", None), "status_code", None)
    base = CONFIG["retry_delay_sec"] * (2 ** attempt)
    if status == 429:
        base *= 3
    return min(base + random.uniform(0, CONFIG["retry_delay_sec"]), 30)


# ─── Global 429 circuit breaker ─────────────────────────────────────────────
# One request hitting a 429 means Gemini is already throttling us; letting
# every other in-flight/queued thread find that out independently (each on
# its own retry timer) just re-triggers the same wall repeatedly. Instead,
# the first thread to see a 429 posts a shared cooldown deadline that every
# other attempt waits out before it even tries the network.

_rate_limit_lock = threading.Lock()
_rate_limit_until = 0.0


def note_rate_limited(delay: float) -> None:
    global _rate_limit_until
    with _rate_limit_lock:
        _rate_limit_until = max(_rate_limit_until, time.time() + delay)


def wait_out_rate_limit() -> None:
    while True:
        with _rate_limit_lock:
            remaining = _rate_limit_until - time.time()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 5))


# ─── Anonymous session bootstrap ────────────────────────────────────────────
# Without a configured account cookie, requests otherwise carry zero session
# context: no cookie, no anti-CSRF `at`/SNlM0e token, nothing but a bare POST.
# That's a plausible source of 405s independent of `gemini_bl` drift. Scrape
# what a real anonymous browser tab would get for free from a single page
# load, and refresh it periodically / whenever a 405 suggests it's gone bad.

_anon_session = {"cookie": "", "xsrf": None, "mtime": 0.0}
_anon_session_lock = threading.Lock()
ANON_SESSION_TTL_SEC = 600

# ─── Models ──────────────────────────────────────────────────────────────────
# Mapping from JS source: MODE_CATEGORY enum (028-6eb337387583.js)
#   1=FAST, 2=THINKING, 3=PRO, 4=AUTO, 5=FAST_DYNAMIC_THINKING, 6=FLASH_LITE

MODELS = {
    "gemini-4-argon": {
        "mode": 1, "think": 4,
        "desc": "Alias for gemini-4-argon (backend upgraded)",
    },
    "gemini-3.7-flash": {
        "mode": 1, "think": 4,
        "desc": "Latest all-around model (Gemini 3.7 Flash, confirmed current default of the 'Flash' category as of 2026-08)",
    },
    "gemini-3.6-flash": {
        "mode": 1, "think": 4,
        "desc": "Alias for gemini-3.7-flash (backend upgraded)",
    },
    "gemini-3.5-flash": {
        "mode": 1, "think": 4,
        "desc": "Alias for gemini-3.7-flash (backend upgraded)",
    },
    "gemini-2.5-flash": {
        "mode": 1, "think": 4,
        "desc": "Gemini 2.5 Flash model",
    },
    "gemini-2.0-flash": {
        "mode": 1, "think": 4,
        "desc": "Gemini 2.0 Flash model",
    },
    "gemini-1.5-flash": {
        "mode": 1, "think": 4,
        "desc": "Gemini 1.5 Flash model",
    },
    "gemini-3.5-flash-thinking": {
        "mode": 2, "think": 0,
        "desc": "Deep thinking mode, longest output (~20k chars)",
    },
    "gemini-2.0-flash-thinking-exp": {
        "mode": 2, "think": 0,
        "desc": "Experimental thinking mode",
    },
    "gemini-3.1-pro": {
        "mode": 3, "think": 4,
        "desc": "Pro model (requires cookie for real routing)",
    },
    "gemini-1.5-pro": {
        "mode": 3, "think": 4,
        "desc": "Gemini 1.5 Pro model",
    },
    "gemini-3.1-pro-enhanced": {
        "mode": 3, "think": 4, "extra": {31: 2, 80: 3},
        "desc": "Pro with enhanced output (experimental)",
    },
    "gemini-auto": {
        "mode": 4, "think": 4,
        "desc": "Auto model selection",
    },
    "gemini-3.5-flash-thinking-lite": {
        "mode": 5, "think": 0,
        "desc": "Dynamic thinking with adaptive depth",
    },
    "gemini-flash-lite": {
        "mode": 6, "think": 4,
        "desc": "Lightweight fast model",
    },
    "imagen-3.0-generate-002": {
        "mode": 1, "think": 4, "is_image": True,
        "desc": "Imagen 3 Image Generation model",
    },
    "imagen-3": {
        "mode": 1, "think": 4, "is_image": True,
        "desc": "Alias for Imagen 3 Image Generation model",
    },
    "dall-e-3": {
        "mode": 1, "think": 4, "is_image": True,
        "desc": "OpenAI DALL-E 3 alias (routes to Imagen 3)",
    },
    "dall-e-2": {
        "mode": 1, "think": 4, "is_image": True,
        "desc": "OpenAI DALL-E 2 alias (routes to Imagen 3)",
    },
    "nano-banana-2": {
        "mode": 1, "think": 4, "is_image": True,
        "desc": "Nano Banana 2 (Gemini 3.1 Flash Image model)",
    },
    "nano_banana_2": {
        "mode": 1, "think": 4, "is_image": True,
        "desc": "Alias for nano-banana-2",
    },
    "nano-banana": {
        "mode": 1, "think": 4, "is_image": True,
        "desc": "Nano Banana Image Generation model",
    },
    "nano_banana": {
        "mode": 1, "think": 4, "is_image": True,
        "desc": "Alias for nano-banana",
    },
}


def resolve_model(model_name: str, default: str = "gemini-3.7-flash"):
    """Resolve model name to (name, mode_id, think_mode, error, extra_fields)."""
    if not model_name:
        model_name = default

    think_override = None
    if "@think=" in model_name:
        model_name, think_str = model_name.rsplit("@think=", 1)
        try:
            think_override = int(think_str)
        except ValueError:
            return None, None, None, f"Invalid think level: {think_str}", None

    cfg = MODELS.get(model_name)
    if not cfg:
        lower = model_name.lower()
        if any(k in lower for k in ("imagen", "dall-e", "image-gen", "image_gen")):
            matched = "imagen-3.0-generate-002"
        elif any(k in lower for k in ("nano", "banana")):
            matched = "nano-banana"
        elif "thinking" in lower or "think" in lower:
            matched = "gemini-3.5-flash-thinking"
        elif "pro" in lower:
            matched = "gemini-3.1-pro"
        elif "lite" in lower:
            matched = "gemini-flash-lite"
        elif "auto" in lower:
            matched = "gemini-auto"
        elif "flash" in lower:
            matched = "gemini-3.6-flash"
        else:
            matched = default

        log(f"Model '{model_name}' mapped to '{matched}'")
        model_name = matched
        cfg = MODELS[matched]

    mode_id = cfg["mode"]
    think_mode = think_override if think_override is not None else cfg["think"]
    extra = cfg.get("extra")
    return model_name, mode_id, think_mode, None, extra


# ─── Utilities ───────────────────────────────────────────────────────────────

def log(msg: str):
    if CONFIG["log_requests"]:
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        sys.stderr.flush()


def _parse_cookie_content(content: str) -> tuple:
    """Parse cookie content (JSON {"cookie":...,"sapisid":...} or a raw 'K=V; ...' string)."""
    content = content.strip()
    if content.startswith("{"):
        data = json.loads(content)
        cookie_str = data.get("cookie", "")
        sapisid = data.get("sapisid", "")
    else:
        cookie_str = content
        pairs = dict(p.split("=", 1) for p in cookie_str.split("; ") if "=" in p)
        sapisid = pairs.get("SAPISID", "")
    return cookie_str, sapisid if sapisid else None


def load_cookie() -> tuple:
    """Load cookie from file, falling back to the GEMINI_COOKIE env var. Returns (cookie_str, sapisid)."""
    cookie_file = CONFIG.get("cookie_file")
    if cookie_file and os.path.exists(cookie_file):
        try:
            with open(cookie_file, "r") as f:
                content = f.read()
            return _parse_cookie_content(content)
        except Exception as e:
            log(f"Cookie load error: {e}")
            return "", None

    env_cookie = os.environ.get("GEMINI_COOKIE")
    if env_cookie:
        try:
            cookie_str, sapisid = _parse_cookie_content(env_cookie)
            return cookie_str, os.environ.get("GEMINI_SAPISID") or sapisid
        except Exception as e:
            log(f"GEMINI_COOKIE env parse error: {e}")
            return "", None

    return "", None


def make_sapisidhash(sapisid: str) -> str:
    ts = int(time.time())
    h = hashlib.sha1(f"{ts} {sapisid} https://gemini.google.com".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{h}"


def account_prefix() -> str:
    """Return the Gemini account path prefix for non-default Google accounts."""
    auth_user = CONFIG.get("auth_user")
    if auth_user is None or auth_user == "":
        return ""
    return f"/u/{auth_user}"


def apply_chat_persistence_flags(inner: list) -> None:
    """Apply Gemini Web persistence flags to an outgoing request payload."""
    if CONFIG.get("temporary_chats", False):
        inner[41] = [1]
        inner[45] = 1
    else:
        inner[41] = [2]


def fetch_anon_session() -> dict:
    """GET gemini.google.com/app anonymously and scrape the build label
    (bl), the anti-CSRF token (SNlM0e), and whatever session cookies Google
    hands a fresh anonymous visitor."""
    result = {"bl": None, "xsrf": None, "cookie": ""}
    try:
        req = urllib.request.Request(
            "https://gemini.google.com/app",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        ctx = ssl.create_default_context()
        proxy = CONFIG.get("proxy")
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
                urllib.request.HTTPSHandler(context=ctx))
            resp = opener.open(req, timeout=15)
        else:
            resp = urllib.request.urlopen(req, context=ctx, timeout=15)
        html = resp.read().decode("utf-8", errors="replace")

        m = re.search(r'(boq_assistant-bard-web-server_\d+\.\d+_p\d+)', html)
        if m:
            result["bl"] = m.group(1)

        m = re.search(r'"SNlM0e":"([^"]+)"', html)
        if m:
            result["xsrf"] = m.group(1)

        cookies = [raw.split(";", 1)[0] for raw in (resp.headers.get_all("Set-Cookie") or [])]
        if cookies:
            result["cookie"] = "; ".join(cookies)
    except Exception as e:
        log(f"Anon session fetch failed: {e}")
    return result


def _refresh_anon_session_locked() -> None:
    """Caller must hold _anon_session_lock."""
    fresh = fetch_anon_session()
    if fresh["bl"]:
        CONFIG["gemini_bl"] = fresh["bl"]
    if fresh["xsrf"]:
        _anon_session["xsrf"] = fresh["xsrf"]
    if fresh["cookie"]:
        _anon_session["cookie"] = fresh["cookie"]
    _anon_session["mtime"] = time.time()
    log(f"Anon session refreshed (bl={CONFIG['gemini_bl']}, "
        f"xsrf={'yes' if _anon_session['xsrf'] else 'no'}, "
        f"cookie={'yes' if _anon_session['cookie'] else 'no'})")


def get_anon_session(force: bool = False) -> dict:
    """Cached anonymous session (bl/xsrf/cookie), refreshed on a TTL or when forced."""
    with _anon_session_lock:
        if force or time.time() - _anon_session["mtime"] > ANON_SESSION_TTL_SEC:
            _refresh_anon_session_locked()
        return dict(_anon_session)


def refresh_session_if_needed() -> bool:
    """Force-refresh after a 405: bl always, plus (without a configured
    account cookie) the anonymous cookie/xsrf those requests still need.
    Returns True if anything actually changed."""
    before = (CONFIG["gemini_bl"], _anon_session["xsrf"], _anon_session["cookie"])
    get_anon_session(force=True)
    after = (CONFIG["gemini_bl"], _anon_session["xsrf"], _anon_session["cookie"])
    return before != after


def load_session() -> tuple:
    """Returns (cookie_str, sapisid, xsrf_token) for outgoing StreamGenerate
    calls: an explicitly configured account cookie/xsrf_token when present,
    otherwise a scraped anonymous session (cookie + SNlM0e) as a fallback so
    anonymous requests aren't sent with zero session context at all."""
    cookie_file = CONFIG.get("cookie_file")
    if cookie_file and os.path.exists(cookie_file):
        try:
            with open(cookie_file, "r") as f:
                content = f.read()
            cookie_str, sapisid = _parse_cookie_content(content)
            return cookie_str, sapisid, CONFIG.get("xsrf_token")
        except Exception as e:
            log(f"Cookie load error: {e}")
            return "", None, CONFIG.get("xsrf_token")

    env_cookie = os.environ.get("GEMINI_COOKIE")
    if env_cookie:
        try:
            cookie_str, sapisid = _parse_cookie_content(env_cookie)
            return cookie_str, os.environ.get("GEMINI_SAPISID") or sapisid, CONFIG.get("xsrf_token")
        except Exception as e:
            log(f"GEMINI_COOKIE env parse error: {e}")
            return "", None, CONFIG.get("xsrf_token")

    anon = get_anon_session()
    return anon["cookie"], None, CONFIG.get("xsrf_token") or anon["xsrf"]


# ─── Gemini Protocol ─────────────────────────────────────────────────────────

def gemini_stream_generate(prompt: str, model_id: int, think_mode: int) -> str:
    """Send prompt to Gemini StreamGenerate with retry. The upstream semaphore
    is only held around each individual network attempt (not across the
    backoff sleep between attempts), so one slow-to-recover request doesn't
    block the whole queue behind it."""
    inner = [None] * 80
    inner[0] = [prompt, 0, None, None, None, None, 0]
    inner[1] = ["en"]
    inner[2] = ["", "", "", None, None, None, None, None, None, ""]
    inner[6] = [0]
    inner[7] = 1
    inner[10] = 1
    inner[11] = 0
    inner[17] = [[think_mode]]
    inner[18] = 0
    inner[27] = 1
    inner[30] = [4]
    apply_chat_persistence_flags(inner)
    inner[53] = 0
    inner[59] = str(uuid.uuid4())
    inner[61] = []
    inner[68] = 1
    inner[79] = model_id

    outer = [None, json.dumps(inner)]
    params = {"f.req": json.dumps(outer)}
    prefix = account_prefix()

    last_err = None
    for attempt in range(CONFIG["retry_attempts"]):
        wait_out_rate_limit()
        cookie_str, sapisid, xsrf = load_session()
        req_params = dict(params)
        if xsrf:
            req_params["at"] = xsrf
        body = urllib.parse.urlencode(req_params).encode()
        reqid = next_reqid()
        url = (
            f"https://gemini.google.com{prefix}/_/BardChatUi/data/"
            "assistant.lamda.BardFrontendService/StreamGenerate"
            f"?bl={CONFIG['gemini_bl']}&hl=en&_reqid={reqid}&rt=c"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://gemini.google.com",
            "Referer": f"https://gemini.google.com{prefix}/app",
            "X-Same-Domain": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if prefix:
            headers["X-Goog-AuthUser"] = str(CONFIG["auth_user"])
        if cookie_str:
            headers["Cookie"] = cookie_str
        if sapisid:
            headers["Authorization"] = make_sapisidhash(sapisid)

        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            ctx = ssl.create_default_context()
            proxy = CONFIG.get("proxy")
            with _upstream_semaphore:
                if proxy:
                    opener = urllib.request.build_opener(
                        urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
                        urllib.request.HTTPSHandler(context=ctx)
                    )
                    resp = opener.open(req, timeout=CONFIG["request_timeout_sec"])
                else:
                    resp = urllib.request.urlopen(req, context=ctx, timeout=CONFIG["request_timeout_sec"])
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                note_rate_limited(retry_sleep_sec(attempt, e))
            if e.code == 405 and refresh_session_if_needed():
                log("Retrying with refreshed session...")
                continue
            if attempt < CONFIG["retry_attempts"] - 1:
                delay = retry_sleep_sec(attempt, e)
                log(f"Retry {attempt+1}/{CONFIG['retry_attempts']}: HTTP Error {e.code}: {e.reason} (waiting {delay:.1f}s)")
                time.sleep(delay)
        except Exception as e:
            last_err = e
            if attempt < CONFIG["retry_attempts"] - 1:
                delay = retry_sleep_sec(attempt, e)
                log(f"Retry {attempt+1}/{CONFIG['retry_attempts']}: {e} (waiting {delay:.1f}s)")
                time.sleep(delay)
    raise last_err


def gemini_stream_generate_iter(prompt: str, model_id: int, think_mode: int):
    """Send prompt and yield incremental text deltas using httpx streaming."""
    inner = [None] * 80
    inner[0] = [prompt, 0, None, None, None, None, 0]
    inner[1] = ["en"]
    inner[2] = ["", "", "", None, None, None, None, None, None, ""]
    inner[6] = [0]
    inner[7] = 1
    inner[10] = 1
    inner[11] = 0
    inner[17] = [[think_mode]]
    inner[18] = 0
    inner[27] = 1
    inner[30] = [4]
    apply_chat_persistence_flags(inner)
    inner[53] = 0
    inner[59] = str(uuid.uuid4())
    inner[61] = []
    inner[68] = 1
    inner[79] = model_id

    outer = [None, json.dumps(inner)]
    params = {"f.req": json.dumps(outer)}
    prefix = account_prefix()
    proxy = CONFIG.get("proxy")

    if not HAS_HTTPX:
        # Fallback: non-streaming with urllib
        raw = gemini_stream_generate(prompt, model_id, think_mode)
        text = extract_response_text(raw)
        if text:
            yield text
        return

    last_err = None
    for attempt in range(CONFIG["retry_attempts"]):
        wait_out_rate_limit()
        cookie_str, sapisid, xsrf = load_session()
        req_params = dict(params)
        if xsrf:
            req_params["at"] = xsrf
        body = urllib.parse.urlencode(req_params)
        reqid = next_reqid()
        url = (
            f"https://gemini.google.com{prefix}/_/BardChatUi/data/"
            "assistant.lamda.BardFrontendService/StreamGenerate"
            f"?bl={CONFIG['gemini_bl']}&hl=en&_reqid={reqid}&rt=c"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://gemini.google.com",
            "Referer": f"https://gemini.google.com{prefix}/app",
            "X-Same-Domain": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if prefix:
            headers["X-Goog-AuthUser"] = str(CONFIG["auth_user"])
        if cookie_str:
            headers["Cookie"] = cookie_str
        if sapisid:
            headers["Authorization"] = make_sapisidhash(sapisid)

        prev_text = ""
        transport = httpx.HTTPTransport(proxy=proxy) if proxy else None
        try:
            with _upstream_semaphore:
                with httpx.Client(transport=transport, timeout=CONFIG["request_timeout_sec"], verify=True) as client:
                    with client.stream("POST", url, content=body, headers=headers) as resp:
                        resp.raise_for_status()
                        buf = ""
                        for chunk in resp.iter_text():
                            buf += chunk
                            if "BardErrorInfo" in buf:
                                import re as _re
                                m = _re.search(r'BardErrorInfo["\s,]*\[(\d+)\]', buf)
                                if m:
                                    raise RuntimeError(f"Gemini upstream rejected request: BardErrorInfo [{m.group(1)}]")
                            while "\n" in buf:
                                line, buf = buf.split("\n", 1)
                                if '"wrb.fr"' not in line or len(line) < 200:
                                    continue
                                try:
                                    arr = json.loads(line)
                                    inner_str = arr[0][2]
                                    if not inner_str or len(inner_str) < 50:
                                        continue
                                    inner2 = json.loads(inner_str)
                                    if isinstance(inner2, list) and len(inner2) > 4 and inner2[4]:
                                        for part in inner2[4]:
                                            if isinstance(part, list) and len(part) > 1 and part[1] and isinstance(part[1], list):
                                                for t in part[1]:
                                                    if isinstance(t, str) and len(t) > len(prev_text):
                                                        delta = t[len(prev_text):]
                                                        delta = clean_gemini_text(delta, strip=False)
                                                        if delta:
                                                            yield delta
                                                        prev_text = t
                                except (json.JSONDecodeError, IndexError, TypeError):
                                    pass
            return
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 405 and refresh_session_if_needed():
                log("Session refreshed, falling back to non-streaming for this request")
                raw = gemini_stream_generate(prompt, model_id, think_mode)
                text = extract_response_text(raw)
                if text:
                    yield text
                return
            if prev_text:
                # Already streamed partial content to the client; retrying
                # would duplicate or garble it, so surface the error instead.
                raise
            last_err = e
            delay = retry_sleep_sec(attempt, e)
            if status == 429:
                note_rate_limited(delay)
            if attempt < CONFIG["retry_attempts"] - 1:
                log(f"Stream retry {attempt+1}/{CONFIG['retry_attempts']}: {e} (waiting {delay:.1f}s)")
                time.sleep(delay)
    raise last_err


def clean_gemini_text(text: str, strip: bool = True) -> str:
    """Remove internal code execution artifacts."""
    text = re.sub(
        r'```(?:python|javascript|text)\?code_(?:reference|stdout)&code_event_index=\d+\n.*?```\n?',
        '', text, flags=re.DOTALL
    )
    return text.strip() if strip else text


def extract_image_urls_from_raw(raw: str) -> list:
    """Extract generated image URLs (googleusercontent.com) from raw response."""
    urls = []
    pattern = r'https?://[a-zA-Z0-9\.\-]+googleusercontent\.com/[^\s"\'\]\)\}\\\>]+'
    seen = set()
    for match in re.finditer(pattern, raw):
        url = match.group(0)
        if any(ign in url for ign in ("fonts.gstatic", "default_avatar", "24px.svg")):
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def extract_response_text_and_images(raw: str) -> tuple:
    """Parse StreamGenerate response to get (final_text, list_of_image_urls)."""
    import re as _re
    bard_err = _re.search(r'BardErrorInfo["\s,]*\[(\d+)\]', raw)
    if bard_err:
        raise RuntimeError(f"Gemini upstream rejected request: BardErrorInfo [{bard_err.group(1)}]")
    texts = []
    for line in raw.split("\n"):
        if '"wrb.fr"' not in line or len(line) < 200:
            continue
        try:
            arr = json.loads(line)
            inner_str = arr[0][2]
            if not inner_str or len(inner_str) < 50:
                continue
            inner = json.loads(inner_str)
            if isinstance(inner, list) and len(inner) > 4 and inner[4]:
                for part in inner[4]:
                    if isinstance(part, list) and len(part) > 1 and part[1]:
                        if isinstance(part[1], list):
                            for t in part[1]:
                                if isinstance(t, str) and len(t) > 0:
                                    texts.append(t)
        except (json.JSONDecodeError, IndexError, TypeError):
            pass
    text = ""
    for t in reversed(texts):
        if t.strip():
            text = t
            break
    text = clean_gemini_text(text)
    image_urls = extract_image_urls_from_raw(raw)

    if image_urls:
        missing_imgs = [url for url in image_urls if url not in text]
        if missing_imgs:
            img_md = "\n\n" + "\n".join(f"![Generated Image]({url})" for url in missing_imgs)
            text += img_md

    return text, image_urls


def extract_response_text(raw: str) -> str:
    """Parse StreamGenerate response to extract final text."""
    text, _ = extract_response_text_and_images(raw)
    return text


def generate_with_images(prompt: str, model_id: int, think_mode: int) -> tuple:
    """Send prompt and return (text, image_urls)."""
    raw = gemini_stream_generate(prompt, model_id, think_mode)
    return extract_response_text_and_images(raw)



# ─── OpenAI Format Helpers ───────────────────────────────────────────────────

def messages_to_prompt(messages: list, tools: list = None) -> str:
    """Convert OpenAI messages to prompt string."""
    parts = []
    if tools:
        tool_defs = []
        for tool in tools:
            fn = tool.get("function", tool) if tool.get("type") == "function" else tool
            tool_defs.append({
                "name": fn.get("name", tool.get("name", "")),
                "description": fn.get("description", tool.get("description", "")),
                "parameters": fn.get("parameters", tool.get("parameters", {})),
            })
        if tool_defs:
            # Natural, non-"[System instruction]"-prefixed framing — the old
            # injection-style wording (fake system-instruction header + fenced
            # command block + raw JSON dump) tends to get flagged and rejected
            # by Gemini's web backend as BardErrorInfo on large/complex tool
            # sets. Mirrors duacincin/tools.py's build_tool_prompt, which
            # was already written for this reason but never wired into this
            # endpoint. Keeps the tool_call/arguments format so parse_tool_calls
            # below doesn't need to change.
            parts.append(
                "# Tool Use\n\n"
                "You can call the following tools to help accomplish tasks. "
                "These tools connect to the user's local environment and will "
                "execute when called.\n\n"
                "Call format (use this exact format):\n"
                '```tool_call\n{"name": "<tool_name>", "arguments": {<arguments>}}\n```\n\n'
                "When calling tools:\n"
                "- Output ONLY the tool_call block(s), nothing else\n"
                "- You may call multiple tools with multiple blocks\n"
                "- After receiving a [Tool result for ...], use that data to answer the user\n\n"
                f"Available tools:\n{json.dumps(tool_defs, indent=2, ensure_ascii=False)}"
            )
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content
                if c.get("type") in ("text", "input_text")
            )
        if role == "system":
            parts.append(f"[System instruction]: {content}")
        elif role == "assistant":
            if msg.get("tool_calls"):
                tc_strs = []
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    tc_strs.append(
                        f'```tool_call\n{{"name": "{fn.get("name")}", '
                        f'"arguments": {fn.get("arguments", "{}")}}}\n```'
                    )
                parts.append(f"[Assistant]: {content or ''}\n" + "\n".join(tc_strs))
            else:
                parts.append(f"[Assistant]: {content}")
        elif role == "tool":
            parts.append(f"[Tool result for {msg.get('name', '')}]: {content}")
        else:
            parts.append(content if content else "")
    return "\n\n".join(p for p in parts if p)


def parse_tool_calls(text: str) -> tuple:
    """Extract tool_call blocks. Returns (clean_text, tool_calls_list)."""
    tool_calls = []
    pattern = r'```tool_call\s*\n(.*?)\n```'
    for match in re.findall(pattern, text, re.DOTALL):
        try:
            data = json.loads(match.strip())
            tool_calls.append({
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": data["name"],
                    "arguments": json.dumps(data.get("arguments", {}), ensure_ascii=False),
                },
            })
        except (json.JSONDecodeError, KeyError):
            pass
    clean = re.sub(pattern, '', text, flags=re.DOTALL).strip()
    return clean, tool_calls


# ─── OpenAPI / API Docs ──────────────────────────────────────────────────────

def build_openapi_spec() -> dict:
    """Build an OpenAPI 3.0 spec describing every endpoint, served at /openapi.json
    and rendered as interactive, testable docs at /docs (Swagger UI)."""
    model_ids = list(MODELS.keys())

    error_schema = {
        "type": "object",
        "properties": {
            "error": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
            }
        },
    }
    chat_message_schema = {
        "type": "object",
        "required": ["role", "content"],
        "properties": {
            "role": {"type": "string", "enum": ["system", "user", "assistant", "tool"]},
            "content": {"type": "string"},
        },
    }
    chat_request_schema = {
        "type": "object",
        "required": ["messages"],
        "properties": {
            "model": {
                "type": "string",
                "description": "Model id. Append `@think=N` (0=deepest..4=shallowest) to override thinking depth.",
                "enum": model_ids,
                "default": "gemini-3.5-flash",
            },
            "messages": {"type": "array", "items": chat_message_schema},
            "stream": {"type": "boolean", "default": False, "description": "Server-Sent Events streaming."},
            "tools": {"type": "array", "items": {"type": "object"}, "description": "OpenAI-style function tool definitions."},
            "tool_choice": {"description": "\"auto\", \"none\", or a specific tool object.", "default": "auto"},
        },
        "example": {
            "model": "gemini-3.5-flash",
            "messages": [{"role": "user", "content": "Hello!"}],
        },
    }
    chat_response_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "object": {"type": "string", "example": "chat.completion"},
            "created": {"type": "integer"},
            "model": {"type": "string"},
            "choices": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "message": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string"},
                                "content": {"type": "string", "nullable": True},
                                "tool_calls": {"type": "array", "items": {"type": "object"}},
                            },
                        },
                        "finish_reason": {"type": "string"},
                    },
                },
            },
            "usage": {
                "type": "object",
                "properties": {
                    "prompt_tokens": {"type": "integer"},
                    "completion_tokens": {"type": "integer"},
                    "total_tokens": {"type": "integer"},
                },
            },
        },
    }
    image_request_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "model": {"type": "string", "default": "imagen-3.0-generate-002", "enum": [m for m in model_ids if MODELS[m].get("is_image")]},
            "prompt": {"type": "string"},
            "response_format": {"type": "string", "enum": ["url", "b64_json"], "default": "url"},
        },
        "example": {
            "model": "imagen-3.0-generate-002",
            "prompt": "A beautiful sunset over snowy mountains",
        },
    }
    image_response_schema = {
        "type": "object",
        "properties": {
            "created": {"type": "integer"},
            "data": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}, "b64_json": {"type": "string"}},
                },
            },
        },
    }
    models_list_schema = {
        "type": "object",
        "properties": {
            "object": {"type": "string", "example": "list"},
            "data": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "object": {"type": "string"},
                        "created": {"type": "integer"},
                        "owned_by": {"type": "string"},
                        "description": {"type": "string"},
                    },
                },
            },
        },
    }
    responses_request_schema = {
        "type": "object",
        "properties": {
            "model": {"type": "string", "enum": model_ids, "default": "gemini-3.5-flash"},
            "input": {"description": "A string, or an array of Responses-API input items.", "example": "Hello!"},
            "instructions": {"type": "string"},
            "tools": {"type": "array", "items": {"type": "object"}},
            "tool_choice": {"default": "auto"},
            "stream": {"type": "boolean", "default": False},
        },
        "example": {"model": "gemini-3.5-flash", "input": "Hello!"},
    }
    responses_response_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "object": {"type": "string", "example": "response"},
            "created_at": {"type": "integer"},
            "status": {"type": "string"},
            "model": {"type": "string"},
            "output": {"type": "array", "items": {"type": "object"}},
            "usage": {"type": "object"},
        },
    }
    google_models_list_schema = {
        "type": "object",
        "properties": {
            "models": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "displayName": {"type": "string"},
                        "description": {"type": "string"},
                        "supportedGenerationMethods": {"type": "array", "items": {"type": "string"}},
                    },
                },
            }
        },
    }
    google_generate_request_schema = {
        "type": "object",
        "required": ["contents"],
        "properties": {
            "contents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "parts": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}}}},
                    },
                },
            },
            "tools": {"type": "array", "items": {"type": "object"}},
            "toolConfig": {"type": "object"},
        },
        "example": {"contents": [{"role": "user", "parts": [{"text": "Hello!"}]}]},
    }
    google_generate_response_schema = {
        "type": "object",
        "properties": {
            "candidates": {"type": "array", "items": {"type": "object"}},
            "usageMetadata": {"type": "object"},
            "modelVersion": {"type": "string"},
        },
    }

    def json_body(schema):
        return {"content": {"application/json": {"schema": schema}}}

    def json_response(desc, schema):
        return {"description": desc, "content": {"application/json": {"schema": schema}}}

    error_response = json_response("Error", error_schema)
    auth_security = [{"bearerAuth": []}, {"apiKeyHeader": []}]

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "DuaCincin",
            "version": __version__,
        },
        "servers": [{"url": "/", "description": "This server"}],
        "tags": [
            {"name": "OpenAI-compatible", "description": "Drop-in replacement for the OpenAI API."},
            {"name": "Codex CLI", "description": "OpenAI Responses API, used by OpenAI Codex CLI."},
            {"name": "Gemini CLI", "description": "Google's native Generative Language API shape."},
            {"name": "Meta", "description": "Health and status."},
        ],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "description": "`Authorization: Bearer <key>` (only enforced if `api_keys` is set in config)."},
                "apiKeyHeader": {"type": "apiKey", "in": "header", "name": "x-api-key", "description": "Alternative to Bearer auth."},
            },
            "schemas": {
                "Error": error_schema,
                "ChatCompletionRequest": chat_request_schema,
                "ChatCompletionResponse": chat_response_schema,
                "ImageGenerationRequest": image_request_schema,
                "ImageGenerationResponse": image_response_schema,
                "ModelsListResponse": models_list_schema,
                "ResponsesRequest": responses_request_schema,
                "ResponsesResponse": responses_response_schema,
                "GoogleModelsListResponse": google_models_list_schema,
                "GoogleGenerateContentRequest": google_generate_request_schema,
                "GoogleGenerateContentResponse": google_generate_response_schema,
            },
        },
        "paths": {
            "/": {
                "get": {
                    "tags": ["Meta"],
                    "summary": "Health check",
                    "responses": {"200": json_response("Server status", {"type": "object", "properties": {
                        "status": {"type": "string"}, "version": {"type": "string"}, "models": {"type": "array", "items": {"type": "string"}}}})},
                }
            },
            "/v1/models": {
                "get": {
                    "tags": ["OpenAI-compatible"],
                    "summary": "List available models",
                    "security": auth_security,
                    "responses": {"200": json_response("List of models", models_list_schema)},
                }
            },
            "/v1/chat/completions": {
                "post": {
                    "tags": ["OpenAI-compatible"],
                    "summary": "Chat completion",
                    "description": "OpenAI-compatible chat completions endpoint. Supports streaming (SSE) and function/tool calling.",
                    "security": auth_security,
                    "requestBody": {"required": True, **json_body(chat_request_schema)},
                    "responses": {
                        "200": json_response("Chat completion (or SSE stream when `stream: true`)", chat_response_schema),
                        "400": error_response,
                        "401": error_response,
                        "502": error_response,
                    },
                }
            },
            "/v1/images/generations": {
                "post": {
                    "tags": ["OpenAI-compatible"],
                    "summary": "Image generation",
                    "description": "OpenAI-compatible image generation, powered by Imagen 3. Requires a configured Google account cookie (`cookie_file`).",
                    "security": auth_security,
                    "requestBody": {"required": True, **json_body(image_request_schema)},
                    "responses": {
                        "200": json_response("Generated image(s)", image_response_schema),
                        "400": error_response,
                        "401": error_response,
                        "502": error_response,
                    },
                }
            },
            "/v1/responses": {
                "post": {
                    "tags": ["Codex CLI"],
                    "summary": "Responses API",
                    "description": "OpenAI Responses API shape, for OpenAI Codex CLI integration.",
                    "security": auth_security,
                    "requestBody": {"required": True, **json_body(responses_request_schema)},
                    "responses": {
                        "200": json_response("Response object (or SSE stream when `stream: true`)", responses_response_schema),
                        "400": error_response,
                        "401": error_response,
                        "502": error_response,
                    },
                }
            },
            "/v1beta/models": {
                "get": {
                    "tags": ["Gemini CLI"],
                    "summary": "List models (Google native shape)",
                    "security": auth_security,
                    "responses": {"200": json_response("List of models", google_models_list_schema)},
                }
            },
            "/v1beta/models/{model}:generateContent": {
                "post": {
                    "tags": ["Gemini CLI"],
                    "summary": "Generate content (non-streaming)",
                    "description": "Google Generative Language API compatible endpoint, used by Gemini CLI.",
                    "security": auth_security,
                    "parameters": [{"name": "model", "in": "path", "required": True, "schema": {"type": "string", "enum": model_ids}}],
                    "requestBody": {"required": True, **json_body(google_generate_request_schema)},
                    "responses": {
                        "200": json_response("Generated content", google_generate_response_schema),
                        "400": error_response,
                        "401": error_response,
                        "502": error_response,
                    },
                }
            },
            "/v1beta/models/{model}:streamGenerateContent": {
                "post": {
                    "tags": ["Gemini CLI"],
                    "summary": "Generate content (streaming, SSE)",
                    "description": "Google Generative Language API compatible streaming endpoint, used by Gemini CLI.",
                    "security": auth_security,
                    "parameters": [{"name": "model", "in": "path", "required": True, "schema": {"type": "string", "enum": model_ids}}],
                    "requestBody": {"required": True, **json_body(google_generate_request_schema)},
                    "responses": {
                        "200": json_response("SSE stream of generated content chunks", google_generate_response_schema),
                        "400": error_response,
                        "401": error_response,
                        "502": error_response,
                    },
                }
            },
        },
    }


DOCS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>DuaCincin &mdash; API Docs (Swagger UI)</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>body { margin: 0; background: #fafafa; }</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    window.onload = function() {
      window.ui = SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: "#swagger-ui",
        presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
        layout: "StandaloneLayout",
        deepLinking: true,
        tryItOutEnabled: true,
      });
    };
  </script>
</body>
</html>
"""

# ─── HTTP Handler ────────────────────────────────────────────────────────────

class GeminiHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        client_ip = self.client_address[0] if self.client_address else "-"
        log(f"{client_ip} {fmt % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parse_body(self, body: bytes) -> dict:
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return None

    def _extract_requested_model(self, req: dict = None, default: str = None) -> str:
        """Extract model selection from JSON body, headers, or query parameters."""
        if default is None:
            default = CONFIG["default_model"]
        if req and isinstance(req, dict) and req.get("model"):
            return req["model"]
        for h in ("x-gemini-model", "x-model"):
            val = self.headers.get(h)
            if val:
                return val.strip()
        if "?" in self.path:
            for pair in self.path.split("?", 1)[1].split("&"):
                if pair.startswith("model=") and pair[6:]:
                    return urllib.parse.unquote(pair[6:])
        return default

    def _authorized(self):
        keys = CONFIG.get("api_keys") or []
        if not keys:
            return True
        auth = self.headers.get("Authorization", "").strip()
        if auth.startswith("Bearer ") and auth[7:].strip() in keys:
            return True
        for h in ("x-api-key", "x-goog-api-key"):
            val = self.headers.get(h, "").strip()
            if val and val in keys:
                return True
        if "?" in self.path:
            for pair in self.path.split("?", 1)[1].split("&"):
                if pair.startswith("key=") and pair[4:].strip() in keys:
                    return True
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        try:
            if self.path.startswith("/v1") and not self._authorized():
                self.send_json({"error": {"message": "invalid api key"}}, 401)
                return
            if self.path == "/v1/models":
                self.send_json({"object": "list", "data": [
                    {"id": n, "object": "model", "created": 1700000000,
                     "owned_by": "google", "description": c["desc"]}
                    for n, c in MODELS.items()
                ]})
            elif self.path.startswith("/v1beta/models"):
                self._handle_google_models_list()
            elif self.path == "/openapi.json":
                self.send_json(build_openapi_spec())
            elif self.path == "/docs":
                self.send_html(DOCS_HTML)
            elif self.path == "/":
                self.send_json({"status": "ok", "version": __version__,
                                "models": list(MODELS.keys())})
            else:
                self.send_json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"GET error: {e}")

    def do_POST(self):
        try:
            if self.path.startswith("/v1") and not self._authorized():
                self.send_json({"error": {"message": "invalid api key"}}, 401)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            if self.path == "/v1/chat/completions":
                self.handle_chat(body)
            elif self.path == "/v1/responses":
                self.handle_responses(body)
            elif self.path == "/v1/images/generations":
                self._handle_images_generations(body)
            elif ":generateContent" in self.path:
                self._handle_google_generate(body, stream=False)
            elif ":streamGenerateContent" in self.path:
                self._handle_google_generate(body, stream=True)
            else:
                self.send_json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"POST error: {e}")
            try:
                self.send_json({"error": {"message": str(e)}}, 500)
            except:
                pass

    def _handle_images_generations(self, body: bytes):
        req = self._parse_body(body)
        if req is None:
            self.send_json({"error": {"message": "invalid JSON"}}, 400)
            return

        prompt = req.get("prompt", "")
        if not prompt or not prompt.strip():
            self.send_json({"error": {"message": "empty prompt"}}, 400)
            return

        cookie_str, _ = load_cookie()
        if not cookie_str:
            self.send_json({
                "error": {
                    "message": "Gemini image generation requires a valid Google cookie. Please configure 'cookie_file' in config.json."
                }
            }, 400)
            return

        model_input = self._extract_requested_model(req, default="imagen-3.0-generate-002")
        model_name, model_id, think_mode, err, extra_fields = resolve_model(model_input, default="imagen-3.0-generate-002")
        if err:
            self.send_json({"error": {"message": err}}, 400)
            return

        gen_prompt = prompt if any(k in prompt.lower() for k in ("generate", "draw", "create", "image")) else f"Generate an image: {prompt}"

        try:
            text, image_urls = generate_with_images(gen_prompt, model_id, think_mode)
        except Exception as e:
            self.send_json({"error": {"message": f"upstream error: {e}"}}, 502)
            return

        if not image_urls:
            msg = text if text else "Gemini failed to generate an image."
            self.send_json({"error": {"message": msg}}, 400)
            return

        data_items = [{"url": url} for url in image_urls]
        self.send_json({
            "created": int(time.time()),
            "data": data_items
        })

    def _call_gemini(self, prompt, model_id, think_mode, tools):
        # extract_response_text raises RuntimeError on BardErrorInfo *after* a
        # 200 OK response — gemini_stream_generate's own retry loop never sees
        # this class of failure, so it was previously never retried at all.
        # Each retry re-runs gemini_stream_generate too, so it goes out with a
        # fresh reqid/session state, not a resend of the identical request.
        last_err = None
        for attempt in range(CONFIG["retry_attempts"]):
            raw = gemini_stream_generate(prompt, model_id, think_mode)
            try:
                text = extract_response_text(raw)
            except RuntimeError as e:
                last_err = e
                if "BardErrorInfo" in str(e) and attempt < CONFIG["retry_attempts"] - 1:
                    delay = retry_sleep_sec(attempt, e)
                    log(f"Retry {attempt+1}/{CONFIG['retry_attempts']}: {e} (waiting {delay:.1f}s)")
                    time.sleep(delay)
                    continue
                raise
            tool_calls = None
            if tools and text:
                text, tool_calls = parse_tool_calls(text)
            return text or "", tool_calls
        raise last_err

    def handle_chat(self, body: bytes):
        req = self._parse_body(body) or {}
        model_input = self._extract_requested_model(req)
        model_name, model_id, think_mode, err, extra_fields = resolve_model(model_input)
        if err:
            self.send_json({"error": {"message": err}}, 400)
            return

        tools = req.get("tools")
        prompt = messages_to_prompt(req.get("messages", []), tools)
        if not prompt.strip():
            self.send_json({"error": {"message": "empty prompt"}}, 400)
            return

        stream = req.get("stream", False)
        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        if stream and not tools:
            # True streaming: forward chunks as they arrive
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                first_chunk = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                               "model": model_name, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(first_chunk)}\n\n".encode())
                for delta_text in gemini_stream_generate_iter(prompt, model_id, think_mode):
                    chunk = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                             "model": model_name, "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}]}
                    self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                # Final chunk
                chunk = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                         "model": model_name, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                log(f"Stream error: {e}")
            return

        # Non-streaming (or tool calling which needs full response)
        try:
            text, tool_calls = self._call_gemini(prompt, model_id, think_mode, tools)
        except Exception as e:
            self.send_json({"error": {"message": f"upstream error: {e}"}}, 502)
            return

        msg = {"role": "assistant", "content": text or None}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        finish = "tool_calls" if tool_calls else "stop"

        if stream:
            # Stream mode with tools: send as single chunk (need full parse for tool_calls)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            chunk = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                     "model": model_name, "choices": [{"index": 0, "delta": msg, "finish_reason": finish}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self.send_json({
                "id": cid, "object": "chat.completion", "created": int(time.time()),
                "model": model_name,
                "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                "usage": {"prompt_tokens": len(prompt)//4, "completion_tokens": len(text)//4,
                          "total_tokens": (len(prompt)+len(text))//4},
            })

    def handle_responses(self, body: bytes):
        """OpenAI Responses API for Codex CLI compatibility."""
        req = self._parse_body(body) or {}
        model_input = self._extract_requested_model(req)
        model_name, model_id, think_mode, err, extra_fields = resolve_model(model_input)
        if err:
            self.send_json({"error": {"message": err}}, 400)
            return

        input_items = req.get("input", [])
        tools = req.get("tools")

        messages = []
        if req.get("instructions"):
            messages.append({"role": "system", "content": req["instructions"]})
        if isinstance(input_items, str):
            messages.append({"role": "user", "content": input_items})
        elif isinstance(input_items, list):
            for item in input_items:
                if isinstance(item, str):
                    messages.append({"role": "user", "content": item})
                elif isinstance(item, dict):
                    if item.get("type") == "function_call_output":
                        messages.append({"role": "tool", "tool_call_id": item.get("call_id", ""),
                                         "name": item.get("name", ""), "content": item.get("output", "")})
                    elif item.get("role") == "assistant" or (item.get("type") == "message" and item.get("role") == "assistant"):
                        cp = item.get("content", [])
                        text_acc, tc_list = "", []
                        if isinstance(cp, list):
                            for c in cp:
                                if isinstance(c, dict):
                                    if c.get("type") == "output_text": text_acc += c.get("text", "")
                                    elif c.get("type") == "function_call": tc_list.append(c)
                        elif isinstance(cp, str):
                            text_acc = cp
                        m = {"role": "assistant", "content": text_acc or None}
                        if tc_list:
                            m["tool_calls"] = [{"id": tc.get("call_id", f"call_{i}"), "type": "function",
                                                "function": {"name": tc.get("name",""), "arguments": tc.get("arguments","{}")}}
                                               for i, tc in enumerate(tc_list)]
                        messages.append(m)
                    else:
                        role = item.get("role", "user")
                        content = item.get("content", "")
                        if isinstance(content, list):
                            content = " ".join(c.get("text", "") for c in content if c.get("type") in ("text", "input_text"))
                        messages.append({"role": role, "content": content})

        if tools:
            tools = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t.get("parameters", {})}}
                     if t.get("type") == "function" and "function" not in t else t for t in tools]

        prompt = messages_to_prompt(messages, tools)
        if not prompt.strip():
            self.send_json({"error": {"message": "empty input"}}, 400)
            return

        try:
            text, tool_calls = self._call_gemini(prompt, model_id, think_mode, tools)
        except Exception as e:
            self.send_json({"error": {"message": f"upstream error: {e}"}}, 502)
            return

        rid = f"resp_{uuid.uuid4().hex[:16]}"
        mid = f"msg_{uuid.uuid4().hex[:12]}"
        output = []
        if tool_calls:
            for tc in tool_calls:
                output.append({"type": "function_call", "id": tc["id"], "call_id": tc["id"],
                               "name": tc["function"]["name"], "arguments": tc["function"]["arguments"], "status": "completed"})
        if text or not tool_calls:
            output.append({"type": "message", "id": mid, "role": "assistant", "status": "completed",
                           "content": [{"type": "output_text", "text": text or "", "annotations": []}]})

        if req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            seq = [0]

            def emit(ev_type, **fields):
                seq[0] += 1
                ev = {"type": ev_type, "sequence_number": seq[0], **fields}
                self.wfile.write(f"event: {ev_type}\ndata: {json.dumps(ev)}\n\n".encode())

            usage = {"input_tokens": len(prompt)//4, "output_tokens": len(text)//4, "total_tokens": (len(prompt)+len(text))//4}
            base_resp = {"id": rid, "object": "response", "created_at": int(time.time()), "model": model_name}
            emit("response.created", response={**base_resp, "status": "in_progress", "output": [], "usage": None})
            emit("response.in_progress", response={**base_resp, "status": "in_progress", "output": [], "usage": None})
            for oi, item in enumerate(output):
                if item["type"] == "function_call":
                    pending = {"type": "function_call", "id": item["id"], "call_id": item["call_id"],
                               "name": item["name"], "arguments": "", "status": "in_progress"}
                    emit("response.output_item.added", output_index=oi, item=pending)
                    emit("response.function_call_arguments.delta", item_id=item["id"], output_index=oi, delta=item["arguments"])
                    emit("response.function_call_arguments.done", item_id=item["id"], output_index=oi, arguments=item["arguments"])
                    emit("response.output_item.done", output_index=oi, item=item)
                elif item["type"] == "message":
                    pending = {"type": "message", "id": item["id"], "role": "assistant", "status": "in_progress", "content": []}
                    emit("response.output_item.added", output_index=oi, item=pending)
                    for ci, cp in enumerate(item["content"]):
                        emit("response.content_part.added", item_id=item["id"], output_index=oi, content_index=ci,
                             part={"type": "output_text", "text": "", "annotations": []})
                        emit("response.output_text.delta", item_id=item["id"], output_index=oi, content_index=ci, delta=cp["text"])
                        emit("response.output_text.done", item_id=item["id"], output_index=oi, content_index=ci, text=cp["text"])
                        emit("response.content_part.done", item_id=item["id"], output_index=oi, content_index=ci, part=cp)
                    emit("response.output_item.done", output_index=oi, item=item)
            emit("response.completed", response={**base_resp, "status": "completed", "output": output, "usage": usage})
            self.wfile.flush()
        else:
            self.send_json({"id": rid, "object": "response", "created_at": int(time.time()), "status": "completed",
                            "model": model_name, "output": output,
                            "usage": {"input_tokens": len(prompt)//4, "output_tokens": len(text)//4, "total_tokens": (len(prompt)+len(text))//4}})


    # ─── Google Native API (Gemini CLI compatible) ────────────────────────────

    def _parse_google_model_from_path(self):
        """Extract model name from /v1beta/models/{model}:method path."""
        m = re.match(r'/v1beta/models/([^:?]+)', self.path)
        if m:
            return m.group(1)
        return None

    def _handle_google_models_list(self):
        """GET /v1beta/models — Google AI format model list."""
        models = []
        for name, cfg in MODELS.items():
            models.append({
                "name": f"models/{name}",
                "displayName": name,
                "description": cfg["desc"],
                "supportedGenerationMethods": ["generateContent", "streamGenerateContent"],
            })
        self.send_json({"models": models})

    def _google_contents_to_prompt(self, req: dict) -> str:
        """Convert Google API contents format to prompt string."""
        parts = []
        sys_inst = req.get("systemInstruction")
        if sys_inst:
            sys_parts = sys_inst.get("parts", [])
            sys_text = " ".join(p.get("text", "") for p in sys_parts if p.get("text"))
            if sys_text:
                parts.append(f"[System instruction]: {sys_text}")

        for content in req.get("contents", []):
            role = content.get("role", "user")
            text_parts = []
            for p in content.get("parts", []):
                if p.get("text"):
                    text_parts.append(p["text"])
            text = " ".join(text_parts)
            if role == "model":
                parts.append(f"[Assistant]: {text}")
            else:
                parts.append(text)
        return "\n\n".join(p for p in parts if p)

    def _handle_google_generate(self, body: bytes, stream: bool):
        """Handle Google native generateContent / streamGenerateContent."""
        req = json.loads(body)
        model_name = self._parse_google_model_from_path()
        if not model_name:
            self.send_json({"error": {"message": "model not specified in path"}}, 400)
            return

        model_name, model_id, think_mode, err = self._resolve_model(model_name)
        if err:
            self.send_json({"error": {"message": err}}, 400)
            return

        prompt = self._google_contents_to_prompt(req)
        if not prompt.strip():
            self.send_json({"error": {"message": "empty content"}}, 400)
            return

        try:
            text, _ = self._call_gemini(prompt, model_id, think_mode, None)
        except Exception as e:
            self.send_json({"error": {"message": f"upstream error: {e}"}}, 502)
            return

        candidate = {
            "content": {"parts": [{"text": text or ""}], "role": "model"},
            "finishReason": "STOP",
            "index": 0,
        }
        usage = {
            "promptTokenCount": len(prompt) // 4,
            "candidatesTokenCount": len(text) // 4,
            "totalTokenCount": (len(prompt) + len(text)) // 4,
        }
        response_obj = {
            "candidates": [candidate],
            "usageMetadata": usage,
            "modelVersion": model_name,
        }

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(f"data: {json.dumps(response_obj)}\n\n".encode())
            self.wfile.flush()
        else:
            self.send_json(response_obj)


# ─── Main ────────────────────────────────────────────────────────────────────

def parse_env_api_keys():
    env_keys = os.environ.get("API_KEYS") or os.environ.get("API_KEY")
    if not env_keys:
        return []
    env_keys = env_keys.strip()
    if env_keys.startswith("["):
        try:
            parsed = json.loads(env_keys)
            if isinstance(parsed, list):
                return [str(k).strip() for k in parsed if str(k).strip()]
        except Exception:
            pass
    return [k.strip() for k in env_keys.split(",") if k.strip()]


def load_config(path: str):
    if path and os.path.exists(path):
        with open(path) as f:
            CONFIG.update(json.load(f))
        log(f"Config loaded: {path}")

    env_keys = parse_env_api_keys()
    if env_keys:
        CONFIG["api_keys"] = env_keys

    if os.environ.get("GEMINI_BL"):
        CONFIG["gemini_bl"] = os.environ["GEMINI_BL"].strip()

    if os.environ.get("DEFAULT_MODEL"):
        CONFIG["default_model"] = os.environ["DEFAULT_MODEL"].strip()

    if os.environ.get("LOG_REQUESTS"):
        CONFIG["log_requests"] = os.environ["LOG_REQUESTS"].strip().lower() == "true"

    if os.environ.get("TEMPORARY_CHATS"):
        CONFIG["temporary_chats"] = os.environ["TEMPORARY_CHATS"].strip().lower() == "true"

    if os.environ.get("MAX_CONCURRENT_REQUESTS"):
        try:
            CONFIG["max_concurrent_requests"] = max(1, int(os.environ["MAX_CONCURRENT_REQUESTS"]))
        except ValueError:
            pass

    env_proxy = os.environ.get("HTTPS_PROXY", "").strip()
    if env_proxy:
        CONFIG["proxy"] = env_proxy

    global _upstream_semaphore
    _upstream_semaphore = threading.BoundedSemaphore(max(1, CONFIG["max_concurrent_requests"]))


def main():
    parser = argparse.ArgumentParser(description="Gemini Web to OpenAI API")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--cookie-file", type=str, default=None, help="Path to cookie file")
    parser.add_argument("--proxy", type=str, default=None, help="HTTP proxy, e.g. http://127.0.0.1:7890")
    parser.add_argument("--version", action="version", version=f"duacincin {__version__}")
    args = parser.parse_args()

    config_path = args.config or os.environ.get("DUACINCIN_CONFIG")
    if not config_path:
        for p in ["./config.json", os.path.expanduser("~/.config/duacincin/config.json")]:
            if os.path.exists(p):
                config_path = p
                break
    load_config(config_path)

    if args.port:
        CONFIG["port"] = args.port
    elif os.environ.get("PORT"):
        try:
            CONFIG["port"] = int(os.environ["PORT"])
        except ValueError:
            pass

    if args.cookie_file:
        CONFIG["cookie_file"] = args.cookie_file
    if args.proxy:
        CONFIG["proxy"] = args.proxy

    get_anon_session(force=True)

    class ThreadedServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    port = CONFIG["port"]
    server = ThreadedServer((CONFIG["host"], port), GeminiHandler)
    print(f"DuaCincin v{__version__}")
    print(f"  Listening: http://0.0.0.0:{port}")
    print(f"  Base URL:  http://localhost:{port}/v1")
    print(f"  Models:    {', '.join(MODELS.keys())}")
    if CONFIG.get("cookie_file"):
        cookie_status = f"yes ({CONFIG['cookie_file']})"
    elif os.environ.get("GEMINI_COOKIE"):
        cookie_status = "yes (GEMINI_COOKIE env)"
    else:
        cookie_status = "none (anonymous)"
    print(f"  Cookie:    {cookie_status}")
    print(f"  Proxy:     {CONFIG.get('proxy') or 'none (uses system env HTTP_PROXY/HTTPS_PROXY)'}")
    print(f"  Retry:     {CONFIG['retry_attempts']}x / {CONFIG['retry_delay_sec']}s (exponential backoff + jitter)")
    print(f"  Max concurrent upstream requests: {CONFIG['max_concurrent_requests']} (extra requests queue)")
    print(f"  BL:        {CONFIG['gemini_bl']}")
    print(f"  Temporary: {'yes' if CONFIG.get('temporary_chats', False) else 'no'}")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
