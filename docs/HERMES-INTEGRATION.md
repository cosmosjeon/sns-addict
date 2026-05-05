# Hermes Integration Contract — sns-addict

> Source of truth for W3.1 (SnsAddictAdapter) and W3.2 (InboundLoop A) implementers.
> All contracts verified against actual Hermes source code (read-only inspection).
> Do NOT modify Hermes core. Do NOT guess contracts — read the source.

---

## 1 — BasePlatformAdapter Contract

**Source**: `~/.hermes/hermes-agent/gateway/platforms/base.py:1206-1480`

`SnsAddictAdapter` must subclass `BasePlatformAdapter` and implement exactly **4 abstract methods**:

```python
from gateway.platforms.base import BasePlatformAdapter
from gateway.config import Platform, PlatformConfig
```

### Constructor

```python
def __init__(self, config: PlatformConfig, platform: Platform):
    super().__init__(config, platform)
    # self.config      — PlatformConfig (extra dict, credentials, etc.)
    # self.platform    — Platform enum value
    # self._running    — bool, managed by _mark_connected() / _mark_disconnected()
    # self._background_tasks  — set[asyncio.Task], managed by handle_message()
    # self._message_handler   — set via set_message_handler() by GatewayRunner
    # self._pending_messages  — Dict[str, MessageEvent], dedup guard
```

Do NOT call `_mark_connected()` or `_mark_disconnected()` directly from outside `connect()`/`disconnect()`.

### Abstract methods (must implement all 4)

```python
@abstractmethod
async def connect(self) -> bool:
    """Connect to the platform. Returns True on success."""

@abstractmethod
async def disconnect(self) -> None:
    """Disconnect cleanly."""

@abstractmethod
async def send(
    self,
    chat_id: str,
    content: str,
    reply_to: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SendResult:
    """Send a message. Returns SendResult(success, message_id, error)."""

@abstractmethod
async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
    """Return dict with at least: name (str), type ('dm'|'group'|'channel')."""
```

**Source lines**: `connect` at line 1409, `disconnect` at 1418, `send` at 1423, `get_chat_info` at 3201.

### is_connected property

`is_connected` is a **property** (not abstract), backed by `self._running`:

```python
@property
def is_connected(self) -> bool:
    return self._running
```

Do NOT override it. Call `self._mark_connected()` inside `connect()` on success and `self._mark_disconnected()` inside `disconnect()`.

### Key inherited attrs

| Attr | Type | Purpose |
|------|------|---------|
| `self._background_tasks` | `set[asyncio.Task]` | Tasks spawned by `handle_message()`. GatewayRunner cancels on shutdown. |
| `self._message_handler` | `Optional[MessageHandler]` | Set by GatewayRunner via `set_message_handler()`. Do NOT call directly. |
| `self._pending_messages` | `Dict[str, MessageEvent]` | Per-session dedup guard. |
| `self._running` | `bool` | Connection state. Managed by `_mark_connected` / `_mark_disconnected`. |

---

## 2 — Inbound Flow (sns-addict pattern)

sns-addict is **DOM event-driven**, not polling. This changes the concurrency model vs. the legacy Instagram adapter.

### Flow

```
DOM MutationObserver fires
  → adapter._on_dom_event(raw_event)          # must return in < 50ms
      → constructs MessageEvent(
            text=...,
            message_type=MessageType.TEXT,
            source=SessionSource(chat_id=thread_id, ...),
            message_id=msg_id,
            timestamp=datetime.now(),
        )
      → asyncio.create_task(self._process_inbound(event))   # non-blocking
      → returns immediately

_process_inbound(event):
  → await self.inbound_loop.on_inbound(event)   # InboundLoop is master orchestrator
```

### CRITICAL: do NOT call `handle_message` directly

`BasePlatformAdapter.handle_message` is a Hermes core method that:
1. Calls `self._message_handler` (the LLM agent runner set by GatewayRunner)
2. Spawns `asyncio.create_task(self._process_message_background(event, session_key))`
3. Automatically calls `self._send_with_retry()` after LLM response

Calling `handle_message` directly **bypasses all sns-addict guardrails** (canary check, quiet hours, loop detector, volume caps, dedup). The legacy Instagram adapter called `handle_message` because it had no InboundLoop. sns-addict does not follow that pattern.

**InboundLoop is the master orchestrator.** `handle_message` is never called by sns-addict code.

### MessageEvent construction (from legacy reference, `adapter.py:557-563`)

