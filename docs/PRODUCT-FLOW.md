# Product Flow — supervised Instagram persona MVP

This product is not a blind Instagram bot. The owner experience should feel like a local Hermes-powered copilot for an Instagram persona: it observes, drafts, asks for approval, and only later earns tightly scoped autopilot-lite behavior.

## Target owner journey

```text
Setup/login
  -> Dashboard
  -> Observe-only mode
  -> Approval queue
  -> Optional autopilot-lite for allowlisted friends only
  -> Emergency stop available throughout
```

## Personas

- **Owner:** the single local operator running sns-addict on their machine.
- **Allowlisted friend/collaborator:** a person the owner explicitly adds in the dashboard before drafts/sends are allowed.
- **Hermes persona:** SOUL.md-driven deski.ai style, invoked through `SnsAddictAdapter.invoke_llm()`.
- **Instagram:** accessed only through the owner’s headful Patchright browser session.

## Step 1 — setup/login

Owner goal: get a safe local environment and authenticated browser profile.

Existing implementation:

- CLI entry: `sns_addict/cli.py` (`setup`).
- Setup orchestration: `sns_addict/setup_flow.py`.
- Browser profile and login: `sns_addict/browser/session.py`, `sns_addict/browser/login.py`.
- Local storage created under `~/.hermes/sns-addict/`.
- Persona installed to `~/.hermes/SOUL.md` from `assets/SOUL.md`.
- Hermes plugin registration lives in `sns_addict/__init__.py` and `plugin.yaml`.

Product requirements:

1. Setup must make clear this is **single-tenant local software**.
2. Setup must default to a non-sending mode after login.
3. Setup must create an empty allowlist; nothing is implicitly trusted.
4. Setup must leave F3 plaintext capture off.

## Step 2 — dashboard home

Owner goal: see system state and know whether anything can send.

Existing implementation:

- Server: `sns_addict/dashboard/server.py`.
- Static UI: `sns_addict/dashboard/static/index.html`, `app.js`, `style.css`.
- Status route: `sns_addict/dashboard/routes/control.py` (`/api/control/status`).
- Live events: `/api/monitoring/events` and `/ws/events` tail `events.jsonl`.

Target dashboard home:

- Current product mode: `stopped`, `observe`, `approval`, or `autopilot_lite`.
- Browser/session status.
- Allowlist count.
- Today’s volume counters.
- Guardrail health: canary, quiet hours, HALT_NOW, loop freezes.
- F3 status with a loud warning if enabled.
- Emergency stop button always visible.

## Step 3 — observe-only mode

Owner goal: verify the account, persona, and detection pipeline without sending.

Behavior:

- Browser may open and observe Instagram DMs.
- DOM events may be logged with hashed text fields through `sns_addict/persistence/events.py`.
- Dashboard Live tab shows activity.
- The LLM may be disabled in pure observe mode, or draft generation may be hidden behind a separate “draft preview” action.
- `DMActions.send()` must never be called in observe mode.

Implementation grounding:

- Detection starts in `sns_addict/detection/dom_observer.py`.
- Adapter callback path is `SnsAddictAdapter._on_dom_event()` and `_process_inbound()` in `sns_addict/adapter.py`.
- The mode gate should prevent `sns_addict/loops/inbound.py` from reaching its send step while in observe mode.

UX details:

- Empty state: “Observing only — no messages will be sent.”
- Event cards show hashed/safe metadata by default.
- Owner can add an allowlisted friend from the Allowlist tab before moving to approval mode.

## Step 4 — allowlist

Owner goal: explicitly mark which relationships are eligible for drafting/sending.

Existing implementation:

- Store: `sns_addict/persistence/allowlist.py`.
- Routes: `sns_addict/dashboard/routes/allowlist.py`.
- UI tab: current dashboard Allowlist tab.

Product rules:

1. No allowlist entry means no draft/send.
2. Allowlist is relationship permission, not permission for cold outreach.
3. Autopilot-lite can only respond inside existing inbound threads from allowlisted users.
4. `is_collaborator` should be used for F3 test collaborators, not broad sending permission.

## Step 5 — approval queue

Owner goal: inspect persona drafts before anything is sent.

Behavior:

1. Inbound message is detected.
2. System verifies mode and allowlist.
3. Guardrails run.
4. Hermes persona drafts a reply from SOUL.md.
5. Draft appears in the queue with guardrail badges and context metadata.
6. Owner chooses: Approve, Edit+Approve, Reject, Stop.
7. Only approved drafts call `SnsAddictAdapter.send()`.

Queue item states:

