# Kiro CLI alignment: implementation and acceptance

## Status

The accepted implementation scope is wired into the application, not just helper
modules. Offline tests and the Rust check pass. **Bounded live requests were
explicitly authorized and performed on 2026-10-14.** Generate, basic Responses,
and a harmless tool continuation succeeded. Optional native-system/output-limit
fields were rejected by the tested account/deployment; native reasoning and Cloud
acceptance remain unverified. Do not read the historical authorization audits below
as current instructions or treat these results as an unrestricted rollout approval.
No installed app or remote relay deployment was changed.

## Entry points and rollout

Use `python app_entry.py` from `python-backend`, or `uvicorn app_entry:app`.
Tauri and the PyInstaller spec use this entry point; Docker now does too.
`main.py` contains the upstream FastAPI application but direct `main:app` loading
does not install the whole local compatibility stack.

Default rollback-compatible routing:

```dotenv
KIRO_PROTOCOL_PROFILE=legacy
KIRO_GENERATION_PROTOCOL=generate
KIRO_NATIVE_SYSTEM_PROMPT=false
```

Explicit CLI RPC rollout (independent of native-system entitlement):

```dotenv
KIRO_PROTOCOL_PROFILE=cli
KIRO_GENERATION_PROTOCOL=generate
KIRO_NATIVE_SYSTEM_PROMPT=false
```

Set `KIRO_NATIVE_SYSTEM_PROMPT=true` only after verifying that the account enables
that field. CLI routing does not imply native-system entitlement. The live-tested
account rejected this field; disabling it retains the explicit legacy history-prefix
representation rather than silently changing a failed request.

Experimental raw Responses rollout:

```dotenv
KIRO_PROTOCOL_PROFILE=cli
KIRO_GENERATION_PROTOCOL=responses
KIRO_NATIVE_SYSTEM_PROMPT=false
```

Responses acceptance is still field-specific: the tested deployment accepts a
minimal request but rejects `max_output_tokens`, so this recipe does not by itself
make Anthropic's required output limit usable.

Restart the backend after changing settings. Roll back by restoring the three
legacy values above and restarting; do not rewrite stored conversations or
credentials. Source-specific capability validation and corrected decoding remain
bug fixes, not a return to silent argument changes or data loss.

## Implementation/evidence matrix

| Requirement | Implementation | Offline evidence |
| --- | --- | --- |
| Error-aware recovery and one coordinated refresh | `extensions/retry_policy.py`, `upstream_retry.py` | retry-policy, upstream-retry and auth tests |
| Closed abandoned/cancelled streams, stable request ID and real attempts | retry transport + shared parser | retry/stream/native-flow regressions |
| Kiro millisecond and HTTP-date hints; no assumed independent 429 buckets | retry policy | hint parsing, exhausted status and no-rotation tests |
| Inference budget separate from control discovery | operation-aware retry | `test_protocol_routing.py` pagination/budget assertions |
| Independent mode/task and conversation/root/turn IDs | session registry + request context | session identity, payload and route tests |
| Credential replacement cannot reuse old native context | credential epochs, account binding and pre-send guard | auth/credential tests and same-source send-block regression |
| Tool schema constraints/references survive | bounded semantic normalizer | 170 dedicated tests plus installed converter tests |
| Schema-driven effort/thinking/output controls | model capabilities + actual converter hooks | capability/payload/API validation tests |
| Native enabled/disabled/adaptive and advertised budgets | capability builders | budget, conflict, no-clamp and default tests |
| Text/signature/opaque stream and history round-trip | decoder, native ledger/store, both API adapters | `test_native_reasoning_flow.py` four-way flow |
| Gateway server-tool projections preserve signed history | projection receipts and canonical restoration | native projection/server-projection tests through real conversion |
| Reported model ownership, no conflicting-owner record | model metadata decoder + replay scope | resolved/conflicting model regressions |
| Coherent origins/targets/auth/UA/privacy | protocol profiles/runtime routing | profile unit tests + installed route matrix |
| Native systemPrompt with no duplicate history prefix | payload builder | route matrix wire assertions |
| CLI management/models/usage/profiles/MCP routing | operation serializer + actual call sites | control routing, profile autofetch, MCP tests |
| Complete bounded model pagination | control operation collector | pagination, repeated-cursor and budget tests |
| Safe explicit control fallback | unknown-operation-only fallback | no fallback on permission/429 tests |
| Responses request/SSE/tools/usage/errors/incomplete | actual retry entry + stream adapter | Responses decoder tests, routing and route matrix |
| Cloud management/RPC/SSE forwarding or fail-closed | Cloud connector + required-route guards | Cloud allowlist/forwarding tests + route matrix |
| Sensitive diagnostic data is not retained | pre-buffer redaction/summaries | redaction/logger/middleware tests |
| All API/output/profile/transport paths exercised | installed FastAPI routers + fake Kiro/relay | 24-case generation route matrix |

