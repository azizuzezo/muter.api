# DuaCincin

<p align="center">
  <img src="logo.png" width="200" alt="DuaCincin logo">
</p>

[中文文档](README_CN.md)

Convert Google Gemini's web interface into an OpenAI-compatible API. Zero cost, cross-platform, single file.

## Features

- **Interactive API Docs**: Swagger UI at `/docs` with **Try it out** support, spec at `/openapi.json`
- **Optional API Keys**: no auth when `api_keys` is empty, OpenAI-style Bearer auth when configured
- **OpenAI Compatible**: Drop-in replacement for `/v1/chat/completions`, `/v1/images/generations`, and `/v1/models`
- **Image Generation**: Standard `/v1/images/generations` endpoint powered by Imagen 3 (`imagen-3.0-generate-002`, `imagen-3`, `dall-e-3`, `dall-e-2`)
- **Tool Calling**: Full function calling support (OpenAI format)
- **Multiple Models**: Flash (3.6/3.5/2.5/2.0/1.5), Extended Thinking, Pro, Auto, Lite, Nano Banana (`nano-banana`)
- **Thinking Depth**: Adjustable via `@think=N` suffix (0=deepest, 4=shallowest)
- **Flexible Model Selection**: Choose model via JSON body `model`, `x-gemini-model` / `x-model` header, or `?model=...` query string
- **Web Search**: Built-in internet access (Gemini's native search)
- **Cross-Platform**: Pure Python, single optional dependency (`httpx` for streaming)
- **Streaming**: SSE streaming support via `httpx`
- **Codex CLI**: Responses API (`/v1/responses`) for OpenAI Codex integration
- **Gemini CLI**: Google native API (`/v1beta/models`) for Gemini CLI compatibility

## Quick Start

```bash
pip install httpx
python duacincin.py
```

Server starts at `http://localhost:8081/v1`.

## API Docs

Interactive, testable API documentation (Swagger UI) is served at:

```
http://localhost:8081/docs
```

It lists every endpoint (`/v1/chat/completions`, `/v1/images/generations`, `/v1/models`, `/v1/responses`, `/v1beta/models/...`) with request/response schemas and examples. Use **Try it out** to send real requests straight from the browser to this running server — no separate client needed. If `api_keys` is configured, click **Authorize** first and paste your key. The raw OpenAPI 3.0 spec is available at `http://localhost:8081/openapi.json` for importing into Postman, Insomnia, or generating client SDKs.

## Client Configuration

### Cherry Studio / ChatBox / any OpenAI client

| Field | Value |
|-------|-------|
| Base URL | `http://localhost:8081/v1` |
| API Key | any `api_keys` value from `config.json`; anything if not configured |
| Model | `gemini-3.5-flash-thinking` |

### Image Generation (`/v1/images/generations`)

```bash
curl http://localhost:8081/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"model":"imagen-3.0-generate-002","prompt":"A beautiful sunset over snowy mountains"}'
```

*(Note: Image generation requires a Google account cookie file configured via `cookie_file`)*

### curl

#### bash / macOS / Linux

```bash
curl http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-key" \
  -d '{"model":"gemini-3.5-flash","messages":[{"role":"user","content":"Hello!"}]}'
```

#### PowerShell (Windows)

```powershell
curl.exe --% http://127.0.0.1:8081/v1/chat/completions -H "Content-Type: application/json" -H "Authorization: Bearer sk-your-key" -d "{\"model\":\"gemini-3.5-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello!\"}]}"
```

> Note: On Windows PowerShell, use `curl.exe` and `--%` so PowerShell does not reinterpret JSON quoting or curl options.

### OpenAI Python SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8081/v1", api_key="sk-your-key")

# Text completion
resp = client.chat.completions.create(
    model="gemini-3.5-flash-thinking",
    messages=[{"role": "user", "content": "Explain quantum computing"}]
)
print(resp.choices[0].message.content)

# Image generation (requires cookie)
img_resp = client.images.generate(
    model="imagen-3.0-generate-002",
    prompt="A futuristic cyberpunk city at night"
)
print(img_resp.data[0].url)
```

### Gemini CLI

```bash
export GEMINI_API_KEY=none
export GOOGLE_GEMINI_BASE_URL=http://localhost:8081
gemini
```

Supports Google native API endpoints:
- `GET /v1beta/models` — list models
- `POST /v1beta/models/{model}:generateContent` — non-streaming
- `POST /v1beta/models/{model}:streamGenerateContent` — streaming (SSE)

## Available Models

| Model | Description | Output |
|-------|-------------|--------|
| `gemini-4-argon` | Gemini 4 Argon (Flash category) | ~12k chars |
| `gemini-3.7-flash` | All-around model (latest, default) | ~12k chars |
| `gemini-3.6-flash` | Alias for gemini-3.7-flash | ~12k chars |
| `gemini-3.5-flash` | Alias for gemini-3.7-flash | ~12k chars |
| `gemini-3.5-flash-thinking` | Extended thinking, longest output | **~20k chars** |
| `gemini-3.5-flash-thinking-lite` | Adaptive thinking depth | ~15k chars |
| `gemini-3.1-pro` | Advanced math & code (needs cookie) | ~12k chars |
| `gemini-auto` | Auto model selection | varies |
| `gemini-flash-lite` | Fastest answers, lightweight | ~10k chars |
| `nano-banana` | Ultra-fast lightweight model alias | ~10k chars |
| `imagen-3.0-generate-002` | Imagen 3 Image Generation model (needs cookie) | Image URL |
| `imagen-3` | Alias for Imagen 3 | Image URL |
| `dall-e-3` | OpenAI DALL-E 3 alias (routes to Imagen 3) | Image URL |

### Thinking Depth

Append `@think=N` to any model name:

```
gemini-3.5-flash-thinking@think=0   # deepest (default)
gemini-3.5-flash-thinking@think=2   # medium
gemini-3.5-flash-thinking@think=4   # shallowest
```

## Optional: Cookie for Pro

Anonymous access works for all models, but `gemini-3.1-pro` routes to Flash without authentication. To get real Pro routing, you need a **Gemini Advanced (paid subscription)** account cookie:

```bash
python duacincin.py --cookie-file cookie.txt
```

### How to get cookies

1. Open Chrome, go to [gemini.google.com](https://gemini.google.com) and sign in with a **Gemini Advanced** Google account
2. Open DevTools (F12) → Application → Cookies → `https://gemini.google.com`
3. Copy these cookie values: `SID`, `HSID`, `SSID`, `APISID`, `SAPISID`, `__Secure-1PSID`
4. Create `cookie.txt` in this format:

```
SID=your_sid_value; HSID=your_hsid_value; SSID=your_ssid_value; APISID=your_apisid_value; SAPISID=your_sapisid_value; __Secure-1PSID=your_1psid_value
```

Or use the JSON format:
```json
{"cookie": "SID=xxx; HSID=xxx; SSID=xxx; APISID=xxx; SAPISID=xxx; __Secure-1PSID=xxx", "sapisid": "your_sapisid_value"}
```

**Alternative (browser extension)**: Use any "Export Cookies" extension to export cookies for `gemini.google.com` in Netscape format, then convert to the single-line format above.

### Authenticated account path and XSRF token

If the signed-in Gemini page URL contains an account index, such as:

```
https://gemini.google.com/u/1/app/...
```

set `auth_user` to that index. Authenticated web requests may also require the page XSRF token. In the rendered Gemini page source, this token is exposed as `SNlM0e`; pass it as `xsrf_token` in `config.json`. The server sends it as the `at` form field.

Example:

```json
{
  "cookie_file": "/app/cookie.txt",
  "auth_user": "1",
  "xsrf_token": "AOOh0P...",
  "gemini_bl": "boq_assistant-bard-web-server_YYYYMMDD.xx_p0"
}
```

If authenticated requests return HTTP 400 with an `xsrf` error, refresh Gemini Web, update `xsrf_token`, and make sure `auth_user` matches the `/u/<index>/` part of the browser URL.

Pro routing requires **Gemini Advanced** (paid subscription). A free Google account cookie will authenticate but silently fall back to Flash.

## Configuration

Create `config.json` in the same directory:

```json
{
  "port": 8081,
  "host": "0.0.0.0",
  "retry_attempts": 3,
  "retry_delay_sec": 2,
  "request_timeout_sec": 180,
  "gemini_bl": "boq_assistant-bard-web-server_20260716.08_p0",
  "auth_user": null,
  "xsrf_token": null,
  "api_keys": ["sk-your-key"],
  "cookie_file": null,
  "proxy": null,
  "log_requests": true,
  "max_concurrent_requests": 3
}
```

When `api_keys` is `[]`, authentication is disabled. When one or more keys are set, `/v1/*` endpoints require `Authorization: Bearer <key>` or `x-api-key: <key>`.

`max_concurrent_requests` caps how many requests are in flight to Gemini's backend at once; extra requests queue instead of firing in parallel. Bursts of simultaneous requests are what trip Google's rate limiting (429s), not the total requests-per-minute on their own, so raising this number too high brings 429s back even though total throughput looks the same.

### Environment variables

Useful on platforms without a persistent filesystem (Railway, Heroku, etc.) where you can't just mount `config.json`/`cookie.txt`:

| Variable | Purpose |
|----------|---------|
| `PORT` | Overrides `config.json`'s `port`. Set automatically by Railway/Heroku. |
| `API_KEYS` | Comma-separated list (or JSON array) of accepted API keys, e.g. `sk-a,sk-b`. Overrides `config.json`'s `api_keys`. |
| `GEMINI_COOKIE` | Cookie content, used when no `cookie_file` is configured/found. Accepts the same two formats as the file: a raw `SID=...; HSID=...; ...` string, or the `{"cookie": "...", "sapisid": "..."}` JSON form. |
| `GEMINI_SAPISID` | Optional; overrides the `SAPISID` parsed out of `GEMINI_COOKIE`. |
| `DUACINCIN_CONFIG` | Path to `config.json`, if not in the working directory. |
| `MAX_CONCURRENT_REQUESTS` | Overrides `config.json`'s `max_concurrent_requests`. |

## Docker

```bash
cp config.example.json config.json
docker build -t duacincin .
docker run -d --name duacincin -p 8081:8081 -v ./config.json:/app/config.json duacincin
```

Or use Docker Compose:

```bash
cp config.example.json config.json
docker compose up -d
```

To mount a cookie file:

```bash
docker run -d --name duacincin -p 8081:8081 -v ./config.json:/app/config.json -v ./cookie.txt:/app/cookie.txt duacincin
```

Set `"cookie_file": "/app/cookie.txt"` in `config.json`.

On platforms without a mountable volume (Railway, Heroku), skip `cookie_file` entirely and set the `GEMINI_COOKIE` environment variable to your cookie string instead — see [Environment variables](#environment-variables).

> **Note**: If you get empty responses (`content: null`) with Docker's default bridge network, switch to host networking: `docker run --network host ...` or add `network_mode: host` in your compose file. This is caused by Gemini's upstream rejecting requests from certain Docker NAT IP ranges.

## Proxy

If you cannot access `gemini.google.com` directly (connection timeout), configure a proxy:

**Method 1: CLI argument**
```bash
python duacincin.py --proxy http://127.0.0.1:7890
```

**Method 2: config.json**
```json
{"proxy": "http://127.0.0.1:7890"}
```

**Method 3: Environment variable** (auto-detected)
```bash
export HTTPS_PROXY=http://127.0.0.1:7890
python duacincin.py
```

Works with Clash, V2Ray, Shadowsocks, or any HTTP proxy.

## Tool Calling

```python
resp = client.chat.completions.create(
    model="gemini-3.5-flash",
    messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a city",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
        }
    }]
)
```

## Limitations

- **No image/multimodal input**: attaching an image requires a client-side integrity token generated by Gemini Web's own frontend JavaScript (confirmed via a captured real request), which a plain HTTP proxy cannot reproduce. Image inputs in messages will be ignored with a note.
- **No TTS / read-aloud**: Gemini Web's "Listen" (text-to-speech) feature has not been reverse-engineered here; there is no `/v1/audio/speech` endpoint.
- **Not real Pro/Ultra**: Without a paid subscription cookie, `gemini-3.1-pro` routes to the same Flash model. The "Pro" label is a UI preference, not a backend model switch.
- **Single-turn only**: Each request is an independent conversation. Multi-turn context is simulated by including previous messages in the prompt.
- **Rate limits**: Google may throttle high-frequency requests. The server retries automatically but sustained heavy use may be blocked.

## Requirements

- Python 3.8+
- `httpx` (`pip install httpx`) — used for streaming requests
- Network access to `gemini.google.com` (proxy/VPN may be needed in some regions)

## How It Works

This tool reverse-engineers Google Gemini's web StreamGenerate protocol. It sends requests to the same endpoint that the Gemini web app uses, converting between OpenAI's API format and Gemini's internal protobuf-like format.

The model selection is controlled by field `[79]` in the request payload, mapped from Gemini's frontend JavaScript source (`MODE_CATEGORY` enum).

## Acknowledgments

- Inspired by the open-source API proxy ecosystem

## License

MIT

---

## 致谢

本项目的开发 agent 能力由 [GenericAgent](https://github.com/lsdefine/GenericAgent) 提供。

### 🚩 友情链接

[![GenericAgent](https://img.shields.io/badge/Agent_Framework-GenericAgent-orange?style=for-the-badge&logo=github)](https://github.com/lsdefine/GenericAgent)
[![LinuxDo](https://img.shields.io/badge/社区-LinuxDo-blue?style=for-the-badge)](https://linux.do/)