```python
event = MessageEvent(
    text=text,
    message_type=MessageType.TEXT,
    source=source,          # SessionSource with chat_id, user_id, platform
    message_id=msg_id,
    timestamp=datetime.now(),
)
```

---

## 3 — Outbound Flow

After InboundLoop passes all 7 guardrail steps, it calls the adapter directly:

```
InboundLoop.on_inbound(event)
  → [guardrail 1] dedup check
  → [guardrail 2] quiet hours
  → [guardrail 3] canary / identity check
  → [guardrail 4] loop detector
  → [guardrail 5] volume caps
  → [guardrail 6] invoke_llm(event) → response_text
  → [guardrail 7] dedup on response
  → await self.adapter.send(thread_id, response_text)
       → DMActions.send(page, thread_id, text)
           → Patchright Page interaction (humanized typing)
           → returns SendResult(success=True, message_id=...)
```

`adapter.send()` is fire-and-best-effort. No retry on failure (duplicate-DM risk). `SendResult.success=False` is logged but not retried.

The `BasePlatformAdapter.send` signature uses `chat_id` (not `thread_id`) as the first positional arg. In sns-addict, `chat_id` is the Instagram thread ID string.

---

## 4 — LLM Dispatch Helper

### Search result (gateway/ inspection)

Searched `~/.hermes/hermes-agent/gateway/` for:
```
async def (generate|dispatch|llm|complete|chat|invoke)
```

**Finding**: No standalone LLM dispatcher function exists in `gateway/`. The LLM is invoked via `GatewayRunner._run_agent()` (run.py:11726), which internally imports `run_agent.AIAgent` and runs a full agent turn. This is the Hermes-native path — it requires a registered `_message_handler`, session management, and the full GatewayRunner context. It is not callable from inside an adapter.

**Plan B activated.** `gateway/` contains no suitable LLM dispatcher for direct adapter use.

### LLM_PRIMARY_PATH = "openai_direct"

W3.1 `invoke_llm` implementation:

```python
async def invoke_llm(self, event: MessageEvent) -> str:
    """
    Call OpenAI directly with SOUL.md as system prompt.
    Returns response text only. Does NOT send. Does NOT trigger handle_message.
    """
    from openai import AsyncOpenAI
    import os

    soul_path = os.path.expanduser("~/.hermes/SOUL.md")
    with open(soul_path) as f:
        soul_md = f.read()

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": soul_md},
            {"role": "user", "content": event.text},
        ],
    )
    return response.choices[0].message.content
```

**Credentials**: `os.environ["OPENAI_API_KEY"]` — same key Hermes uses. No separate config needed.

**Behavior contract**:
- `invoke_llm` returns a string only. It never calls `send()`.
- InboundLoop calls `invoke_llm` after guardrails 1-5 pass, then runs guardrail 7 (dedup on response), then calls `adapter.send()`.
- `asyncio.create_task` is used by `_on_dom_event` to keep the DOM callback non-blocking. `invoke_llm` itself is `await`-ed inside `_process_inbound`.

---

## 5 — Concurrency Model

### DOM callback constraint

`_on_dom_event` must return in **< 50ms**. It only calls `asyncio.create_task()` — no `await`.

```python
def _on_dom_event(self, raw_event: dict) -> None:
    event = self._build_message_event(raw_event)
    asyncio.create_task(self._process_inbound(event))
    # returns immediately
```

### InboundLoop bounded queue

```python
# InboundLoop internal state
_active_tasks: set[asyncio.Task]   # max 5 concurrent
MAX_CONCURRENT = 5
```

On `on_inbound(event)`:
- If `len(_active_tasks) >= MAX_CONCURRENT`: drop event, log `inbound_dropped_overflow`, return.
- Otherwise: `task = asyncio.create_task(self._run_guardrails(event))`, add to `_active_tasks`, register done callback to discard.

### Shutdown

```python
async def stop(self) -> None:
    tasks = list(self._active_tasks)
    await asyncio.gather(*tasks, return_exceptions=True)  # 10s timeout
    # cancel remaining
    for t in tasks:
        if not t.done():
            t.cancel()
```

### Background tasks (BasePlatformAdapter)

`self._background_tasks` (inherited from `BasePlatformAdapter`) is used by `handle_message()` internally. sns-addict does not use `handle_message`, so `_background_tasks` stays empty. GatewayRunner still calls `cancel_background_tasks()` on shutdown — this is a no-op for sns-addict.

---

## 6 — Legacy Reference

