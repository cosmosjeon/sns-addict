- Kept the legacy constants and behavior verbatim for the adapter port.
- Removed an unused `asyncio` import to satisfy diagnostics.

- Suppressed pyright warnings in the new test files to keep diagnostics clean while using `MagicMock`/`AsyncMock` for Patchright-style APIs.