The matrix proves local implementation and offline behavior. It does not prove
account entitlement, remote relay deployment, or cloud acceptance of an experimental
field. These are explicit live gates below.

## Wire provenance

Reference: supplied CLI 2.29.1, shipped `@kiro/agent 0.66.33`.
Original ACP bundle SHA256:
`ca0672e74c07a925cbeee0558e5e14bb77561deb2ffa0dc2d40ed4a72b441eba`.
AST-verified readable bundle SHA256:
`bf8e9dd69e0381c924abb4b764fc3acae5844d7e0ee8e0abfd8501b974dc4e90`.
The readable hash was rechecked during implementation. LF line numbers and contract
provenance are saved in `python-backend/tests/fixtures/kiro_cli_2_29_1/static-contract.json`.
These are static contracts, not network captures; reconstructed native code was not
used as protocol proof.

The actual runtime factory selects AwsJson1_0Protocol and KiroRuntimeService
(LF528119-528146,185082-185091), whose serializer sends:

```http
POST https://runtime.<region>.kiro.dev/
Content-Type: application/x-amz-json-1.0
x-amz-target: KiroRuntimeService.GenerateAssistantResponse
```

The REST annotation does not select this wire path. `agentMode` is serialized in
RPC JSON (LF182252-182266), not removed merely because it carries an httpHeader
annotation. Management has its own service targets. InvokeMCP takes the modeled
JSON-RPC id/method/jsonrpc/params/profileArn body (LF184728-184744,531492-531533).

Raw Responses uses `/v1/responses`. Its operation models `maxOutputTokens` with
JSON name `max_output_tokens` (LF184375/184380,184557-184579). The gateway preserves
client max_tokens through that global operation field; it does not mistake absence
of Generate's per-model max_tokens property for lack of a Responses output limit.
This compatibility mapping is schema-backed, not something source `luo` emits.

## Configuration and behavior

| Setting | Default | Behavior |
| --- | --- | --- |
| KIRO_PROTOCOL_PROFILE | legacy | legacy or cli operation contracts |
| KIRO_GENERATION_PROTOCOL | generate | generate or explicit experimental responses |
| KIRO_NATIVE_SYSTEM_PROMPT | false | Native system field, no duplicate prefix |
| KIRO_CONTENT_COLLECTION_ENABLED | false | Opt-out applies to inference/control/MCP |
| KIRO_CONTROL_PLANE_FALLBACK | false | One legacy fallback only for definite UnknownOperation |
| KIRO_RUNTIME_ENDPOINT | derived | Optional HTTPS origin override |
| KIRO_MANAGEMENT_ENDPOINT | derived | Independent HTTPS management origin |
| KIRO_LEGACY_Q_ENDPOINT | derived | Independent legacy control/MCP origin |
| KIRO_MAX_UPSTREAM_ATTEMPTS | 6 | Shared inference-send budget within one client request |
| KIRO_UPSTREAM_REQUEST_DEADLINE | 300 seconds | Transport/auth/backoff/first-response waiting budget |
| STREAMING_READ_TIMEOUT | existing app setting | Body read-idle limit, not total response lifetime |
| KIRO_STREAM_TOTAL_TIMEOUT | 0 | Explicit optional hard successful-stream lifetime |
| KIRO_ADDITIONAL_MODEL_FIELDS | true | Native fields; disabling rejects explicit controls instead of ignoring them |
| KIRO_LEGACY_FAKE_REASONING | false | Explicit legacy text tags, separate from native reasoning |
| KIRO_ALLOW_ADDITIONAL_FIELDS_FALLBACK | false | Explicit unsupported-field deletion with bounded scoped TTL |
| STABLE_CONVERSATION_ID | true | Recognize explicit session metadata, never prompt-hash identity |
| KIROAAS_APP_VERSION | source manifest / launch env | Truthful gateway version; frozen fallback is unversioned |

