# sns-addict

> Local Hermes-powered supervised Instagram persona — not a growth/spam bot.

sns-addict runs a single-tenant local dashboard for an Instagram persona. The owner connects Instagram in a headful local Chromium window, starts a live observer, reviews persona drafts, and only approved replies are sent. Autopilot-lite is optional and tightly limited to allowlisted 1:1 inbound DMs.

## Product flow

```text
one command
  -> dashboard opens
  -> Connect Instagram opens local Chromium
  -> owner logs in directly on instagram.com
  -> Start Agent launches live observer in approval-first mode
  -> allowlisted inbound DMs create drafts
  -> owner approves/edits/rejects
  -> Emergency Stop is always available
```

The dashboard never asks for or stores an Instagram password. Credentials/2FA are typed only into Instagram's own Chromium page.

## Install

```bash
hermes plugins install cosmosjeon/sns-addict
# OR fallback
pip install -U "git+https://github.com/cosmosjeon/sns-addict.git"
```

For local development:

```bash
cd /Users/slit/opensource/sns-addict
pip install -e ".[dev]"
```

## Quick start for non-developers

```bash
sns-addict start
# or, when invoked through Hermes plugin routing:
hermes sns-addict start
```

Then use the dashboard at `http://127.0.0.1:8765`:

1. Click **Connect Instagram**.
2. Log in inside the Chromium Instagram window. Do not enter credentials in the dashboard.
3. Add a test friend/collaborator to **Allowlist**.
4. Click **Start Agent**.
5. Keep the default `approval` mode for the first test.
6. Send a DM from the allowlisted test account.
7. Confirm a draft appears in **Approval Queue**.
8. Approve or reject it.

Safe defaults:

- Initial local state is `stopped` until the owner starts the agent.
- `Start Agent` uses `approval` mode, not autopilot.
- Non-allowlisted inbound DMs are observe/log only: no draft, no send.
- Ambiguous/group metadata fails closed.
- `HALT_NOW` and Emergency Stop block sends.

## LLM backend

Reply drafting prefers Hermes Agent when the app runs as a Hermes plugin/profile and `agent.auxiliary_client` is available. In standalone `sns-addict start` / npm wrapper mode, configure an OpenAI-compatible fallback before expecting real drafts:

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"          # optional
export OPENAI_BASE_URL="https://api.openai.com/v1"  # optional

# OR OpenRouter
export OPENROUTER_API_KEY="..."
export OPENROUTER_MODEL="openai/gpt-4o-mini"
```

The dashboard shows the active LLM backend and setup hint. If no backend is configured, the observer can still detect allowlisted inbound DMs in `approval` mode, but the proposal is a diagnostic placeholder instead of a sendable persona draft.

## Runtime modes

| Mode | Behavior |
| --- | --- |
| `stopped` | No browser/send activity. Emergency stop state. |
| `observe` | Observe/log only. No LLM draft and no send. |
| `approval` | Allowlisted 1:1 inbound DMs can create drafts. Owner approval is required before send. |
| `autopilot_lite` | Optional automatic replies only for allowlisted explicit 1:1 inbound DMs after guardrails pass. Never default. |

## Emergency stop

Dashboard **Emergency Stop** and CLI stop both touch:

```bash
~/.hermes/HALT_NOW
```

Manual stop:

```bash
touch ~/.hermes/HALT_NOW
```

Resume requires explicit owner action: clear the halt and choose a mode/start again.

```bash
rm -f ~/.hermes/HALT_NOW
sns-addict start
```

## Architecture

```text
Local dashboard / CLI
  -> onboarding routes: Connect Instagram status/start
  -> runtime supervisor: owns local adapter task
  -> SnsAddictAdapter: Patchright browser + DOM observer
  -> InboundLoop: mode + allowlist + guardrails + draft/send policy
  -> StateStore / AllowlistStore / events.jsonl under ~/.hermes/sns-addict/
```

Key files:

| Component | File |
| --- | --- |
| CLI launcher | `sns_addict/cli.py` |
| Local onboarding helpers | `sns_addict/onboarding.py` |
| Dashboard onboarding API | `sns_addict/dashboard/routes/onboarding.py` |
| Runtime supervisor | `sns_addict/runtime/supervisor.py` |
| Dashboard UI | `sns_addict/dashboard/static/` |
| Adapter/browser runtime | `sns_addict/adapter.py`, `sns_addict/browser/` |
| Mode-aware inbound policy | `sns_addict/loops/inbound.py` |
| State/allowlist/events | `sns_addict/persistence/` |

## Guardrails

Before any send-capable path:

1. HALT/stopped check
2. identity canary
3. allowlist + explicit 1:1 metadata
4. quiet hours
5. loop detector
6. dedup
7. volume cap
8. fire-and-best-effort send, no automatic retry

## Docs

- [MVP Spec](docs/MVP-SPEC.md)
- [Product Flow](docs/PRODUCT-FLOW.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Installation Guide](docs/INSTALLATION.md)
- [Hermes Integration](docs/HERMES-INTEGRATION.md)
- [Persona Guide](docs/PERSONA-GUIDE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## License

MIT
