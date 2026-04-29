# Aula Project Plan

## Objective

Start a focused project for reading data from Aula, with messages as the first priority.
The initial target is to read and normalize:

- Aula message threads and message bodies (`beskeder`)
- Related school data that may come from integrated providers such as Overblik and Meebook

## Reference Repo Review

Reference: <https://github.com/A-Hoier/Aula-AI.d>

What the reference repo is useful for:

- It contains a working custom `AulaClient`.
- It logs in through `https://login.aula.dk/auth/login.php`.
- It discovers the active Aula API version by probing `https://www.aula.dk/api/v20+`.
- It uses these Aula endpoints:
  - `profiles.getProfilesByLogin`
  - `presence.getDailyOverview`
  - `messaging.getThreads`
  - `messaging.getMessagesForThread`
  - `calendar.getEventsByProfileIdsAndResourceIds`
  - `gallery.getAlbums`
  - `gallery.getAlbum`

What should not be copied into this new project by default:

- The FastAPI chat wrapper
- The Dash frontend
- The Pydantic AI agent layer
- The Google research toolchain
- The Azure/Anthropic model configuration

Reason:
The repo is mainly an AI chat demo with Aula attached as one tool. This new repo should start as an Aula data project, not an LLM app.

## Recommended Technical Direction

Use the reference repo as endpoint inspiration, but prefer a maintained Aula library for authentication and core data access where possible.

Recommended base:

- Python project
- `uv` for environment and dependency management
- The `aula` package from PyPI for MitID-based auth, token caching, messages, calendar, posts, notifications, and widget access

Why this is the better starting point:

- It avoids maintaining a fragile browser-login scraper unless necessary.
- It already exposes message and widget-oriented operations.
- It appears to cover provider-linked data such as Meebook-related week plans through widget APIs.

Pragmatic fallback:

- If the `aula` package does not expose the exact Overblik or Meebook data needed, add a thin raw-Aula client layer for the missing endpoints only.
- Reuse the endpoint patterns proven in `Aula-AI.d` for that fallback layer.

## Scope For Phase 1

Deliver a minimal, dependable data layer before any UI.

Phase 1 goals:

1. Authenticate against Aula with reusable local token storage.
2. Fetch profile and child/institution context.
3. Fetch message threads.
4. Fetch full messages for a thread.
5. Normalize output into one internal schema.
6. Export results as JSON from a CLI command.

Phase 1 non-goals:

- No chat UI
- No web UI
- No LLM integration
- No dashboard
- No containerization unless required later

## Normalized Data Model

Create one internal representation so data from native Aula messaging and provider-linked sources can be handled uniformly.

Suggested entities:

- `Profile`
- `ChildContext`
- `MessageSource`
- `MessageThread`
- `MessageItem`
- `Attachment`

Suggested `MessageSource` values:

- `aula`
- `overblik`
- `meebook`
- `unknown`

Suggested normalized fields for a thread:

- `thread_id`
- `source`
- `title`
- `participants`
- `last_message_at`
- `unread`
- `raw`

Suggested normalized fields for a message:

- `message_id`
- `thread_id`
- `source`
- `sender_name`
- `sent_at`
- `body_text`
- `body_html`
- `attachments`
- `raw`

## Proposed Repo Shape

```text
.
├── PROJECT_PLAN.md
├── HANDOVER_PROMPT.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/
│   └── aula_project/
│       ├── __init__.py
│       ├── config.py
│       ├── auth.py
│       ├── client.py
│       ├── normalize.py
│       ├── models.py
│       └── cli.py
└── tests/
    ├── test_normalize.py
    └── test_messages.py
```

## Implementation Plan

### Milestone 1: Bootstrap

- Create Python package skeleton.
- Add `pyproject.toml`.
- Add `.env.example`.
- Add `.gitignore` that excludes secrets, token caches, and local envs.
- Add a small CLI entrypoint.

### Milestone 2: Auth + Profile

- Integrate Aula authentication.
- Store tokens locally in a non-committed file.
- Add a command to print the current profile and child contexts.

### Milestone 3: Native Aula Messages

- Implement:
  - list threads
  - fetch messages for thread
  - normalize message/thread data
- Add JSON output suitable for later automation.

### Milestone 4: Provider-Linked Data

- Audit what Overblik and Meebook data is available through the maintained Aula library.
- If available, normalize it into the same internal schema.
- If not available, add narrowly scoped raw endpoint calls.
- Keep provider-specific code isolated from the core client.

### Milestone 5: Quality

- Add fixture-backed tests for normalization.
- Add a smoke-test command for live auth and read access.
- Add logging with sensitive fields redacted.

## Risks And Unknowns

- Some Aula content may require MitID re-authentication or elevated session state.
- Sensitive messages may not expose full content through the same route every time.
- Overblik and Meebook may not map to standard Aula message threads.
- Provider data may be exposed through widgets, posts, or summaries rather than `messaging.*`.
- A custom login scraper is more brittle than token-based auth through a maintained client.

## First Build Recommendation

The first actual implementation pass should do this and nothing more:

1. Bootstrap the Python repo.
2. Integrate the maintained `aula` package.
3. Add a CLI command that authenticates and prints recent message threads as JSON.
4. Add a second CLI command that expands one thread into full messages.
5. Save raw payloads during development so normalization can be refined safely.

## Source Notes

- `Aula-AI.d` proved the relevant Aula message endpoints and session flow.
- PyPI `aula` documentation indicates a maintained client with:
  - `get_message_threads()`
  - `get_messages_for_thread(thread_id)`
  - widget access including Meebook-related helpers
  - CLI support for messages, notifications, summaries, and widget-backed school data
