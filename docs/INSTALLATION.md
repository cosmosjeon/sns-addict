# Installation Guide

## Prerequisites

- **Hermes** ≥ 0.12.0, or standalone `pip install` fallback
- **Python** ≥ 3.10
- **macOS** recommended; Linux is untested
- **2 GB free disk** for bundled Chromium
- Instagram account you control

sns-addict is a **local supervised persona**, not a growth/spam bot. The dashboard never asks for an Instagram password; login happens only inside a local Chromium window on `instagram.com`.

## Install

### Method 1: Hermes Plugin

```bash
hermes plugins install cosmosjeon/sns-addict
```

Hermes installs dependencies and registers the `sns-addict` subcommand.

### Method 2: pip fallback

```bash
pip install -U "git+https://github.com/cosmosjeon/sns-addict.git"
```

After pip install, the `sns-addict` CLI is available directly.

## Non-developer quick start

Run one command:

```bash
sns-addict start
# or through Hermes plugin routing:
hermes sns-addict start
```

This will:

1. Prepare local files under `~/.hermes/sns-addict/`.
2. Copy `SOUL.md` to `~/.hermes/SOUL.md` if missing.
3. Start the local dashboard at `http://127.0.0.1:8765`.
4. Open the dashboard in your browser unless `--no-open` is passed.
5. Keep the agent **stopped** until you explicitly click **Start Agent**.

From the dashboard:

1. Click **Connect Instagram**.
2. Log in directly inside the Chromium Instagram window.
3. Add a test friend/collaborator to the allowlist.
4. Click **Start Agent**. This starts in `approval` mode.
5. Send a test DM from the allowlisted account.
6. Approve or reject the proposed reply.

## Safe defaults

- Initial state is `stopped`.
- Start Agent uses `approval`, not `autopilot_lite`.
- Non-allowlisted inbound DMs do not produce drafts or sends.
- Group/ambiguous metadata fails closed.
- Emergency Stop touches `~/.hermes/HALT_NOW`.

## Fallback setup command

The older setup command remains available for explicit terminal-driven setup:

```bash
hermes sns-addict setup
# or
sns-addict setup
```

Use this only if the dashboard-led Connect Instagram flow is not sufficient.

## Dashboard command only

If local files are already prepared and you only want the dashboard server:

```bash
sns-addict dashboard
# or
hermes sns-addict dashboard
```

Open:

```text
http://127.0.0.1:8765
```

Different port:

```bash
sns-addict start --port 8766
sns-addict dashboard --port 8766
```

## Emergency Stop

Dashboard **Emergency Stop** and CLI stop both create:

```bash
~/.hermes/HALT_NOW
```

Manual stop:

```bash
touch ~/.hermes/HALT_NOW
```

Resume requires explicit owner action:

```bash
rm -f ~/.hermes/HALT_NOW
sns-addict start
```

Then choose mode/start in the dashboard.

## Owner UX tips

- Test with a secondary Instagram account first.
- Keep Chromium visible while testing; background tabs may throttle observers.
- Use `approval` mode until you trust the persona and DOM detection.
- Enable `autopilot_lite` only for allowlisted 1:1 test accounts.
- Run `caffeinate -d` during long local tests to prevent sleep.

## Troubleshooting

**Port conflict**: change port with `sns-addict start --port 8766`.

**2FA prompt**: complete 2FA manually in the Chromium Instagram window.

**Login not detected**: wait for Instagram DM inbox to load, then refresh the dashboard status. If needed, click Connect Instagram again.

**Chromium won't launch**: ensure 2 GB free disk and install Patchright browser dependencies.

**Agent not drafting**: confirm runtime mode is `approval`, the sender is in allowlist, and live events show the observer is connected.

**Agent sends nothing in observe mode**: expected. `observe` never drafts or sends.

**Emergency stop remains active**: remove `~/.hermes/HALT_NOW`, then click Start Agent again.
