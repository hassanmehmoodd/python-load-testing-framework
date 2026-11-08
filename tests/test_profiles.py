"""Load profile stage plans."""

import pytest

from perfload.profiles import PROFILE_SHAPES, build_stages


@pytest.mark.parametrize("profile", sorted(PROFILE_SHAPES))
def test_stages_are_monotonic_and_finish_on_duration(profile):
    stages = build_stages(profile, users=10, spawn_rate=2, duration_seconds=40)
    assert stages[-1].end == 40
    assert all(stages[index].end < stages[index + 1].end for index in range(len(stages) - 1))
    assert all(1 <= stage.users <= 10 for stage in stages)
    assert all(stage.spawn_rate == 2 for stage in stages)


def test_ramp_steps_up():
    stages = build_stages("ramp", users=8, spawn_rate=2, duration_seconds=40)
    assert [stage.users for stage in stages] == [2, 4, 6, 8]


def test_spike_jumps_and_returns():
    stages = build_stages("spike", users=10, spawn_rate=5, duration_seconds=40)
    assert stages[0].users == 2
    assert stages[1].users == 10
    assert stages[-1].users == 2


def test_stress_holds_the_peak():
    stages = build_stages("stress", users=20, spawn_rate=4, duration_seconds=40)
    assert stages[-1].users == 20
    assert stages[-2].users == 20
    assert stages[-1].end - stages[-2].end > stages[0].end


def test_endurance_holds_after_a_short_ramp():
    stages = build_stages("endurance", users=8, spawn_rate=2, duration_seconds=45)
    assert len(stages) == 2
    assert stages[0].users == 8
    assert stages[1].users == 8
    assert stages[1].end == 45
    assert stages[0].end < stages[1].end / 2


def test_short_duration_still_ends_cleanly():
    stages = build_stages("ramp", users=5, spawn_rate=1, duration_seconds=5)
    assert stages[-1].end == 5
    assert stages[-1].users == 5


def test_unknown_profile():
    with pytest.raises(ValueError, match="Unknown profile"):
        build_stages("tsunami", users=1, spawn_rate=1, duration_seconds=5)
