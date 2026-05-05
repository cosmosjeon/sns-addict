# Installation Guide

## Prerequisites

- **Hermes** ≥ 0.12.0 (or `pip install git+...` fallback)
- **Python** ≥ 3.10
- **macOS** (Linux untested)
- **2 GB free disk** (Chromium download ~211 MB)
- Instagram account (deski.ai)

Check your Python version:

```bash
python3 --version
# Should print Python 3.10.x or higher
```

Check Hermes version:

```bash
hermes --version
# Should print 0.12.0 or higher
```

## Method 1: Hermes Plugin (Recommended)

```bash
hermes plugins install cosmosjeon/sns-addict
```

Hermes downloads the plugin, installs Python dependencies, and registers the `sns-addict` subcommand. No manual pip steps needed.

## Method 2: pip (Fallback)

If you don't have Hermes or prefer a standalone install:

```bash
pip install git+https://github.com/cosmosjeon/sns-addict.git
```

After pip install, the `sns-addict` CLI is available directly (without the `hermes` prefix).

## Setup

Run the interactive setup (you'll log in to Instagram):

```bash
hermes sns-addict setup
```

This will:
1. Install Patchright + download bundled Chromium (~211 MB)
2. Open a browser window — log in to your Instagram account
3. When "Save login info?" appears, click **예** (Yes)
4. Install SOUL.md persona to `~/.hermes/SOUL.md`
5. Update `~/.hermes/config.yaml` with sns_addict block

The setup takes about 3-5 minutes on a fast connection (mostly Chromium download).

## Dashboard

Start the dashboard server:

```bash
hermes sns-addict dashboard
```

Open http://localhost:8765 in your browser.

From the dashboard you can:
- Add friends to the allowlist
- View live DM activity
- Check guardrail status
- Start and stop the bot

To use a different port:

```bash
hermes sns-addict dashboard --port 8766
```

## Owner UX Tips

- Move the headful Chromium window to a separate macOS Space
- Do NOT click inside the Chromium window while the bot is running
- Keep the Instagram tab **foregrounded** (MutationObserver throttles in background)
- Run `caffeinate -d &` during 1-hour live tests to prevent sleep

## Emergency Stop

Create the halt file to stop the bot immediately:

```bash
touch ~/.hermes/HALT_NOW
```

Remove it to resume:

```bash
rm ~/.hermes/HALT_NOW
```

## Troubleshooting

**challenge_required redirect**: Instagram detected automation. Stop immediately, wait 24h, try again with a fresh profile.

**Port conflict**: Change port with `hermes sns-addict dashboard --port 8766`

**2FA prompt**: Complete 2FA manually in the browser window during setup.

**Login timeout**: You have 5 minutes to complete login. Re-run `hermes sns-addict setup` if it times out.

**Chromium won't launch**: Make sure you have at least 2 GB free disk space. Run `df -h ~` to check.

**Bot not responding to DMs**: Confirm the Instagram tab is foregrounded in the Chromium window. Background tabs throttle MutationObserver events.
