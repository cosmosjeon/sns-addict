- Ported legacy guardrails as thin wrappers around existing persistence/state models.
- Volume cap needs `_store: StateStore` annotation and ignored update result to keep diagnostics clean.
- Dedup is intentionally in-memory with a 10-minute window; quiet hours uses local `datetime.now()` only.

- Guardrail smoke checks are reliable as a single `python -c` one-liner; multiline shell-embedded Python can break in this wrapper.

- BrowserSession.start() uses `async_playwright().start()` and `launch_persistent_context(...)`, so unit tests need to mock the start path directly.
- `click_first_matching()` checks `wait_for(state="visible")` on `.first`, not `is_visible()`, so selector tests should stub `wait_for` and assert click fallback behavior through exceptions.