Control-plane calls have independent command IDs and attempt counts. They share
an enclosing request's elapsed-time deadline, not its inference send count. Model
discovery follows at most ten pages and rejects repeated cursors/partial failures.
A successful active generation is not cut off simply because a retry budget expires;
use the separate hard stream limit only when intended.

Both API routes accept optional X-Kiro-Session-Id, X-Kiro-Root-Session-Id,
X-Kiro-Turn-Id, X-Kiro-Agent-Mode and X-Kiro-Task-Type. Root/turn require a session;
IDs allow 1-256 non-whitespace printable ASCII characters. Duplicate/invalid values
are rejected. Tools do not select Spec mode. Equivalent bearer/x-api-key values
share the same client namespace across API surfaces.

Session registry: 1024 sessions, 32 remembered turns each, one-hour sliding TTL.
Explicit turn IDs remain deterministic after registry eviction; implicit turns may
get a new continuation. Native replay has no automatic time expiry. A 512-record,
16 MiB RAM accelerator fronts an encrypted persistent ledger (default logical-value
budget: 512 MiB). RAM eviction and process restart reload the original scoped record
and complete projection receipts; they no longer invalidate signed history. A message
ledger remains limited to 16 MiB and 4096 blocks. Explicit memory mode opts out of disk
retention and therefore cannot recover evicted/lost evidence. See NATIVE_REPLAY.md.
OpenAI clients must preserve reasoning_details. Actual signatures/opaque bytes are
not fabricated or converted to prompt text. Missing/altered/unverified state still
fails closed; persistence does not authorize arbitrary imported history or locally
verify the upstream cryptographic signature.

Credential generations distinguish an auth manager's own successful refresh from
externally reloaded/replaced credentials. They are not verified JWT/principal IDs.
A separate encrypted credential-continuity binding lets unchanged sources and the
gateway's own refresh writes recover native replay after restart. The in-flight
credential generation remains process-local; account labels/paths alone never prove
continuity. External rotation may invalidate native replay. Changes are noticed on loader reads
and refresh rechecks, not by continuous filesystem watching or cross-process locking.
An in-flight source replacement yields an actionable 409 before the prepared payload
is sent. The next request binds the new epoch.

Responses thinking budgets have no verified wire mapping and are rejected explicitly;
use Generate with an advertised budget instead. Disabled Responses thinking maps to
reasoning effort none; conflicting explicit effort is rejected. Enabled/adaptive
thinking requires a usable advertised/explicit effort. No model-name defaults or
silent token-limit clamps are introduced. Reported provider model IDs are exposed
as kiro_upstream_model without overwriting public model aliases.

## Cloud and diagnostic privacy

Cloud mode requires an installed transport, valid HTTPS relay URL and sign-in key.
Missing settings or unsupported selected hosts are errors, never implicit direct
connections. Approved management hosts are forwarded with the original target URL,
operation headers and exact payload SHA256. Bearer credentials use the relay's
existing protected forwarding header, not the CloudFront Authorization slot.
Redirect following is disabled for upstream operations. The remote relay must also
allow management hosts and preserve RPC/SSE; client tests do not deploy that policy.

Debug copies are sanitized before buffering/writing. Raw wire chunks retain only
size/hash summaries; complete JSON/SSE has native opaque/signature and credential
fields redacted; malformed fragments fail closed. Captured application logs and
free-form error text are summaries. Cleanup replaces only owned diagnostic files,
never recursively deletes a configured directory or unrelated files.

## Verification and remaining live gate

Run from the repository root:

```powershell
python -X utf8 -m pytest -q --tb=short -W error::RuntimeWarning -W error::pytest.PytestUnraisableExceptionWarning
```

The root pytest.ini collects offline backend tests only; it cannot accidentally
import the real-account manual_api_test.py. UTF-8 reads are explicit for the Windows
credential-migration fixture.

Recorded checkpoints:

- Initial read-only audit: 173 extension tests, which missed the observed defects.
- First implementation pass: 2259 tests and 209 subtests.
- Native/protocol-component pass: 3404 tests and 213 subtests.
- Integrated routing pass: 3591 tests and 213 subtests; only the existing dependency
  deprecation warning, with RuntimeWarning/unawaited-coroutine warnings treated as errors.
