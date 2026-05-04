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
uv run aula-project notify-new --thread-limit 20 --dry-run
uv run aula-project summary-server
```

Token caching is local and defaults to `.aula_tokens.json`.

`login` now reports which auth path was used:

- `cached_access_token`
- `refreshed_access_token`
- `fresh_login`
- `fresh_login_after_cookie_rejection`

`auth-status` inspects only the local token cache and prints whether cached login can be reused, refreshed, or needs a new login. Use `auth-status --verbose` for sanitized token and cookie diagnostics. `important` ranks likely-important threads using deterministic rules and includes the matched signals in its JSON output.

Default human-readable output is intentionally concise. When timestamps are shown in text, they use local time only. Use JSON or verbose output when you need UTC timestamps, raw-ish normalized fields, or diagnostics.

## Scheduled Review

`review-new` is intended for scheduled runs. It reads recent threads, expands changed or uncached threads into full messages, filters messages received since the previous successful scan, asks OpenAI for a structured relevance decision, and stores its checkpoint in `.aula_scan_state.json`. Thread messages are cached in `.aula_message_cache.json` so unchanged threads do not need to be expanded on every run.

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

## Notifications

`notify-new` runs the scheduled review flow and sends a notification only when something meets the configured minimum priority. It uses OpenAI decisions when enabled, and falls back to deterministic triage with `--no-openai` or `--dry-run`.

Configure an Apprise notification URL in `.env`:

```env
AULA_NOTIFY_URL=pover://USER_KEY@APP_TOKEN
AULA_NOTIFY_MIN_PRIORITY=medium
```

Then run:

```bash
uv run aula-project notify-new --thread-limit 20
```

Useful variants:

```bash
uv run aula-project notify-new --thread-limit 20 --dry-run
uv run aula-project notify-new --thread-limit 20 --no-openai
uv run aula-project notify-new --thread-limit 20 --min-priority high
uv run aula-project notify-new --thread-limit 20 --dry-run --timeout-seconds 20
```

`AULA_NOTIFY_URL` accepts any Apprise-supported URL, such as Pushover, ntfy, Telegram, email, Slack, or Discord. Use `AULA_NOTIFY_URLS` with whitespace-separated URLs to notify more than one destination.

If no Apprise URL is configured, `notify-new` will use `terminal-notifier` when it is available on `PATH`:

```bash
brew install terminal-notifier
uv run aula-project notify-new --thread-limit 20
```

Install macOS launchd jobs for notifications and the always-on summary page:

```bash
uv run aula-project install-service --interval-minutes 20 --thread-limit 20 --load
```

This installs two user LaunchAgents:

- `dk.local.aula-project.notify`: runs `notify-new` every 20 minutes, refreshes the Aula token when needed, checks for important new messages, sends a notification only when something meets the configured priority, and updates `.aula_scan_state.json` after successful delivery or when no notification is needed.
- `dk.local.aula-project.summary`: keeps `summary-server` running at `http://127.0.0.1:8767/`. The page fetches fresh Aula data whenever it is opened or refreshed.

Use `--no-summary-server` if you only want the periodic notification checker.

## Summary Server

Run a local summary page manually:

```bash
uv run aula-project summary-server --thread-limit 20 --limit 10
```

Then open `http://127.0.0.1:8767/`. JSON is available at `http://127.0.0.1:8767/api/summary`.

The current implementation reads the Aula profile, message threads, and full messages for those threads. It does not yet fetch calendar events, absence records, documents, galleries, Meebook plans beyond message-thread payloads, or other Aula modules.

## Docker Deployment

The summary server can run in Docker with token and scan-state files stored in a named volume. First copy `.env.example` to `.env` on the server and set at least `AULA_MITID_USERNAME`.

Build the image:

```bash
docker compose build
```

Run the first interactive Aula login inside the container:

```bash
docker compose run --rm aula-summary aula-project login
```

That command writes `/data/.aula_tokens.json` into the `aula-data` Docker volume. The running server reuses and refreshes that cache.

Start the summary server:

```bash
docker compose up -d
```

By default, `compose.yml` publishes the page only on the server loopback interface at `http://127.0.0.1:8767/`. Put a reverse proxy in front of it for remote access, or change the port binding to `8767:8767` if you intentionally want Docker to listen on all interfaces.

Useful server commands:

```bash
docker compose logs -f aula-summary
docker compose exec aula-summary aula-project auth-status
docker compose run --rm aula-summary aula-project login
docker compose down
```

## Environment

- `AULA_MITID_USERNAME`: MitID username used for Aula login
- `AULA_AUTH_METHOD`: `app` or `token`, defaults to `app`
- `AULA_TOKEN_CACHE_PATH`: token cache file path, defaults to `.aula_tokens.json`
- `AULA_SCAN_STATE_PATH`: scheduled scan checkpoint path, defaults to `.aula_scan_state.json`
- `AULA_MESSAGE_CACHE_PATH`: per-thread message cache path, defaults to `.aula_message_cache.json`
- `AULA_RAW_CAPTURE_DIR`: optional directory for saved raw payloads
- `AULA_MESSAGE_LIMIT`: default thread listing limit, defaults to `10`
- `AULA_JSON_INDENT`: JSON indentation, defaults to `2`
- `AULA_OPENAI_MODEL`: OpenAI model used by `review-new`, defaults to `gpt-5.2`
- `AULA_NOTIFY_URL`: Apprise notification URL used by `notify-new`
- `AULA_NOTIFY_URLS`: whitespace-separated Apprise notification URLs, alternative to `AULA_NOTIFY_URL`
- `AULA_NOTIFY_MIN_PRIORITY`: `low`, `medium`, or `high`, defaults to `medium`
- `AULA_REQUEST_TIMEOUT_SECONDS`: overall timeout for Aula network commands, defaults to `60`; set to `0` to disable
- `OPENAI_API_KEY`: OpenAI API key used by the official SDK
