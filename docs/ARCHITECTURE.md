# Architecture — sns-addict MVP

sns-addict should be a **local, single-tenant, safety-first Hermes plugin** that lets the owner supervise an Instagram persona. The MVP direction is to continue this repository rather than fork/rewrite it, but to harden the product into an agent-assisted approval system instead of a blind DM bot.

## Product decision

- **Keep:** Hermes plugin packaging, Patchright browser session, local dashboard, SOUL.md persona, event/state persistence, and existing guardrail modules.
- **Change:** expose product modes that make supervision explicit: `observe`, `approval`, `autopilot_lite`, and `stopped`.
- **Constrain:** no unsolicited first messages; no send without an allowlisted relationship; F3 plaintext capture only with collaborator consent.
- **Operate locally:** control surfaces bind to localhost by default and persist under `~/.hermes/sns-addict/`; non-local host binding should be treated as an explicit owner risk decision.

## Current implementation map

| Area | Existing files | Current role |
|---|---|---|
| Hermes registration | `sns_addict/__init__.py`, `plugin.yaml`, `pyproject.toml` | Registers the `sns_addict` platform and exposes the package entry points. |
| CLI | `sns_addict/cli.py` | `setup`, `dashboard`, `status`, and `stop` commands. |
| Setup/login | `sns_addict/setup_flow.py`, `sns_addict/browser/login.py`, `sns_addict/browser/session.py` | Installs Patchright/Chromium, creates local storage, installs `SOUL.md`, opens headful Instagram login, and updates Hermes config. |
| Browser automation | `sns_addict/browser/session.py`, `sns_addict/browser/selectors.py`, `sns_addict/actions/dm.py` | Headful Korean-locale Patchright profile and click/type DM actions. |
| Detection | `sns_addict/detection/dom_observer.py`, `sns_addict/detection/dispatcher.py` | Foreground-tab DOM polling/observer events. WebSocket/MQTT files are C2 placeholders. |
| Adapter | `sns_addict/adapter.py` | Hermes `BasePlatformAdapter` implementation, state watcher, browser lifecycle, LLM invocation, send, halt. |
| Inbound pipeline | `sns_addict/loops/inbound.py` | Bounded async pipeline: canary, quiet hours, loop detector, LLM, dedup, volume cap, send. |
| Guardrails | `sns_addict/guardrails/*.py` | Identity canary, quiet hours, volume cap, dedup, loop detector, cold-start grace, HALT_NOW watcher. |
| Dashboard | `sns_addict/dashboard/server.py`, `sns_addict/dashboard/routes/*`, `sns_addict/dashboard/static/*` | Local FastAPI app with status/start/stop, allowlist, live events, F3 toggle, persona, alerts, conversations API. |
| Persistence | `sns_addict/persistence/state.py`, `sns_addict/persistence/allowlist.py`, `sns_addict/persistence/events.py`, `sns_addict/persistence/conversations.py` | Atomic local JSON/JSONL state, allowlist, hashed event fields, and hashed thread conversation metadata/timestamps. |
| Future surfaces | `sns_addict/actions/group.py`, `sns_addict/actions/reels.py`, `sns_addict/actions/story.py`, `sns_addict/vision/reels_analyzer.py`, `sns_addict/vision/share_decision.py`, `sns_addict/loops/active_behavior.py`, `sns_addict/loops/mood_scheduler.py` | Existing code or placeholders for later cycles; not part of the safety-first MVP send path unless explicitly gated. |

## High-level runtime

```text
Owner CLI / Hermes plugin
  ├─ sns_addict.__init__.register(ctx)
  └─ sns_addict.cli setup|dashboard|status|stop

Local dashboard (localhost:8765)
  ├─ /api/control/*       -> writes ~/.hermes/sns-addict/state.json
  ├─ /api/allowlist/*     -> writes ~/.hermes/sns-addict/allowlist.json
  ├─ /api/monitoring/*    -> reads ~/.hermes/sns-addict/logs/events.jsonl
  ├─ /api/persona/*       -> edits ~/.hermes/SOUL.md
  └─ /ws/events           -> tails events.jsonl

Hermes adapter process
  ├─ SnsAddictAdapter._watch_state()
  ├─ BrowserSession(headful Patchright profile)
  ├─ DOM observer -> _on_dom_event() -> _process_inbound()
  ├─ InboundLoop guardrails
  ├─ Hermes auxiliary LLM + SOUL.md
  └─ DMActions.send() only after the selected product mode allows it
```

## Runtime modes

The product-facing modes below are the MVP contract. Current code has lower-level `State.session_state` values (`active`, `paused`, `stopped`, `halted`, `challenge_pending`) in `sns_addict/persistence/state.py`; the dashboard currently maps Start/Stop to `active`/`stopped` in `sns_addict/dashboard/routes/control.py`. The MVP should introduce or map explicit product modes without letting raw `active` mean “send automatically.”

