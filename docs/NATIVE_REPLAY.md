# Native history and transparent forwarding

## Request behavior

Local replay records are an optional reconstruction cache, not authorization to
use a conversation. A missing record, restart, changed client/account/model,
changed assistant text, or edited session root no longer produces a local
`native_history_unavailable` rejection in the request path.

When an exact scoped record exists, the gateway can recover original block order
and an anonymous conversation identity. It never pulls another client's cached
text into a request. Without a match, it forwards the history supplied by the
caller; upstream validates the actual signatures and model support.

Anthropic assistant blocks retain their supplied order. OpenAI history is flattened:
without an original cached record, reconstruction uses thinking, text, then tool
calls. This cannot recover interleaving that the client did not preserve. An
upstream signature error is still possible; a local cache miss alone is not an error.

If tool-pair repair changes an assistant turn, the repaired ordinary transcript
is sent without attaching native reasoning to changed text/tool content. A missing
server-tool projection receipt falls back to the visible transcript, retaining
search results as text. Neither fallback invents signatures or new tool results.

## Stop hooks and requests without tools

The default `KIRO_TOOLLESS_NATIVE_HISTORY=transcript` handles Stop prompt hooks,
summarization, and other requests whose `tools` list is absent or empty. It omits
historical assistant thinking, signatures, and opaque reasoning before conversion,
while preserving ordinary answers and rendering tool calls/results as text.
Server-tool events retain their visible data. Reasoning-only turns receive an
omission marker. User content and nested tool arguments are not filtered.

This applies to all requests without tools, including ones that ask for thinking
in their new response. Current-response thinking controls are independent. The
historical value `strict` disables this transcript conversion; it no longer makes
local cache proof mandatory. An invalid setting remains a configuration error.

No extra opt-in is needed after updating the backend. Existing deployments that
explicitly set `strict` can remove that override or select `transcript`, then
restart the backend. This does not modify client history files.

## Optional persistent cache

- `KIRO_NATIVE_REPLAY_MODE=persistent` is the default; `memory` disables disk writes.
- `KIRO_NATIVE_REPLAY_DIR` defaults to `native-replay` beside `ACCOUNTS_STATE_FILE`.
  Tauri supplies the app data directory in development and packaged builds.
- `KIRO_NATIVE_REPLAY_MAX_BYTES=536870912` is the stored-value budget. Least-recently
  used evidence is evicted when full. SQLite overhead is additional.
- `history.sqlite3` is plain SQLite containing response text, native blocks and
  projection receipts. New files use owner-only creation permissions where supported.
  Older encrypted `replay.sqlite3`/`replay.key` files are not migrated or read.
- Cache startup/read/write errors are logged and degrade to memory or caller history.
  A failed cache write does not turn a completed model response into an API failure.
  Oversized individual cache entries are skipped. Corrupt files are not deleted.
- Credential-continuity digests are cache indexes, not upstream identity proof.
  An unavailable/stale disk binding falls back to process-local identity without
  overwriting a newer binding. In-flight credential replacement still triggers a
  retry before sending a payload prepared for a different credential snapshot.

## Other local compatibility checks

The forwarding adapters use model metadata for transport paths and optional
defaults. Missing/malformed metadata, unlisted effort values and cached output
limits no longer reject explicit Generate controls. Requested token counts are
not clamped. Disabling automatic additional fields does not discard explicit
client parameters. Upstream decides whether the selected model accepts them.

`output_config.format` is preserved for Generate and mapped to `text.format` for
Responses. JSON-schema formats receive the required default name `response` when
no name was supplied. Responses output limits and effort values are forwarded
without enforcing cached model limits/enums.
Additional Generate thinking options such as `thinking.display` are preserved.
Fields without a supported Responses mapping still produce a mapping error.

JSON types, positive token counts, valid wire encodings, finite resource budgets,
API authentication, HTTPS/Cloud routing, and protocol mappings are still checked.
For example, Responses has no established thinking-token-budget mapping; the
adapter reports that limitation instead of pretending the field was sent. Real
upstream refusals, capacity limits and authentication failures remain visible.

## Offline validation

Tests cover missing/changed scope, restart and cache corruption, streamed and
non-streamed output through both API adapters, ordered Anthropic native blocks,
OpenAI reconstruction, tool-free evaluator requests, server-tool results,
credential continuity, edited session roots, stale/missing model metadata,
structured output and unchanged caller data. These tests use synthetic streams
and no live account credentials; they do not certify acceptance by every upstream.
