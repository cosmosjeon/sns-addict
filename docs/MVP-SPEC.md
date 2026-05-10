# MVP Spec — sns-addict C1 safety-first product plan

## One-line goal

Turn the existing sns-addict repo into a **local, single-tenant Hermes plugin for a supervised Instagram persona**: observe first, queue persona drafts for approval, and only allow tightly constrained autopilot-lite for allowlisted friends.

## C1 scope

C1 is the safety-first MVP. It proves that the current codebase can become a controlled Hermes persona without a fork/rewrite.

### In scope

- Local install/setup/login through existing CLI/setup flow.
- Local dashboard as the owner control plane.
- Explicit product modes: `stopped`, `observe`, `approval`, `autopilot_lite`.
- Observe-only default after setup/login.
- Allowlist management before any draft/send.
- Approval queue for generated persona replies.
- Hermes/SOUL.md-based drafting.
- Guardrail-preserving send path.
- Emergency stop through dashboard, CLI, and `~/.hermes/HALT_NOW`.
- F3 plaintext assistant-reply capture only with collaborator consent.
- Verification that current code paths are not used for unsolicited first messages.

### Out of scope / non-goals

- Forking or rewriting the project.
- Multi-user/multi-tenant SaaS or remote dashboard access.
- Instagram growth automation, scraping, mass DM, or engagement farming.
- Any unsolicited first message.
- Autonomous group DMs, story reactions, Reels sharing, or active outreach.
- Background-tab detection guarantees.
- Automatic recovery from Instagram challenges/bans.
- Plaintext capture outside explicit F3 test windows.

## Current code baseline

| Capability | Existing grounding | C1 status |
|---|---|---|
| Hermes plugin | `sns_addict/__init__.py`, `plugin.yaml`, `pyproject.toml` | Keep. |
| Setup/login | `sns_addict/setup_flow.py`, `sns_addict/browser/login.py`, `sns_addict/browser/session.py` | Keep; default to non-sending product state. |
| Dashboard | `sns_addict/dashboard/server.py`, routes/static files | Extend with modes and queue. |
| Browser DM send/read | `sns_addict/actions/dm.py` | Keep; only reachable after mode+queue+guardrail checks. |
| DOM detection | `sns_addict/detection/dom_observer.py` | Use for observe/approval; foreground-tab caveat. |
| Adapter lifecycle | `sns_addict/adapter.py` | Keep; add product mode gates around LLM/send. |
| Inbound guardrail pipeline | `sns_addict/loops/inbound.py` | Refactor from direct-send pipeline to mode-aware queue/send pipeline. |
| Allowlist | `sns_addict/persistence/allowlist.py`, dashboard route | Make mandatory before draft/send. |
| State/events | `sns_addict/persistence/state.py`, `events.py` | Extend for product modes and approval queue. |
| Emergency halt | `sns_addict/guardrails/halt_now.py`, `sns_addict/cli.py`, control route | Keep and elevate in UI. |
| F3 testing | `SnsAddictAdapter._append_f3_reply()`, `/api/control/f3_mode`, runbook | Keep consent-gated. |
| Active behavior | `sns_addict/loops/active_behavior.py` | Exclude from C1 send path. |

## Product requirements

### R1 — local single-tenant operation

- Dashboard binds to localhost by default (`127.0.0.1`, port 8765).
- Local files live under `~/.hermes/sns-addict/` and `~/.hermes/SOUL.md`.
- No server-side shared tenant state is introduced.

### R2 — explicit modes

The product must expose these modes:

| Mode | Requirement |
|---|---|
| `stopped` | No browser actions that can send; stop/halt reason shown. |
| `observe` | Detect/log/display activity only; no LLM send and no `DMActions.send()`. |
| `approval` | Generate drafts only for allowlisted inbound threads; send only after owner action. |
| `autopilot_lite` | Automatic replies only for allowlisted inbound threads after all guardrails pass. |

Raw implementation states such as `active` must not be presented as “bot is free to send.”

### R3 — no unsolicited first messages

- C1 must never originate a conversation.
- `sns_addict/loops/active_behavior.py` and proactive actions must not be wired into C1.
- Autopilot-lite means “automatic reply to eligible inbound,” not outreach.

### R4 — explicit allowlist

- Non-allowlisted threads are observe-only.
- Allowlist entries are managed through `AllowlistStore` and dashboard routes.
- Draft/send paths must check allowlist before LLM/send.

### R5 — approval queue

- Approval mode creates queue items, not sends.
- Owner can approve, edit+approve, reject, or stop.
- Approved send uses existing `SnsAddictAdapter.send()` once.
- Failed sends are not retried automatically.

### R6 — guardrails stay mandatory

Before any send-capable action:

1. HALT_NOW/stopped check.
2. Identity canary first when inspecting message content.
3. Allowlist gate.
4. Quiet hours.
5. Loop detector.
6. Volume cap.
7. Dedup.
8. Fire-and-best-effort send.

Existing modules: `sns_addict/guardrails/halt_now.py`, `identity_canary.py`, `quiet_hours.py`, `loop_detector.py`, `volume_cap.py`, `dedup.py`.

### R7 — privacy and F3