| Mode | Owner intent | Send behavior | Implementation grounding |
|---|---|---|---|
| `stopped` | Browser/agent is off or halted. | Never send. | Existing `state.session_state = "stopped"`/`"halted"`; `HALT_NOW` in `sns_addict/guardrails/halt_now.py`; CLI stop in `sns_addict/cli.py`. |
| `observe` | Watch inbox and surface candidate activity only. | Never send; store/hash events and show in dashboard. | Existing DOM observer, events log, dashboard live tab. Needs mode gate before `InboundLoop` calls LLM/send. |
| `approval` | Draft persona replies for owner review. | Send only after owner approves a queued draft. | Existing `State.pending_sends` can be the seed. Needs approval queue routes/UI and a send-after-approval path. |
| `autopilot_lite` | Low-volume automatic replies to known collaborators only. | May reply only to explicit allowlist entries and only after all guardrails pass. No first messages. | Existing `AllowlistStore`, guardrails, and volume caps. Needs inbound allowlist gate and no-active-outreach enforcement. |

### Required mode invariants

1. `stopped` and `observe` must not call `DMActions.send()`.
2. `approval` may call `invoke_llm()` but must put drafts in an approval queue instead of sending directly.
3. `autopilot_lite` must verify allowlist membership before LLM/send and must never originate a first message.
4. `HALT_NOW` must override every mode.
5. Identity canary must remain first in any path that could send.

## Inbound flow target

Current `sns_addict/loops/inbound.py` is close to the technical pipeline, but the MVP product gate should sit before any automatic send:

```text
DOM event
  -> adapter._on_dom_event(event)             # non-blocking callback
  -> adapter._process_inbound(event)          # read latest thread text
  -> mode gate
      stopped        -> drop/log only
      observe        -> event/card only
      approval       -> guardrails + draft -> approval queue
      autopilot_lite -> allowlist + guardrails + send
```

For `approval` and `autopilot_lite`, the guarded path is:

```text
identity_canary
  -> HALT_NOW/stopped check
  -> allowlist relationship check
  -> quiet_hours
  -> loop_detector
  -> volume_cap precheck
  -> invoke_llm(SOUL.md + inbound text)
  -> dedup
  -> queue draft OR send
  -> record counters/events
```

Notes grounded in current code:

- `sns_addict/adapter.py` already avoids Hermes core `handle_message()` and calls `invoke_llm()` explicitly.
- `sns_addict/actions/dm.py` sends by clicking and humanized typing with no retry.
- `sns_addict/persistence/events.py` hashes `text` fields before writing to `events.jsonl`.
- Privacy gap: `sns_addict/detection/dom_observer.py` can emit a plaintext `preview`, `sns_addict/adapter.py` can forward it into event metadata, and `sns_addict/dashboard/static/app.js` currently renders event fields verbatim. C1 must either hash/redact preview-like metadata before persistence/WebSocket broadcast or clearly label live preview display as a local debugging-only leak.
- `sns_addict/adapter.py` currently writes plaintext assistant replies to `replies-f3.jsonl` when F3 mode is enabled; the dashboard route requires `collaborator_consent=True` before enabling F3.

## Approval queue architecture

The queue is the central product shift from bot to supervised persona.

### Draft lifecycle

```text
candidate_detected
  -> draft_requested
  -> draft_ready
  -> owner_approved | owner_edited | owner_rejected | expired | halted
  -> send_attempted
  -> sent | send_failed | lost
```

### Recommended local data model

Seed this from the existing `State.pending_sends` field in `sns_addict/persistence/state.py`, or split into a dedicated `approval_queue.jsonl` once queue operations become non-trivial.

Minimum fields:

- `id`: local queue id.
- `thread_id_hash`: SHA-256 prefix; never plaintext in logs.
- `thread_ref`: encrypted or process-local reference only if required for sending.
- `inbound_text_hash`: hash only by default.
- `draft_text`: plaintext assistant draft visible to the owner while pending.
- `mode`: `approval` or `autopilot_lite`.
- `guardrail_state`: pass/block details.
- `created_at`, `expires_at`, `approved_at`, `sent_at`.
- `owner_action`: `approved`, `edited`, `rejected`, `expired`.

### Queue API/dashboard surfaces

Existing dashboard foundations:

- `sns_addict/dashboard/server.py` mounts `/api/control`, `/api/allowlist`, `/api/monitoring`, `/api/persona`, `/api/alerts`, `/api/conversations`, and `/ws/events`.
- `sns_addict/dashboard/static/index.html` has Home, Allowlist, Live, and a disabled Conversations tab.

MVP additions should add:

- Queue tab: pending drafts, guardrail status, allowlist badge, quiet-hours badge.
- Approve/Edit/Reject controls.
- “Approve all” is a non-goal for C1.
- Emergency stop affordance visible on every screen.

## Hermes integration boundary