- `cargo check --offline`: successful for kiroaas 1.3.0.
- PyInstaller backend build and read-only `--help` smoke: successful in an owned
  verification directory; final rebuild after the last source changes is recorded
  separately below. No installed app or release archive was overwritten.

Explicit authorization was received on 2026-10-14 and the supported-path live
checks are recorded below. Native reasoning and optional field acceptance still
require a representative enabled account; Cloud additionally requires an existing
configured relay. Record only sanitized statuses/usage, never credentials or opaque
native payloads. An unsupported account/relay feature is an external capability
constraint, not permission to discard client parameters or bypass the relay.

## Historical local verification checkpoint — 2026-10-14

- Current source suite: **3591 passed, 213 subtests passed**, with RuntimeWarning
  and unawaited-coroutine warnings treated as errors. The single remaining warning
  is the installed Starlette/httpx deprecation notice.
- `cargo check --offline`: passed.
- Final PyInstaller rebuild: passed in the existing, path-verified owned directory
  `python-backend/build/verification-39d2354b0b` without touching release archives.
- Frozen executable `--help`: passed with CLI/Responses/native-system settings and
  credential inputs cleared. Required protocol, reasoning, credential and diagnostic
  modules were verified present in PYZ. Artifact evidence is `verification.json`
  in that directory. The build reports an optional tzdata hook warning; no named
  ZoneInfo database is used by these request paths.
- Frozen EXE SHA256: `22260881e3deed41d57dc84fa260e1c85165ffa3b80eab4294ff05583fc770f5`.
- Compileall and diff whitespace checks passed. No commits, server deployments, or
  real Kiro account calls were made. All owned agents/build/test sessions finished.
- Outstanding gate: explicit authorization for bounded real-account/cloud acceptance.
  This is the first request for that authorization; the goal remains active and is
  not marked complete or blocked on this first occurrence.

## Historical post-build completion audit — 2026-10-14

Revalidated the current checkout against the frozen artifact without executing it
or making network calls. The executable hash still matches verification.json;
its embedded PYZ exactly matches the audited PYZ. All **64** local application
modules/scripts match freshly compiled current source after normalizing only
co_filename recursively. There are **zero mismatches**. Evidence is
`python-backend/build/verification-39d2354b0b/source-bytecode-audit.json`.

No new human authorization was received for billable real-account acceptance.
The automatic goal continuation is not that authorization. This is the second
consecutive goal turn with the same remaining external gate. Local verification
has advanced, but the full goal still cannot be marked complete. No live Kiro
request, credential discovery, or deployment was performed.

## Historical blocked audit — 2026-10-14 (authorization since resolved)

The live-acceptance authorization gate remains unchanged for a third consecutive
goal turn. Current source was recompiled and compared again: 64 modules/scripts,
zero structural mismatches with the audited frozen build. The comparison explicitly
checks recursive CodeType values rather than reference-sensitive marshal encodings;
a temporary all-module marshal-byte mismatch was a reference-encoding artifact, not
a source change. Evidence: structural-bytecode-audit.json in the verification build.
No additional local implementation work is outstanding in the accepted scope.
At that checkpoint, automatic continuation was not human authorization for billable
requests and the goal was marked blocked. The user subsequently provided explicit
authorization; this historical gate is resolved.

## Authorized live acceptance — 2026-10-14

Credential discovery was limited to the application's configured and known Kiro
locations. The active CLI database was in `%LOCALAPPDATA%/kiro-cli/data.sqlite3`,
not `%APPDATA%`. The existing social credential refreshed successfully through the
normal auth manager. No account credentials, signed reasoning, or raw stream bytes
were retained in the report. App configuration and installed artifacts were not
changed; API probes ran through `app_entry` in an in-process ASGI client.

The advertised test model was `claude-haiku-4.5`. Probes asked for `OK`, or called
a local echo-shaped tool whose result was supplied in memory without executing a
shell command. Each inference probe used a one-send transport budget, with bounded
elapsed time and no implicit control/parameter fallback.