- Default logs must not contain inbound plaintext.
- `sns_addict/persistence/events.py` hashes any `text` field before writing.
- Current C1 gap: DOM/adapter/dashboard metadata can still expose plaintext `preview` values unless explicitly redacted; this must be fixed or tested before claiming plaintext-free live logs.
- F3 plaintext assistant reply capture is off by default.
- F3 can be enabled only with collaborator consent via dashboard/API.
- F3 evidence is local and should be time-boxed.

## Dashboard requirements

Existing dashboard files provide the base: `sns_addict/dashboard/server.py`, `sns_addict/dashboard/routes/*`, and `sns_addict/dashboard/static/*`.

C1 dashboard surfaces:

1. **Home:** mode, status, halt reason, F3 warning, counters.
2. **Allowlist:** add/remove friends in the visible C1 dashboard; edit/collaborator metadata may remain API-level or future UI unless implemented.
3. **Observe/Live:** safe event feed from `events.jsonl`.
4. **Approval Queue:** pending drafts with approve/edit/reject.
5. **Guardrails:** quiet-hours state, volume counters, frozen threads, canary alerts.
6. **Emergency Stop:** persistent stop control.

## Acceptance criteria

### Setup/login

- `sns-addict setup` or `hermes sns-addict setup` completes without changing runtime code.
- Storage exists at `~/.hermes/sns-addict/`.
- Empty allowlist is created if absent.
- F3 is off.
- Initial product mode is `stopped` or `observe`, not autopilot.

### Observe mode

- DOM events appear in dashboard/live events.
- No calls to `SnsAddictAdapter.send()` or `DMActions.send()` occur.
- Non-allowlisted inbound messages remain non-sendable.

### Approval mode

- Allowlisted inbound messages create queue items.
- Drafts can be approved, edited, or rejected.
- Only approved items send.
- Stop before approval cancels or blocks sends.

### Autopilot-lite

- Only allowlisted inbound threads can receive automatic replies.
- Non-allowlisted inbound threads never call LLM/send.
- Quiet hours, volume cap, dedup, identity canary, and HALT_NOW are enforced.
- No active outreach path is enabled.

### Emergency stop

- Dashboard stop and CLI stop both stop within the watcher interval.
- `~/.hermes/HALT_NOW` blocks new sends.
- Resume requires explicit owner action.

### F3

- Enabling F3 without `collaborator_consent` fails.
- Enabling F3 with consent logs a consent event.
- Plaintext assistant replies are captured only while F3 is enabled.

## Verification plan

### Automated docs/code sanity

- `python -m pytest -q` if the environment has dependencies and it is safe to run.
- Path sanity for documentation references, e.g. verify cited `sns_addict/...` files exist.
- Add tests in future implementation cycle for each mode gate.
- Privacy regression for default event/live-dashboard payloads: inbound plaintext must not appear in `text`, `preview`, or similar fields unless an explicit consent-gated debug mode is active.

### Unit tests to add in implementation cycle

- `observe` mode does not call adapter send.
- `approval` mode queues drafts instead of sending.
- Queue approve triggers exactly one send.
- Queue reject triggers zero sends.
- `autopilot_lite` blocks non-allowlisted thread.
- `autopilot_lite` blocks first-message/proactive action.
- HALT_NOW blocks all mode send paths.
- F3 enable requires collaborator consent.

### Manual checks

- Dashboard loads at `http://localhost:8765`.
- Live event feed updates while Instagram tab is foregrounded.
- Stop button touches `~/.hermes/HALT_NOW`.
- Removing `HALT_NOW` plus explicit mode change is required to resume.
- F3 runbook remains consent-gated: `docs/RUNBOOK-W2-W3-F3.md`.

## Next cycles

### C1 completion checklist

- [ ] Product mode field/mapping is explicit.
- [ ] Observe mode is default and send-proof.
- [ ] Approval queue exists in API and UI.
- [ ] Inbound allowlist gate exists before LLM/send.
- [ ] Autopilot-lite is disabled by default.
- [ ] Active outreach surfaces are disabled or guarded.
- [ ] Emergency stop is prominent and tested.
- [ ] F3 remains consent-gated.

### C2

- Conversation detail tab using `sns_addict/persistence/conversations.py`.
- Better realtime detection if DOM foreground reliability is insufficient.
- Morning queue handling for quiet-hours drafts.
- Alert/recovery UX for challenges and canary halts.

### C3

- Carefully expand autopilot-lite only after C1/C2 evidence.
- Consider group/Reels/story features only as approval-first experiences.
- Add richer persona evaluation and regression checks.
- Long-run evidence and safety metrics dashboard.

## Risks

| Risk | Mitigation |
|---|---|
| Current `active` state implies automatic send. | Introduce product modes and make `active` only a low-level connection state. |
| Inbound path lacks explicit allowlist gate. | Add allowlist check before LLM/send or queue. |
| Allowlist stores usernames while adapter uses thread IDs/hrefs. | Add a relationship resolver and store a safe mapping before enforcing allowlist. |
| Active behavior can originate DMs if wired. | Keep out of C1; add tests forbidding first messages. |
| Live event preview metadata may expose inbound plaintext. | Redact/hash `preview` before persistence/WebSocket/UI, or isolate it behind explicit local debug consent. |
| DOM observer misses background-tab events. | Make observe/approval tests foregrounded; evaluate WebSocket only in C2. |
| F3 stores plaintext assistant replies. | Consent gate, default off, local-only, time-boxed. |
| Send failure retries could duplicate DMs. | Preserve existing no-retry send behavior. |
