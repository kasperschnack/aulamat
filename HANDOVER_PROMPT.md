# Handover Prompt

Continue this repo as a focused Aula message-triage project.

Start by reading `PROJECT_PLAN.md`, then inspect `src/aula_project/`, especially:

- `client.py`
- `normalize.py`
- `triage.py`
- `scheduled_review.py`
- `openai_review.py`
- `scan_state.py`
- `cli.py`

## Current Status

- The repo is a minimal Python CLI project managed with `uv`.
- The GitHub repo is public:
  - `https://github.com/kasperschnack/aulamat`
  - remote: `git@github.com:kasperschnack/aulamat.git`
- The maintained `aula` package is integrated.
- MitID login works from this repo.
- Token caching is implemented locally via `.aula_tokens.json`.
- Auth-cache inspection is implemented.
- Native Aula message thread retrieval works.
- Full message retrieval for a thread works.
- Live Aula `content_html` message bodies are normalized.
- Deterministic message triage is implemented.
- OpenAI-based scheduled review is implemented.
- The project now supports the intended scheduled workflow:
  1. Read recent Aula message threads.
  2. Fetch full messages for each thread.
  3. Filter messages not seen in the previous run.
  4. Run deterministic triage for transparent signals.
  5. Ask OpenAI for a structured relevance decision and summary.
  6. Store the checkpoint in `.aula_scan_state.json`.

## CLI Commands

Current CLI commands:

- `login`
- `auth-status`
- `profile`
- `threads`
- `messages <thread-id>`
- `important`
- `review-new`

Important command examples:

```bash
uv run aula-project auth-status
uv run aula-project threads --limit 5
uv run aula-project messages <thread-id>
uv run aula-project important --thread-limit 10 --limit 5
uv run aula-project review-new --thread-limit 20
uv run aula-project review-new --thread-limit 20 --dry-run
uv run aula-project review-new --thread-limit 20 --include-messages
```

`review-new` defaults to concise output:

- counts
- compact per-thread deterministic signal summaries
- `openai_review`

Use `--include-messages` only for debugging normalization or prompt inputs because the full payload is large.

## Current Environment Variables

See `.env.example`.

- `AULA_MITID_USERNAME`
- `AULA_AUTH_METHOD`
- `AULA_TOKEN_CACHE_PATH`
- `AULA_SCAN_STATE_PATH`
- `AULA_RAW_CAPTURE_DIR`
- `AULA_MESSAGE_LIMIT`
- `AULA_JSON_INDENT`
- `AULA_OPENAI_MODEL`
- `OPENAI_API_KEY`

Ignored local state:

- `.env`
- `.aula_tokens.json`
- `.aula_scan_state.json`
- `.aula_raw/`

## Verified Behavior

On April 29, 2026:

- `auth-status` showed a reusable cached access token, refresh token, and session cookies.
- `uv run pytest` passed after the scheduled-review changes.
- The test suite covered normalization, deterministic triage, auth-cache inspection, and scheduled-review state handling.
- A live `review-new --thread-limit 20` run completed end to end.
- The live run returned a useful OpenAI review with:
  - per-thread `flag`
  - `priority`
  - `reason`
  - `recommended_action`
  - short evidence snippets
  - overall summary

The live output was initially too verbose because it included full normalized messages by default. The code was then changed so `review-new` is concise by default and full messages require `--include-messages`.

## Confirmed Findings

- The Aula message API path used by the old reference repo remains relevant.
- These Aula methods are still important for message access:
  - `profiles.getProfilesByLogin`
  - `messaging.getThreads`
  - `messaging.getMessagesForThread`
- The old browser-scraping login flow should not be copied.
- Authentication should continue to use the maintained `aula` package and MitID.
- A local compatibility patch exists around the MitID completion handoff because the upstream flow did not fully match the current redirect/form behavior during testing.
- The maintained `aula` package handles key auth reuse paths:
  - cached access-token reuse
  - refresh-token renewal
  - fresh MitID fallback when cached session cookies are rejected
- Live thread metadata is sparse:
  - titles may be present
  - participants are often missing
  - timestamps are often missing
  - preview text may be missing
- Because thread metadata is sparse, relevance ranking must inspect full thread messages.
- Some live messages have no sender or sent timestamp in the maintained library output.
- Message IDs from live payloads are usable as the scheduled checkpoint key.

