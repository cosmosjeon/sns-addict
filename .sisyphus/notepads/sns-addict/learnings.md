- Ported legacy guardrails as thin wrappers around existing persistence/state models.
- Volume cap needs `_store: StateStore` annotation and ignored update result to keep diagnostics clean.
- Dedup is intentionally in-memory with a 10-minute window; quiet hours uses local `datetime.now()` only.

- Guardrail smoke checks are reliable as a single `python -c` one-liner; multiline shell-embedded Python can break in this wrapper.

- BrowserSession.start() uses `async_playwright().start()` and `launch_persistent_context(...)`, so unit tests need to mock the start path directly.
- `click_first_matching()` checks `wait_for(state="visible")` on `.first`, not `is_visible()`, so selector tests should stub `wait_for` and assert click fallback behavior through exceptions.
- `freezegun` works cleanly for `time.time()`-based guardrail tests and for `datetime.datetime.now()`-based quiet-hours checks.
- A tiny `StateStore` subclass with `@override` is enough to satisfy type checks when mocking `VolumeCap` state reads.
- Guardrail tests stay diagnostics-clean when fixture params are annotated (`Path`, `pytest.MonkeyPatch`) and module constants are monkeypatched instead of touching real `~/.hermes` paths.
# 2026-05-05
- FastAPI TestClient needs `httpx` installed in the venv; otherwise dashboard route tests fail at collection.
- For persistence round-trips, set `pending_sends[*].queued_at` far enough in the future to avoid `_age_pending_sends()` mutating the payload.
- `StateStore.read()` corruption recovery renames the bad file to `*.json.corrupt-<ts>` and returns a fresh `State`.
