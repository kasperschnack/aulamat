# Handover Prompt

Continue this repo as a focused Aula data project.

Start by reading `PROJECT_PLAN.md`, then inspect the existing implementation under `src/aula_project/`.

## Current Status

- The repo now contains a minimal Python CLI project managed with `uv`.
- The maintained `aula` package is integrated.
- MitID login now works from this repo.
- Token caching is implemented locally via `.aula_tokens.json`.
- The CLI currently supports:
  - `login`
  - `profile`
  - `threads`
  - `messages <thread-id>`
- Normalization models and fixture-backed tests exist.

## Confirmed Findings

- The Aula message API path used by the old reference repo is still relevant.
- These Aula methods are still the important ones for message access:
  - `profiles.getProfilesByLogin`
  - `messaging.getThreads`
  - `messaging.getMessagesForThread`
- The old browser-scraping login flow should not be copied.
- Authentication should continue to use the maintained `aula` package and MitID.
- A local compatibility patch was added around the MitID completion handoff because the upstream flow did not fully match the current redirect/form behavior during testing.

## New Priority

The next pass is no longer just “can we log in?”.

The next goals are:

1. Make auth reuse dependable so the user does not need to complete MitID every time.
2. Read Aula messages and identify what is important enough that the user should actually read it.

## Auth Direction

Treat token reuse as a product requirement, not a nice-to-have.

Focus on:

- verifying when cached tokens are reused successfully
- verifying when refresh tokens are sufficient
- understanding when Aula session cookies expire
- reducing fresh MitID prompts as much as possible without brittle hacks

Prefer:

- cached token reuse
- refresh-token-based renewal
- session re-initialization when possible

Only add “keep alive” behavior if it is actually needed after measuring the cache/refresh behavior.
Do not build a fake long-running session daemon unless it solves a real problem.

## Message Triage Direction

The user wants an agent to read Aula messages and figure out whether there is something important to read.

Build this in stages:

1. First, make message retrieval solid and normalized.
2. Then add a deterministic triage layer that flags likely-important messages.
3. Only after that, add an agent/LLM pass for summarization or prioritization.

Important:

- Keep raw Aula retrieval separate from interpretation.
- Preserve raw payloads where useful for debugging.
- Be explicit about what is a raw message fact versus an inferred importance judgment.

Examples of likely-important signals:

- deadlines
- schedule changes
- missing forms or consent
- meetings
- requests for response
- absence / pickup / practical school logistics
- sensitive or unread messages

## Reference Context

This repo was started from a review of `https://github.com/A-Hoier/Aula-AI.d`.

Useful parts of that repo:

- custom Aula client
- proof that relevant message endpoints exist

Do not copy over:

- FastAPI app
- Dash frontend
- agent scaffolding
- general AI chat wrapper code

A local inspection clone exists at:

- `/tmp/Aula-AI.d-ref`

## Constraints

- Keep the project small and dependable.
- Prefer CLI JSON output first.
- Do not build a web UI yet.
- Do not add broad agent infrastructure before the message pipeline is trustworthy.
- Keep tests fixture-backed where possible.
- Keep native Aula messaging clearly separated from provider-linked data such as Overblik or Meebook.

## Immediate Next Steps

1. Verify that `.aula_tokens.json` is reused across runs and document real behavior.
2. Improve auth ergonomics if fresh MitID prompts still happen too often.
3. Validate live `threads` and `messages` output against real Aula data.
4. Tighten normalization using real payload structure.
5. Add a first-pass importance classifier over normalized messages/threads.
6. Add a CLI command that outputs “important things to read” as JSON.
7. Only then evaluate whether an LLM/agent summarizer should be added on top.

## Definition Of Done For The Next Pass

- Repeated CLI runs usually reuse cached auth without requiring MitID every time.
- `threads` and `messages` work reliably against live data.
- The repo can identify likely-important Aula messages in a transparent way.
- There is a CLI command that emits prioritized or flagged messages as JSON.
- Tests cover normalization and the first-pass importance logic.
