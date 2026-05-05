"""Tests for sns_addict.guardrails.volume_cap."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import override

import pytest
from freezegun import freeze_time

from sns_addict.persistence.state import SendCounters, State, StateStore


@dataclass
class FakeStateStore(StateStore):
    state: State

    @override
    async def read(self) -> State:
        return self.state


def _state(
    *,
    day_window_start: float,
    day_count: int = 0,
    per_friend_day: dict[str, int] | None = None,
    per_friend_hour: dict[str, list[float]] | None = None,
) -> State:
    return State(
        send_counters=SendCounters(
            day_window_start=day_window_start,
            day_count=day_count,
            per_friend_day=per_friend_day or {},
            per_friend_hour=per_friend_hour or {},
        )
    )


@pytest.mark.asyncio
@freeze_time("2026-05-05 12:00:00")
async def test_volume_under_cap_passes():
    from sns_addict.guardrails.volume_cap import VolumeCap

    now = time.time()
    vc = VolumeCap(FakeStateStore(_state(day_window_start=now, day_count=0)))

    assert await vc.exceeded("thread-1") is False


@pytest.mark.asyncio
@freeze_time("2026-05-05 12:00:00")
async def test_volume_hourly_friend_cap():
    from sns_addict.guardrails.volume_cap import VolumeCap

    now = time.time()
    vc = VolumeCap(
        FakeStateStore(
            _state(
                day_window_start=now,
                per_friend_hour={"thread-1": [now - 10, now - 20, now - 30, now - 40, now - 50]},
            )
        )
    )

    assert await vc.exceeded("thread-1") is True


@pytest.mark.asyncio
@freeze_time("2026-05-05 12:00:00")
async def test_volume_daily_friend_cap():
    from sns_addict.guardrails.volume_cap import VolumeCap

    now = time.time()
    vc = VolumeCap(
        FakeStateStore(
            _state(day_window_start=now, per_friend_day={"thread-1": 20})
        )
    )

    assert await vc.exceeded("thread-1") is True


@pytest.mark.asyncio
@freeze_time("2026-05-05 12:00:00")
async def test_volume_global_daily_cap():
    from sns_addict.guardrails.volume_cap import VolumeCap

    vc = VolumeCap(FakeStateStore(_state(day_window_start=time.time(), day_count=50)))

    assert await vc.exceeded("thread-1") is True


@pytest.mark.asyncio
@freeze_time("2026-05-05 13:00:00")
async def test_volume_day_window_rollover():
    from sns_addict.guardrails.volume_cap import VolumeCap

    now = time.time()
    vc = VolumeCap(FakeStateStore(_state(day_window_start=now - (25 * 3600), day_count=50)))

    assert await vc.exceeded("thread-1") is False