| Check | Observed result |
| --- | --- |
| CLI management ListAvailableModels | HTTP 200; 9 models, none advertising additionalModelRequestFieldsSchema |
| CLI management GetUsageLimits | HTTP 200 |
| CLI Generate without native systemPrompt | HTTP 200, exact OK; native eventstream decoded |
| Legacy Generate through OpenAI API | HTTP 200, exact OK and normal stop |
| CLI Generate through OpenAI API, both output modes | HTTP 200, exact OK, normal completion, no SSE error |
| Basic Responses without instructions or explicit output limit | HTTP 200, exact OK; SSE decoded |
| Responses through streaming OpenAI API without those fields | HTTP 200, exact OK, stop and DONE marker |
| Generate tool call and result continuation | Both HTTP 200; echo_probe arguments preserved, final exact OK |
| Native systemPrompt enabled, Generate | HTTP 400 REQUEST_BODY_INVALID; the coarse error alone does not establish the cause |
| Native systemPrompt enabled, Responses | HTTP 400 unsupported_parameter; explicitly says systemPrompt is not enabled for this user |
| Responses with an explicit output limit via Anthropic | HTTP 400 unsupported_parameter, param=max_output_tokens; the minimal request without that limit succeeded |

The output-limit result is a deployment/account observation, not a claim that the
CLI operation schema lacks the modeled field. Explicit max_tokens is preserved;
it is not discarded to manufacture a passing test. Generate also conservatively
rejects explicit model controls when its model metadata does not advertise their
schema. Consequently, this account cannot currently pass ordinary Anthropic
requests requiring max_tokens under the strict policy. Enabling Responses does
not resolve that limitation on this tested deployment.

### Live-discovered error fix

Responses HTTP failures contain `error.message`, `error.code`, and optionally
`error.param`, unlike Generate's flat error body. The public routes previously
reduced this nested body to `Unknown error`. The shared error enhancer now preserves
the actual message, code/type and a bounded parameter path, while retaining existing
Generate enhancement behavior. Malformed nested values are ignored instead of
stringified. Regression coverage exercises both APIs, both output modes, direct
and Cloud transports, and single-account/account-system routes without network I/O.

After the fix, the live Anthropic request retained HTTP 400, the service's actual
unsupported-parameter message, and `parameter: max_output_tokens`, rather than
returning `Unknown error`. Generate's missing-schema rejection was also verified
through the Anthropic route without bypassing the conservative capability policy.

### Remaining acceptance boundaries

- Native reasoning signatures/redacted history are covered by offline round trips,
  not a successful live native-reasoning request on this account. No capability
  schema was advertised and no unverified thinking parameters were forced.
- Native system fields and explicit output-limit fields need an enabled account or
  upstream support. No repeated permission request is outstanding.
- Cloud is disabled and no relay session is configured. No credentials were sent
  to a new relay and no Cloud deployment was made.
- These limitations remain explicit; the full feature matrix is not claimed to
  have passed live merely because local tests and supported request paths pass.

Sanitized per-probe evidence is under the owned verification build directory:
`live-control-results.json`, `live-compatible-results.json`, `live-api-results.json`,
`live-tool-and-limit-results.json`, `live-postfix-results.json`, and
`live-final-limit-results.json`. Pre-fix error
records are intentionally retained as historical evidence, not current behavior.

## Post-live-fix verification — 2026-10-14

- Full current-source suite: **3628 passed, 213 subtests passed**. RuntimeWarning
  and unraisable-coroutine warnings were errors; only the pre-existing installed
  Starlette/httpx deprecation warning remains. This adds 37 regression cases.
- Compileall and `git diff --check`: passed. Rust sources did not change after
  the previously successful `cargo check --offline`.
- New isolated PyInstaller build: `python-backend/build/verification-live-20261014`.
  The earlier build and its pre-fix evidence were preserved, not overwritten.
- Frozen executable: `dist/kiro-gateway/kiro-gateway.exe` within that directory.
- Frozen EXE SHA256: `32e89120cc02f259ed38fbfe888ba3006616bd50338b0e734a70ec23e8f64908`.
- Credentials-cleared `--help` smoke: passed with CLI/Responses/native-system
  settings. It did not start the server or perform account requests.
- All **64** application modules/scripts structurally match current source in the
  actual executable; the bundled `.env.example` also matches. Audit and manifest:
  `structural-bytecode-audit.json` and `verification.json` in the new build directory.
- The optional tzdata build warning is unchanged. No installed app, release archive,
  or remote deployment was overwritten. Changes were uncommitted at this
  verification checkpoint; subsequent Git submission does not imply deployment.
- This checkpoint completes the live-discovered error repair, not successful live
  acceptance of unavailable native/Cloud capabilities. The overall feature matrix
  remains explicitly incomplete for the reasons above.