Use Hermes as the plugin host, not as an unbounded autonomous sender.

- Entry point: `sns_addict.__init__.register(ctx)`.
- Adapter factory: `sns_addict.adapter.create_adapter(cfg)`.
- Adapter contract: `connect`, `disconnect`, `send`, `get_chat_info` are implemented in `sns_addict/adapter.py`.
- LLM path: `SnsAddictAdapter.invoke_llm()` uses Hermes-auth auxiliary client and `~/.hermes/SOUL.md`.
- Do not call Hermes core `handle_message()` from sns-addict; this would bypass the product queue and guardrail sequencing documented in `docs/HERMES-INTEGRATION.md`.

## Safety and privacy principles

| Principle | MVP rule | Existing support | Gap to close |
|---|---|---|---|
| No unsolicited first messages | Never start a new conversation. | `sns_addict/actions/dm.py` only sends when called; `sns_addict/loops/active_behavior.py` is separable. | Keep `sns_addict/loops/active_behavior.py` out of C1/autopilot-lite, or hard-disable first sends. |
| Explicit allowlist | Only approved relationships can be drafted/sent. | `AllowlistStore` and dashboard allowlist routes exist. | Add inbound allowlist gate before draft/send. |
| Human supervision | Approval mode is default post-setup mode. | Dashboard and local state exist. | Add approval queue. |
| Identity canary | In send-capable modes, if asked whether this is AI/bot, send the canonical reply and halt. In `stopped`/pure `observe`, do not send; record/alert only. | `sns_addict/guardrails/identity_canary.py`. | Preserve as first send-capable guardrail and add mode-specific tests. |
| Quiet hours | No sending 02:00–08:00 local. | `sns_addict/guardrails/quiet_hours.py`. | Queue for morning in approval mode; do not drop silently. |
| Volume caps | Cap per day/per friend. | `sns_addict/guardrails/volume_cap.py`. | Precheck before draft/send and expose counters in dashboard. |
| Emergency stop | Owner can halt immediately. | `HALT_NOW`, `/api/control/stop`, CLI `stop`. | Clear recovery UX: show halted reason and require owner action to resume. |
| F3 plaintext capture | Only for tests with collaborator consent. | `/api/control/f3_mode` requires consent. | Ensure docs/runbooks keep F3 off by default and never capture inbound plaintext without consent. |

## Non-goals for C1 MVP

- Multi-tenant hosting, cloud dashboard, remote control, or shared credentials.
- Growth automation, scraping, mass DM, engagement farming, or cold outreach.
- First-message initiation, even to allowlisted users.
- Group DM autonomy, Reels/story sharing autonomy, or vision-based proactive recommendations.
- Background-tab reliability guarantees; current DOM detection requires a foreground tab.
- Automatic challenge/ban recovery.
- Plaintext transcript storage outside explicit F3 test windows with collaborator consent.

## Known architecture gaps

1. Product modes are not first-class yet; current dashboard exposes `active`/`stopped` only.
2. Inbound allowlist gating is not yet visible in `InboundLoop`.
3. Allowlist entries currently model usernames while the adapter works with Instagram thread IDs/hrefs; C1 needs a safe relationship resolver/mapping.
4. Approval queue routes/UI are not yet implemented.
5. `sns_addict/loops/active_behavior.py` can initiate DMs if called; C1 must keep it disabled or refactor it behind no-first-message policy.
6. DOM detection in `sns_addict/detection/dom_observer.py` depends on a foregrounded Instagram tab.
7. Live event metadata may still contain plaintext `preview` fields despite hashed `text` handling; C1 must redact/hash those fields before claiming plaintext-free default logs.
8. Some existing docs mention stale paths; this architecture file uses current repo paths.

## Verification plan

- Run unit tests without changing code: `python -m pytest -q`.
- Static docs sanity: confirm all cited repo paths exist.
- Manual setup smoke: `sns-addict setup` creates `~/.hermes/sns-addict/` storage and persistent browser profile.
- Dashboard smoke: `sns-addict dashboard --host 127.0.0.1 --port 8765` serves Home/Allowlist/Live tabs.
- Mode safety tests to add with implementation: observe never sends, approval queues drafts only, autopilot-lite blocks non-allowlisted threads, HALT_NOW overrides all modes.
- Privacy regression test to add: default `events.jsonl` and live dashboard payloads do not expose inbound plaintext `text` or `preview` fields.
- F3 live tests only after collaborator consent, using `docs/RUNBOOK-W2-W3-F3.md`.

## Next cycles

- **C1:** local setup/login, observe mode, approval queue, allowlist gate, emergency stop, F3 consent, dashboard clarity.
- **C2:** realtime detection hardening, conversation review tab, morning queue delivery, richer alerting.
- **C3:** optional autopilot-lite expansion after evidence, stricter policy tests, group/Reels/story decisions only if they preserve no-first-message and allowlist rules.
