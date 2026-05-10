# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportPrivateUsage=false, reportUnusedCallResult=false, reportMissingParameterType=false

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from sns_addict.utils.long_run import AutoStop, SleepRecovery


@pytest.mark.asyncio
async def test_auto_stop_fires_after_24h() -> None:
    mock_adapter = AsyncMock()
    auto_stop = AutoStop(mock_adapter)
    auto_stop._started_at = time.time() - (AutoStop.MAX_RUNTIME_SECONDS + 1)

    await auto_stop.watch()

    mock_adapter.halt.assert_awaited_once_with("24h auto-stop")


@pytest.mark.asyncio
async def test_sleep_recovery_reconnects() -> None:
    mock_adapter = AsyncMock()
    mock_adapter.is_connected = True

    recovery = SleepRecovery(mock_adapter)
    recovery._last_tick = time.time() - (SleepRecovery.SLEEP_GAP_THRESHOLD + 10)

    call_count = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    with patch("sns_addict.utils.long_run.asyncio.sleep", new=fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await recovery.watch()

    mock_adapter.disconnect.assert_awaited_once()
    mock_adapter.connect.assert_awaited_once()
