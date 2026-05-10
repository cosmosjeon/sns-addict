# Runbook — W2 / W3 / W6.F3 Human Gates

> Generated: 2026-05-10  
> All automated work (W1–W5, W6.F1/F2/F4) is complete.  
> This runbook covers the 3 human-gate steps required to close v0.1.0.

---

## Prerequisites

```bash
# Confirm 94 tests pass
cd ~/Documents/sns-addict
.venv/bin/pytest sns_addict/tests/ --tb=no -q

# Confirm Hermes boots cleanly
hermes status
# Should show: ✓ sns_addict connected
```

---

## STEP 1 — W2.1: F3 Dry-run (5 minutes)

### Enable F3 mode in config

Edit `~/.hermes/config.yaml` — add `f3_mode: true` to the sns_addict extra block:

```yaml
  sns_addict:
    enabled: true
    extra:
      dashboard_port: 8765
      profile_dir: /Users/cosmos/.hermes/sns-addict/profile
      mode: live
      auto_start: false
      f3_mode: true          # ← ADD THIS LINE
```

### Run the dry-run

```bash
# Terminal 1 — start Hermes
hermes start

# Watch logs for: ✓ sns_addict connected
# Open Dashboard: http://localhost:8765
# Toggle to "active"
```

On your **second device** (phone or another browser):
- Open Instagram → DM your own account (the bot account)
- Send 1–3 test messages in Korean (e.g. "안녕", "뭐해", "오늘 날씨 어때")
- Wait for bot to reply (should be within 10s)

### Verify evidence

```bash
# Check F3 evidence was written
cat ~/.hermes/sns-addict/logs/replies-f3.jsonl | head -5

# Copy to evidence directory
mkdir -p ~/Documents/sns-addict/evidence/dryrun
cp ~/.hermes/sns-addict/logs/replies-f3.jsonl \
   ~/Documents/sns-addict/evidence/dryrun/replies-f3.jsonl

# Also copy events log
cp ~/.hermes/sns-addict/logs/events.jsonl \
   ~/Documents/sns-addict/evidence/dryrun/events.jsonl
```

Expected jsonl line format:
```json
{"ts": 1715000000.0, "thread_id_hash": "abc123...", "input": "", "output": "안녕하세요! ...", "context": []}
```

### Stop after 5–10 minutes

```bash
# Dashboard → toggle to "stopped"
# OR: Ctrl+C in hermes terminal
```

---

## STEP 2 — W2.2: Voice Rubric Scoring

```bash
cd ~/Documents/sns-addict

# Run voice scorer against dry-run evidence
.venv/bin/python tools/voice_score.py \
  evidence/dryrun/replies-f3.jsonl \
  --rubric 10dim

# Target: score ≥ 17/20
```

**If score < 17:**
- Edit `~/.hermes/SOUL.md` to strengthen the persona voice
- Re-run the dry-run (W2.1) with updated SOUL.md
- Re-score until ≥ 17/20

**Record the model name used:**
```bash
# Check which model auxiliary_client resolved to
grep "model\|provider" ~/.hermes/sns-addict/logs/events.jsonl | head -5
# OR check hermes logs for the model slug
```

Update `~/Documents/insta-chat/.sisyphus/notepads/sns-addict-unified/decisions.md`:
```
## W2.2 model name
- Model: [model-slug-here] (e.g. "claude-3-5-sonnet-20241022" or "nous-hermes-3")
- Voice score: [X]/20
- Date: 2026-05-10
```

---

## STEP 3 — W3.1: DOM Observer 30-min Foregrounded Tab Test

### Setup

```bash
# Ensure hermes is running with sns_addict active
hermes start
# Dashboard → "active"
# Keep the browser tab in FOREGROUND (do NOT minimize)
```

### Test protocol

Send **5 DMs in 60 seconds**, 3 separate times (= 15 DMs total):

| Round | Time | Action |
|-------|------|--------|
| Round 1 | T+0:00 | Send 5 DMs from second device in 60s |
| Round 2 | T+10:00 | Send 5 DMs from second device in 60s |
| Round 3 | T+20:00 | Send 5 DMs from second device in 60s |
| Done | T+30:00 | Stop, analyze |

### Analyze results

```bash
# Count detected vs sent
cd ~/Documents/sns-addict
.venv/bin/python tools/f3_latency_check.py \
  ~/.hermes/sns-addict/logs/events.jsonl

# Manual check: count "reply_sent" events vs DMs sent
grep '"kind": "reply_sent"' ~/.hermes/sns-addict/logs/events.jsonl | wc -l
# Should be ≥ 14 out of 15 (≥95% detection)
```

**PASS criteria:** detection ≥ 95% AND p95 latency ≤ 5s  
**FAIL criteria:** detection < 95% OR p95 latency > 5s → WebSocket sniffing needed

