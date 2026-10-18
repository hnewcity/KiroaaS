# Native reasoning history: long conversations and restart recovery

## Behavior

Native thinking is durable conversation evidence, not an hour-long bearer token.
The gateway preserves its account/client/model and original-content checks, but no
longer expires proof one hour after generation. It never drops thinking silently or
accepts unknown client signatures merely because the local cache is empty.

By default, complete native responses and complete server-tool projection receipts
are committed to `history.sqlite3`. The 512-record / 16 MiB memory cache
is only an accelerator: cold misses recover the original record from disk. Both API
surfaces and streaming/non-streaming paths share the same ledger. Incomplete or
failed streams do not register completed proof. No automatic retention timer is set.

This follows the CLI principle that persisted history, rather than process-local
cache residency, is authoritative. It is deliberately not a byte-for-byte copy of
the CLI: this gateway accepts external histories and reconstructs flattened or
server-tool-adapted messages, so it must retain its extra provenance/isolation proof.
It does not silently apply the CLI's model-switch reasoning stripping policy.

## Storage and privacy

- `KIRO_NATIVE_REPLAY_MODE=persistent` (default); `memory` explicitly disables disk
  retention, but restart and RAM eviction then lose proof.
- `KIRO_NATIVE_REPLAY_DIR`: a private directory, defaulting to `native-replay` beside
  `ACCOUNTS_STATE_FILE`. Tauri sets it to `native-replay` in the application's data
  directory for both development and packaged runs.
- `KIRO_NATIVE_REPLAY_MAX_BYTES=536870912`: stored-value budget (512 MiB). SQLite
  page/journal overhead is additional. When full, the least recently used conversations
  are evicted so new requests keep working; an evicted chat then returns
  `native_history_unavailable`. A single entry larger than the budget stays in RAM only.
  Account bindings are never evicted.
- `history.sqlite3` is a plain SQLite file. It contains native thinking, original
  response text, tool data and projection receipts: treat it as private conversation
  history, like the credential files beside it. New files are created owner-only
  (0700 directory, 0600 file); permissions are not enforced at startup. No raw
  credentials are stored; credential continuity uses keyed digests.
- Each row embeds its own kind and key, so corrupt or swapped rows fail closed
  instead of being treated as missing history.
- To erase all retained proof, stop every gateway process using the directory and
  delete `history.sqlite3`. This invalidates its old chats.
- Earlier builds wrote an encrypted `replay.sqlite3` plus `replay.key`. Those files are
  ignored (a warning is logged) and can be deleted; their histories are not migrated.

## Account continuity

The existing `credential_generation` remains process-local and guards in-flight
requests against credential replacement. Replay uses a separate persistent opaque
binding, recovered only when keyed credential-source snapshots match. The namespace
(account ID/path) partitions the records but is not itself identity proof.

Gateway-owned successful refresh writes preserve continuity. External credential
replacement changes the binding, and a stale manager cannot overwrite a newer
binding created by another process. A refresh performed by another application may
still count as external replacement: these are source-continuity checks, not verified
provider principal IDs. Client credentials and normalized model must also match.

## Upgrade limitations and diagnostics

There is no way to recover proof that the previous memory-only implementation has
already expired, evicted or lost during restart. Such old histories still return
`native_history_unavailable`; start a new chat and transfer necessary ordinary-text
context once. Newly recorded histories are resumable under the rules above.

Unreadable/corrupt storage and changed cross-process
account bindings produce actionable distinct storage messages. Storage errors never
fall back to unverified replay. This removes the gateway's one-hour restriction; it
does not override upstream context limits, upstream signature validity or account
changes, and it does not certify native support for an untested live deployment.

## Offline validation

Coverage includes long/overnight history, more than 512 original records, a fresh
Python process reopening stored evidence, ordinary and projected histories across
both APIs, normal refresh and source replacement, independent request generations,
concurrent initialization, LRU eviction, corrupt/swapped rows, legacy files, explicit
memory opt-out, and malformed configuration. No real accounts or upstream requests
are used by these tests.
