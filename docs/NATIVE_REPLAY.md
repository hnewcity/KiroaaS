# Native reasoning history: long conversations and restart recovery

## Behavior

Native thinking is durable conversation evidence, not an hour-long bearer token.
The gateway preserves its account/client/model and original-content checks, but no
longer expires proof one hour after generation. It never drops thinking silently or
accepts unknown client signatures merely because the local cache is empty.

By default, complete native responses and complete server-tool projection receipts
are encrypted and committed to `replay.sqlite3`. The 512-record / 16 MiB memory cache
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
- `KIRO_NATIVE_REPLAY_MAX_BYTES=536870912`: encrypted-value budget (512 MiB). SQLite
  page/journal overhead is additional. When full, new evidence writes fail explicitly;
  existing conversations are not silently evicted. Increase the budget to continue.
- SQLite contains Fernet-authenticated encrypted records and keyed lookup indexes.
  Payload identity is authenticated as well, so swapping ciphertext rows fails closed.
  The ledger contains native thinking, original response text, tool data and projection
  receipts: treat it as private conversation history, not as disposable debug logs.
- `replay.key` is separate. On Windows its content is protected with current-user
  DPAPI (not machine-wide DPAPI). On other platforms the directory/key must be owner-only
  (0700/0600). POSIX protection relies on those filesystem permissions; it is not an
  OS-keystore implementation. An attacker with both plaintext key and database can
  decrypt it. Neither platform logs decrypted evidence or stores raw credentials.
- Back up both files. A Windows key is tied to its user's DPAPI environment: copying
  both files to an unrelated machine/user is not a supported restore mechanism.
  A missing/invalid key is an explicit error, never silently replaced for an old DB.
- To erase all retained proof, stop every gateway process using the directory and
  explicitly delete the whole dedicated replay directory. This invalidates its old
  chats. Do not delete just the key, copy a live DB, or clear it as ordinary log cleanup.

The new dependency is `cryptography>=44.0.0`; reinstall backend requirements and
rebuild packaged backends when upgrading. An already-running/frozen old executable
will not pick up source changes.

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

Storage-full, unreadable/corrupt storage, missing keys and changed cross-process
account bindings produce actionable distinct storage messages. Storage errors never
fall back to unverified replay. This removes the gateway's one-hour restriction; it
does not override upstream context limits, upstream signature validity or account
changes, and it does not certify native support for an untested live deployment.

## Offline validation

Coverage includes long/overnight history, more than 512 original records, a fresh
Python process reopening encrypted evidence, ordinary and projected histories across
both APIs, normal refresh and source replacement, independent request generations,
concurrent initialization, quota failure, corrupt/swapped rows, missing keys, explicit
memory opt-out, and malformed configuration. No real accounts or upstream requests
are used by these tests.
