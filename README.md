# Aulamat

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

## Scheduled Review

`review-new` is intended for scheduled runs. It reads recent threads, expands them into full messages, filters messages received since the previous successful scan, asks OpenAI for a structured relevance decision, and stores its checkpoint in `.aula_scan_state.json`.

For automation or downstream processing, use the default compact JSON:

```bash
uv run aula-project review-new --thread-limit 20
uv run aula-project review-new --thread-limit 20 --format json
```

For a user-facing notification body, use plain text:

```bash
uv run aula-project review-new --thread-limit 20 --format text
```

For debugging normalization, prompt input, or model decisions, use verbose JSON:

```bash
uv run aula-project review-new --thread-limit 20 --format json-verbose
```

Output modes:

- `--format json`: compact machine-readable JSON, default
- `--format json-verbose`: full normalized messages for debugging
- `--format text`: end-user summary text only

Use `--dry-run` to inspect candidates without calling OpenAI or updating the checkpoint:

```bash
uv run aula-project review-new --thread-limit 20 --dry-run
```

## Environment

- `AULA_MITID_USERNAME`: MitID username used for Aula login
- `AULA_AUTH_METHOD`: `app` or `token`, defaults to `app`
- `AULA_TOKEN_CACHE_PATH`: token cache file path, defaults to `.aula_tokens.json`
- `AULA_SCAN_STATE_PATH`: scheduled scan checkpoint path, defaults to `.aula_scan_state.json`
- `AULA_RAW_CAPTURE_DIR`: optional directory for saved raw payloads
- `AULA_MESSAGE_LIMIT`: default thread listing limit, defaults to `10`
- `AULA_JSON_INDENT`: JSON indentation, defaults to `2`
- `AULA_OPENAI_MODEL`: OpenAI model used by `review-new`, defaults to `gpt-5.2`
- `OPENAI_API_KEY`: OpenAI API key used by the official SDK