## Message Scope

The current implementation reads native Aula messages.

Meebook status:

- The normalizer can label a thread as `meebook` when Meebook appears inside native Aula message metadata.
- The project does not yet fetch Meebook/provider widget data directly.
- A live message mentioned that Meebook may be down and users can use the browser instead of the app.
- Keep Meebook/provider integration separate from native Aula messaging until there is a concrete need and stable data source.

## Relevance Direction

The product goal is no longer only “urgent or required”.

The scheduled review should answer:

> Is there anything in new Aula messages that is relevant or interesting for a parent to notice?

Relevant includes:

- deadlines
- payment or MobilePay requests
- schedule changes
- cancelled or moved trips
- missing forms or consent
- meetings
- requests for response
- absence / pickup / practical school logistics
- things to bring
- unread or sensitive messages
- attachments
- optional but interesting opportunities:
  - extracurricular activities
  - clubs and associations
  - courses
  - camps or holiday activities
  - workshops
  - webinars
  - extracurricular/enrichment activities

Priority guidance:

- Required action with deadline/payment/response should usually be `high`.
- Concrete logistics for the child should usually be `medium`.
- Optional opportunities are relevant but usually `low` unless they have a deadline, payment, or explicit action.
- Generic FYI/newsletter content should not be flagged unless it contains a concrete action, logistics, or genuinely interesting opportunity.

## Deterministic Signals

Currently implemented signal families include:

- `deadline`
- `schedule_change`
- `consent_or_form`
- `response_requested`
- `meeting`
- `absence_or_pickup`
- `practical_logistics`
- `optional_opportunity`
- `unread`
- `sensitive`
- `attachments`

The deterministic layer is not the final judge. It exists to provide transparent evidence and useful hints to OpenAI.

## OpenAI Review

OpenAI integration lives in `openai_review.py`.

Scheduled prompt shaping lives in `scheduled_review.py`.

The OpenAI review returns strict JSON with:

- `items`
  - `thread_id`
  - `flag`
  - `priority`
  - `reason`
  - `recommended_action`
  - `evidence`
- `summary`

The current prompt tells OpenAI to:

- flag required school logistics
- flag optional opportunities like camps, clubs, workshops, webinars, and enrichment activities
- keep optional opportunities lower priority unless there is deadline/payment/action
- avoid flagging generic FYI content
- use Danish message content as primary evidence
- keep evidence snippets short

## Auth Direction

Treat token reuse as a product requirement.

Focus on:

- verifying cached token reuse
- verifying refresh-token behavior
- understanding when Aula session cookies expire
- reducing fresh MitID prompts without brittle hacks

Prefer:

- cached token reuse
- refresh-token renewal
- session re-initialization when possible

Do not build a fake long-running session daemon unless repeated scheduled usage proves it is needed.

Current observability:

- `login` reports the auth strategy used
- `auth-status` inspects the local cache without hitting Aula
- auth output is sanitized and should not expose raw tokens

## Constraints

- Keep the project small and dependable.
- Prefer CLI JSON output first.
- Do not build a web UI yet.
- Do not add broad agent infrastructure.
- Keep raw Aula retrieval separate from interpretation.
- Preserve raw payloads only where useful for debugging.
- Keep native Aula messaging separate from provider-linked data such as Overblik or Meebook.
- Keep tests fixture-backed where possible.
- Scheduled output should be concise by default.

## Immediate Next Steps

1. Run tests after the latest prompt/triage updates.
2. Verify `review-new --dry-run` and `review-new --no-openai` still behave correctly.
3. Add or update tests for `optional_opportunity` using broad category examples, not vendor-specific names.
4. Inspect the compact `review-new` output after another live run.
5. Consider adding a `--since` or `--reset-state` utility if scheduled testing needs easier checkpoint control.
6. Consider adding notification delivery later, but only after the JSON review output is stable.

## Definition Of Done For The Next Pass

- Tests pass.
- `review-new` remains concise by default.
- `--include-messages` still exposes full normalized payloads for debugging.
- Optional opportunities are treated as relevant, usually low priority, without hard-coding one specific provider or activity name.
- Required actions and practical school logistics remain higher priority than optional enrichment items.
- Repeated scheduled runs do not reprocess already seen message IDs.
- Auth reuse continues to avoid fresh MitID in normal use when cached/refresh tokens are valid.