The legacy Instagram adapter at `~/.hermes/hermes-agent/plugins/platforms/instagram/adapter.py` is a **read-only reference**. Port guardrail logic verbatim; do NOT port the inbound/outbound flow.

### MessageEvent construction example

`adapter.py:557-563`:
```python
event = MessageEvent(
    text=text,
    message_type=MessageType.TEXT,
    source=source,
    message_id=msg_id,
    timestamp=_dt.datetime.now(),
)
await self.handle_message(event)   # <-- sns-addict does NOT do this
```

### Legacy send flow reference

`adapter.py:268-340` — legacy send flow (polling model). Use for step ordering reference only. The polling loop, `_age_pending_sends` (`adapter.py:567-577`), and retry logic are all polling-model artifacts.

### CRITICAL: legacy flow is bypassed in sns-addict

Legacy flow:
```
polling loop → MessageEvent → self.handle_message(event)
  → Hermes core → self._message_handler (LLM agent)
  → self._send_with_retry()   # automatic
```

sns-addict flow:
```
DOM event → MessageEvent → asyncio.create_task(_process_inbound)
  → InboundLoop.on_inbound(event)   # master orchestrator
  → invoke_llm(event)               # explicit, after guardrails
  → adapter.send(thread_id, text)   # explicit, after dedup
```

**InboundLoop is the master orchestrator.** `handle_message` is never called. `_send_with_retry` is never called. `_background_tasks` stays empty.

---

## 7 — register() Contract

`register(ctx)` is the plugin entry point. It has no `self` — it's a module-level function.

```python
def register(ctx):
    ctx.register_platform(
        name="sns_addict",
        label="SNS Addict (Instagram)",
        adapter_factory=create_adapter,       # factory fn, NOT lambda cfg: SnsAddictAdapter(cfg)
        check_fn=check_requirements,          # patchright + chromium installed?
        validate_config=validate_config,      # username + dashboard_port present?
        is_connected=is_connected,            # thin wrapper around adapter.is_connected
        required_env=[],                      # no required env vars (uses OPENAI_API_KEY from Hermes)
        install_hint="hermes plugins install cosmosjeon/sns-addict",
        setup_fn=interactive_setup,           # W3.6 — interactive login flow
        emoji="📸",
        platform_hint=(
            "Instagram DMs as deski.ai (SNS-addict persona). "
            "Korean casual voice. Mood-driven activity. "
            "See ~/.hermes/SOUL.md for persona definition."
        ),
    )
```

**12 arguments** to `ctx.register_platform`: `name`, `label`, `adapter_factory`, `check_fn`, `validate_config`, `is_connected`, `required_env`, `install_hint`, `setup_fn`, `emoji`, `platform_hint` — that's 11. The 12th is implicit: Hermes also reads `platform_hint` as a string (not a list), so no `platform_hint_list` arg exists.

### adapter_factory vs. lambda

Use a named `create_adapter(cfg)` function, not an inline lambda. The factory must:
1. Instantiate `SnsAddictAdapter(cfg, Platform.SNS_ADDICT)`
2. Spawn the `state.json` watcher task (W3.5)
3. Return the adapter instance

```python
def create_adapter(cfg: PlatformConfig) -> SnsAddictAdapter:
    adapter = SnsAddictAdapter(cfg, Platform.SNS_ADDICT)
    # state.json watcher spawned in adapter.connect(), not here
    return adapter
```

### register() rules

- No `self` — this is a module-level function, not a method.
- No adapter instance at registration time — only the factory is registered.
- `setup_fn` is called by `hermes sns-addict setup` (W3.6). It's not called on every connect.
- `check_fn` is called by `hermes plugins check sns-addict`. It should verify patchright and Chromium are installed.

---

### Quick Reference

| Symbol | Where | Role |
|--------|-------|------|
| `BasePlatformAdapter` | `base.py:1206` | ABC — subclass this |
| `MessageEvent` | `base.py:870` | Inbound event dataclass |
| `SendResult` | `base.py` | Return type of `send()` |
| `asyncio.create_task` | `_on_dom_event` | Keep DOM callback < 50ms |
| `InboundLoop` | `sns_addict/inbound_loop.py` | Master orchestrator (W3.2) |
| `invoke_llm` | `sns_addict/adapter.py` | OpenAI direct call (W3.1) |
| `handle_message` | `base.py:2525` | Hermes core — NEVER call from sns-addict |
| `_send_with_retry` | `base.py:2192` | Hermes core — NEVER call from sns-addict |

---

*Last updated: 2026-05-05. Verified against Hermes v0.12.0.*