### Document outcome

Update `~/Documents/insta-chat/.sisyphus/notepads/sns-addict-unified/decisions.md`:
```
## W3.1 outcome
- Date: 2026-05-10
- Detection rate: [X]/15 = [Y]%
- p50 latency: [X]s
- p95 latency: [X]s
- Verdict: PASS / FAIL
- Action: DOM Observer sufficient (skip WebSocket) / WebSocket sniffing needed
```

---

## STEP 4 — W6.F3: 1-Hour Live Test

> Only run after W2.1 + W2.2 + W3.1 all PASS.

### Pre-flight

```bash
# Keep machine awake
caffeinate -d &

# Verify hermes status
hermes status

# Add collaborator to allowlist
# Dashboard → Allowlist → Add [collaborator_username]

# Enable F3 mode (should already be on from W2.1)
# Verify in ~/.hermes/config.yaml: f3_mode: true
```

### Run

```bash
hermes start
# Dashboard → "active"
# Monitor for 60 minutes
# Collaborator sends DMs naturally during this time
```

### Post-run analysis

```bash
# Copy evidence
cp ~/.hermes/sns-addict/logs/replies-f3.jsonl \
   ~/Documents/sns-addict/evidence/f3-live/replies-f3.jsonl
cp ~/.hermes/sns-addict/logs/events.jsonl \
   ~/Documents/sns-addict/evidence/f3-live/events.jsonl

# Check latency
.venv/bin/python tools/f3_latency_check.py \
  evidence/f3-live/events.jsonl

# Check voice score
.venv/bin/python tools/voice_score.py \
  evidence/f3-live/replies-f3.jsonl --rubric 10dim

# Check for canary hits
grep '"kind": "canary_hit"' evidence/f3-live/events.jsonl | wc -l
# Must be 0

# Check for process leaks
ps aux | grep -i "patchright\|chromium" | grep -v grep
# Should show only 1 chromium process
```

**PASS criteria:**
- p50 latency ≤ 10s, p95 ≤ 30s
- Voice score ≥ 17/20
- 0 canary FAIL
- 0 process leak

**Re-run cap: 1** — if this run fails, fix the issue and re-run once. If second run also fails: stop and escalate.

---

## STEP 5 — W6.tag: Git Tag v0.1.0

After ALL of W2.1 + W2.2 + W3.1 + W6.F3 PASS:

```bash
cd ~/Documents/sns-addict

# Commit evidence
git add evidence/
git commit -m "chore(evidence): W2.1 dry-run + W3.1 DOM test + W6.F3 live test evidence"

# Tag
git tag -a v0.1.0 -m "$(cat <<'EOF'
sns-addict v0.1.0 — C1+C2+C3 complete

## What's in this release

### C1 Foundation (already shipped)
- Patchright BrowserSession (headful, ko-KR, persistent profile)
- DOM Observer new-message detection
- InboundLoop A: 7-step pipeline (canary→quiet→loop→LLM→dedup→volume→send)
- 8 guardrails: volume_cap, dedup, quiet_hours, loop_detector, identity_canary,
  halt_now, cold_start_grace, fire-and-best-effort
- Hermes plugin (kind: platform, BasePlatformAdapter)
- Dashboard MVP (Home + Allowlist + Events tail + Start/Stop)

### C2 Features (this release)
- invoke_llm → Hermes-auth auxiliary_client (no raw OpenAI key)
- mood_scheduler: time-of-day Korean mood cycles (아침/낮/저녁/밤)
- active_behavior: mood-driven active outreach (2/day cap)
- group DM: read/send in group threads (15/day/group cap)
- persona editor: SOUL.md inline edit with diff preview + atomic write
- conversations tab: recent thread history dashboard

### C3 Features (this release)
- reels_analyzer: Patchright screenshot + vision LLM summary
- share_decision: allowlist-gated reel sharing
- reels + story actions: Patchright UI flows
- alerts panel: challenge/ban/quota status dashboard
- long-run hardening: 24h auto-stop, sleep/wake recovery, suspicious-login log

## Metrics
- Tests: 94 passing, 0 skips
- Coverage: 75% overall, 91% guardrails
- Lint: clean (ruff)
- Voice score: ≥17/20 (F3 validated)
- Live test: 0 canary FAIL, 0 process leak

## DoD
All 10 DoD gates passed. Owner explicit okay received.
EOF
)"

# Push tag
git push origin v0.1.0
```

---

## Disable F3 mode after release

```yaml
# ~/.hermes/config.yaml — remove f3_mode line
  sns_addict:
    extra:
      # f3_mode: true   ← REMOVE (privacy)
```

---

*Runbook generated by Atlas (sns-addict-unified session ses_1ef4540a6ffeObI5uur5xK51T4)*
