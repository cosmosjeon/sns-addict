# sns-addict

> Korean SNS persona Instagram bot via browser automation

sns-addict is a [Hermes](https://github.com/cosmosjeon/hermes) plugin that automates Instagram DM responses using the deski.ai persona (SOUL.md, voice 19/20 validated). It uses Patchright browser automation with anti-detection measures.

## Install

```bash
hermes plugins install cosmosjeon/sns-addict
# OR (fallback)
pip install git+https://github.com/cosmosjeon/sns-addict.git
```

## Quick Start

```bash
# 1. Setup (interactive — you'll log in to Instagram)
hermes sns-addict setup

# 2. Start dashboard
hermes sns-addict dashboard
# → Open http://localhost:8765

# 3. Add a friend to allowlist via dashboard
# 4. Click "Start" in dashboard
# 5. Bot responds to DMs automatically
```

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for full setup details.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Tier 1: Hermes Plugin Layer                            │
│  register() → SnsAddictAdapter (BasePlatformAdapter)    │
├─────────────────────────────────────────────────────────┤
│  Tier 2: Browser Automation (Patchright)                │
│  BrowserSession → DOM Observer → DM Actions             │
├─────────────────────────────────────────────────────────┤
│  Tier 3: Guardrails + Inbound Loop A                    │
│  canary → quiet → loop → LLM → dedup → volume → send   │
├─────────────────────────────────────────────────────────┤
│  Tier 4: Dashboard + Persistence                        │
│  FastAPI + WebSocket + state.json + allowlist.json      │
└─────────────────────────────────────────────────────────┘
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Plugin entry | `sns_addict/__init__.py` | Hermes `register()` hook |
| Browser session | `sns_addict/browser.py` | Patchright session + DOM observer |
| Inbound loop | `sns_addict/loop.py` | Poll → guardrails → LLM → send |
| Dashboard | `sns_addict/dashboard.py` | FastAPI + WebSocket server |
| Guardrails | `sns_addict/guardrails.py` | 8 safety checks |
| Persistence | `sns_addict/state.py` | state.json + allowlist.json |

## Persona

Powered by SOUL.md (5098 chars, voice 19/20 validated). The bot responds as deski.ai — a Korean persona with natural conversational style.

The persona file lives at `~/.hermes/SOUL.md` after setup. You can edit it to adjust tone, but keep the voice score above 15/20 or replies will feel off.

## Guardrails (8)

1. **volume_cap** — 50/day total, 5/hr/friend, 20/day/friend
2. **identity_canary** — detects "are you AI?" → replies "뭐래 ㅋㅋ" + halts
3. **loop_detector** — 4 turns/60s → freeze thread
4. **dedup** — 10-min window, no duplicate replies
5. **quiet_hours** — 02:00-08:00 send blocked
6. **halt_now** — `~/.hermes/HALT_NOW` file → immediate stop
7. **cold_start_grace** — 5-min warmup (0min for testing)
8. **fire-and-best-effort** — no retry on send failure

To trigger an emergency stop at any time:

```bash
touch ~/.hermes/HALT_NOW
```

Remove the file to resume:

```bash
rm ~/.hermes/HALT_NOW
```

## Dashboard

The dashboard runs at `http://localhost:8765` and shows:

- Live DM feed (incoming + outgoing)
- Allowlist management (add/remove friends)
- Guardrail status (which checks fired today)
- Volume counters (per-friend + global)
- Start / Stop controls

## Configuration

After `hermes sns-addict setup`, your `~/.hermes/config.yaml` gains:

```yaml
sns_addict:
  port: 8765
  quiet_start: "02:00"
  quiet_end: "08:00"
  volume_day: 50
  volume_hour_per_friend: 5
  volume_day_per_friend: 20
  cold_start_grace_seconds: 300
```

Edit these values to tune behavior. Restart the bot after changes.

## Cycle Roadmap

- **C1 (this)**: Foundation — install + DM reply + dashboard + guardrails
- **C2**: Realtime + mood scheduler + WebSocket detection
- **C3**: Vision + long-run + group DMs

## Docs

- [Installation Guide](docs/INSTALLATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Hermes Integration](docs/HERMES-INTEGRATION.md)
- [Persona Guide](docs/PERSONA-GUIDE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## License

MIT
