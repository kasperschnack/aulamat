# Aula Project

Minimal Python CLI for authenticating to Aula, reading recent message threads, and normalizing message data into stable JSON.

## Quick Start

1. Copy `.env.example` to `.env` and set `AULA_MITID_USERNAME`.
2. Install dependencies with `uv sync --dev`.
3. Run:

```bash
uv run aula-project auth-status
uv run aula-project login
uv run aula-project threads --limit 5
uv run aula-project messages <thread-id>
uv run aula-project important --thread-limit 10 --limit 5
uv run aula-project profile
```

Token caching is local and defaults to `.aula_tokens.json`.

`login` now reports which auth path was used:

- `cached_access_token`
- `refreshed_access_token`
- `fresh_login`
- `fresh_login_after_cookie_rejection`

`auth-status` inspects only the local token cache. `important` ranks likely-important threads using deterministic rules and includes the matched signals in its JSON output.

## Environment

- `AULA_MITID_USERNAME`: MitID username used for Aula login
- `AULA_AUTH_METHOD`: `app` or `token`, defaults to `app`
- `AULA_TOKEN_CACHE_PATH`: token cache file path, defaults to `.aula_tokens.json`
- `AULA_RAW_CAPTURE_DIR`: optional directory for saved raw payloads
- `AULA_MESSAGE_LIMIT`: default thread listing limit, defaults to `10`
- `AULA_JSON_INDENT`: JSON indentation, defaults to `2`