| State | Meaning |
|---|---|
| `pending` | Draft is waiting for owner action. |
| `approved` | Owner approved; send can begin if no stop/quiet-hour block intervened. |
| `edited` | Owner changed the draft before approval. |
| `rejected` | Draft discarded. |
| `expired` | Draft aged out or the thread became unsafe. |
| `blocked` | Guardrail blocked the item. |
| `sent` | Adapter returned a successful send result. |
| `failed` | Send failed; no automatic retry. |

Implementation grounding:

- Seed persistence from `State.pending_sends` in `sns_addict/persistence/state.py` or add a dedicated queue store later.
- Send path remains `SnsAddictAdapter.send()` -> `sns_addict/actions/dm.py`.
- Existing `events.jsonl` can log queue transitions without inbound plaintext once preview-like metadata is redacted. Current DOM/adapter/dashboard plumbing may still surface plaintext `preview` fields, so C1 must treat preview redaction as a required privacy hardening item.

C1 queue UX:

- Pending tab with one primary action per draft.
- Rejection reason optional.
- No bulk approve.
- No automatic retry on send failure.

## Step 6 — autopilot-lite

Owner goal: optionally allow very low-risk automatic replies after the approval flow has proven safe.

Hard constraints:

- Only allowlisted friends.
- Only replies to inbound messages; no first messages.
- Quiet hours enforced.
- Volume caps enforced.
- Identity canary halts.
- HALT_NOW halts.
- Loop detector freezes rapid back-and-forth.
- No retries after failed send.

Implementation grounding:

- Volume: `sns_addict/guardrails/volume_cap.py`.
- Quiet hours: `sns_addict/guardrails/quiet_hours.py`.
- Identity canary: `sns_addict/guardrails/identity_canary.py`.
- Loop detection: `sns_addict/guardrails/loop_detector.py`.
- Dedup: `sns_addict/guardrails/dedup.py`.
- HALT_NOW: `sns_addict/guardrails/halt_now.py`.

Important current-code warning:

- `sns_addict/loops/active_behavior.py` is an active outreach surface. It must remain out of the MVP send path, or be refactored so it cannot originate first messages.

## Step 7 — emergency stop and recovery

Owner goal: stop all activity instantly and recover intentionally.

Existing implementation:

- CLI: `sns-addict stop` touches `~/.hermes/HALT_NOW` via `sns_addict/cli.py`.
- Dashboard: `/api/control/stop` sets state to `stopped` and touches `HALT_NOW`.
- Watcher: `HaltNow.watch()` in `sns_addict/guardrails/halt_now.py` calls adapter halt/disconnect.
- Adapter state: `SnsAddictAdapter.halt()` writes `halt_reason` in state.

Target UX:

1. Stop button is visible on every dashboard view.
2. Stop sets mode to `stopped`/`halted` and cancels pending sends that have not started.
3. Resume requires the owner to remove/clear `HALT_NOW` and explicitly choose a mode.
4. The dashboard shows the last halt reason.

## F3 testing flow

F3 mode exists only to collect plaintext assistant replies for voice scoring during agreed test windows.

Existing implementation:

- Route: `POST /api/control/f3_mode` in `sns_addict/dashboard/routes/control.py`.
- Consent requirement: enabling F3 requires `collaborator_consent: true`.
- Capture path: `SnsAddictAdapter._append_f3_reply()` writes `replies-f3.jsonl`.
- Runbook: `docs/RUNBOOK-W2-W3-F3.md`.

Rules:

- F3 off by default.
- F3 requires collaborator consent before enabling.
- F3 should be time-boxed and disabled after scoring.
- Do not capture inbound plaintext without explicit consent.

## Happy path summary

```text
1. Owner runs setup and logs in.
2. Dashboard opens in stopped/observe state.
3. Owner adds a collaborator to allowlist.
4. Owner switches to observe and validates live events.
5. Owner switches to approval mode.
6. Inbound DM creates a draft queue item.
7. Owner approves or edits the draft.
8. Adapter sends once, best-effort, with no retry.
9. Owner may later enable autopilot-lite for this allowlisted friend only.
10. Any concern -> emergency stop.
```

## Failure and blocked paths

| Situation | Expected product behavior |
|---|---|
| Non-allowlisted inbound DM | Observe/log only; no draft/send. |
| Identity canary phrase | In send-capable modes, send canonical reply only if policy permits, then halt and alert. In stopped/observe, alert without sending. |
| Quiet hours | Queue for owner/morning; do not send automatically. |
| Volume cap exceeded | Mark blocked; do not send. |
| Send failure | Mark failed; do not retry automatically. |
| Browser challenge/suspicious login | Stop and require owner review. |
| F3 consent missing | Reject F3 enable request. |
| HALT_NOW present | Stop all modes and require manual recovery. |
