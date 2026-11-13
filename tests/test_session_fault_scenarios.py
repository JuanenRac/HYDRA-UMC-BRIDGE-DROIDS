# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - tests/test_session_fault_scenarios.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Fault scenarios of the Spot session against simulated handles: a robot that loses its e-stop, its lease or its link, a battery that sinks, a state that goes
stale, and a seeded storm of faults over hundreds of keep-alive rounds. The simulation uses fakes only: nothing here talks to a robot.

The rule under test is the one the session exists for: it fails closed. After a cut the session is never ready again and the state it reports is SAFE_STOP."""

import math
import random
import unittest

from hydra_umc_sdk.bridge_contract import MachineState

from hydra_umc_bridge_droids import SpotSession, SpotSessionConfig


def robot_state(motor="STATE_ON", battery=80.0, posture="STANDING", faults=None, wrap=True):
    level = {"value": battery} if wrap else battery
    state = {
        "power_state": {"motor_power_state": motor},
        "battery_states": [{"charge_percentage": level}] if battery is not None else [],
        "kinematic_state": {"posture": posture},
    }
    if faults:
        state["behavior_fault_state"] = {"faults": faults}
    return state


class SimEstop:
    def __init__(self):
        self.calls, self.check_in_ok, self.raise_on = [], True, set()

    def _do(self, name):
        self.calls.append(name)
        if name in self.raise_on:
            raise OSError(f"estop {name} unreachable")

    def register(self):
        self._do("register")

    def allow(self):
        self._do("allow")

    def cut(self):
        self._do("cut")

    def check_in(self):
        self._do("check_in")
        return self.check_in_ok


class SimLease:
    def __init__(self):
        self.alive, self.calls, self.raise_on = True, [], set()

    def _do(self, name):
        self.calls.append(name)
        if name in self.raise_on:
            raise OSError(f"lease {name} unreachable")

    def acquire(self):
        self._do("acquire")

    def is_alive(self):
        self._do("is_alive")
        return self.alive

    def release(self):
        self._do("release")


class SimPower:
    def __init__(self):
        self.calls, self.result, self.raises = [], True, False

    def power_on(self, timeout_s):
        self.calls.append("on")
        if self.raises:
            raise OSError("power service unreachable")
        return self.result

    def power_off(self, timeout_s):
        self.calls.append("off")
        if self.raises:
            raise OSError("power service unreachable")
        return True


class SimState:
    def __init__(self):
        self.state, self.mode = robot_state(), "ok"

    def get_robot_state(self):
        if self.mode == "raise":
            raise OSError("link down")
        if self.mode == "none":
            return None
        if self.mode == "garbage":
            return ["not", "a", "mapping"]
        return self.state


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Bench(unittest.TestCase):
    def build(self, **config):
        self.estop, self.lease, self.power, self.reader, self.clock = SimEstop(), SimLease(), SimPower(), SimState(), Clock()
        return SpotSession(self.estop, self.lease, self.power, self.reader, SpotSessionConfig(**config), clock=self.clock)

    def assertCut(self, session, text=""):
        self.assertFalse(session.ready)
        self.assertTrue(session.cut_reason)
        self.assertIn(text, session.cut_reason)
        self.assertEqual(session.observed_machine_state(), MachineState.SAFE_STOP)
        self.assertIn("cut", self.estop.calls)


class BringUpFaults(Bench):
    def test_a_healthy_bring_up(self):
        session = self.build()
        result = session.bring_up()
        self.assertTrue(result.ok and session.ready)
        self.assertEqual(result.steps, ("estop registered", "estop allows motion", "lease acquired"))
        self.assertEqual(self.power.calls, [])  # motors stay off unless the operator asked

    def test_each_step_that_fails_cuts_and_names_the_last_good_step(self):
        cases = [
            (lambda: self.estop.raise_on.add("register"), "nothing"),
            (lambda: self.estop.raise_on.add("allow"), "estop registered"),
            (lambda: self.lease.raise_on.add("acquire"), "estop allows motion"),
        ]
        for arrange, last_good in cases:
            session = self.build()
            arrange()
            result = session.bring_up()
            self.assertFalse(result.ok)
            self.assertIn(f"after {last_good}", result.reason)
            self.assertCut(session)
            self.assertEqual(self.power.calls, [], "no power is ever asked for after a failed bring-up")

    def test_an_unreadable_state_stops_the_bring_up(self):
        for mode in ("raise", "none", "garbage"):
            session = self.build()
            self.reader.mode = mode
            result = session.bring_up()
            self.assertFalse(result.ok, mode)
            self.assertCut(session, "could not be read")

    def test_battery_exactly_at_the_floor_passes_and_just_under_does_not(self):
        session = self.build(min_battery_pct=20.0)
        self.reader.state = robot_state(battery=20.0)
        self.assertTrue(session.bring_up().ok)
        session = self.build(min_battery_pct=20.0)
        self.reader.state = robot_state(battery=19.99)
        result = session.bring_up()
        self.assertFalse(result.ok)
        self.assertIn("floor", result.reason)

    def test_the_battery_may_be_a_plain_number_or_missing_or_junk(self):
        for battery, wrap, ok in ((55.0, False, True), (None, True, True), (5.0, False, False)):
            session = self.build()
            self.reader.state = robot_state(battery=battery, wrap=wrap)
            self.assertEqual(session.bring_up().ok, ok, battery)
        session = self.build()
        self.reader.state = {"battery_states": [None, "x", {"charge_percentage": "high"}, {"charge_percentage": True}, {"charge_percentage": math.nan}]}
        self.assertTrue(session.bring_up().ok, "junk entries are ignored, not trusted and not fatal")

    def test_the_lowest_of_several_batteries_decides(self):
        session = self.build()
        self.reader.state = {"battery_states": [{"charge_percentage": 90}, {"charge_percentage": {"value": 10}}]}
        self.assertFalse(session.bring_up().ok)

    def test_power_on_failures(self):
        for arrange, text in ((lambda: setattr(self.power, "result", False), "did not power on"), (lambda: setattr(self.power, "raises", True), "power on failed")):
            session = self.build(power_on_after_bring_up=True)
            arrange()
            result = session.bring_up()
            self.assertFalse(result.ok)
            self.assertCut(session, text)

    def test_power_on_when_asked(self):
        session = self.build(power_on_after_bring_up=True)
        result = session.bring_up()
        self.assertTrue(result.ok)
        self.assertEqual(result.steps[-1], "motors powered on")

    def test_invalid_settings_stop_the_bring_up_before_anything_is_touched(self):
        for change in ({"estop_timeout_s": 0}, {"min_battery_pct": 101}, {"min_battery_pct": True}, {"home_waypoint": "  "}, {"tick_interval_s": math.inf}, {"max_link_loss_s": -1}, {"cut_on_link_loss": "yes"}, {"power_on_after_bring_up": 1}):
            session = self.build(**change)
            result = session.bring_up()
            self.assertFalse(result.ok, change)
            self.assertIn("invalid session configuration", result.reason)
            self.assertEqual((self.estop.calls, self.lease.calls), ([], []), "nothing is touched with a bad configuration")


class KeepAliveFaults(Bench):
    def up(self, **config):
        session = self.build(**config)
        self.assertTrue(session.bring_up().ok)
        return session

    def test_a_session_that_is_not_ready_never_ticks_the_robot(self):
        session = self.build()
        before = list(self.estop.calls)
        self.assertFalse(session.tick().ok)
        self.assertEqual(self.estop.calls, before)

    def test_a_lost_lease_a_refused_check_in_and_unreachable_services_all_cut(self):
        scenarios = {
            "lease taken": lambda: setattr(self.lease, "alive", False),
            "check-in refused": lambda: setattr(self.estop, "check_in_ok", False),
            "check-in unreachable": lambda: self.estop.raise_on.add("check_in"),
            "lease service unreachable": lambda: self.lease.raise_on.add("is_alive"),
        }
        for name, arrange in scenarios.items():
            session = self.up()
            arrange()
            result = session.tick()
            self.assertFalse(result.ok, name)
            self.assertCut(session)
            self.assertFalse(session.tick().ok, "a cut session stays cut")

    def test_a_cut_that_itself_fails_does_not_raise(self):
        session = self.up()
        self.estop.raise_on.add("cut")
        self.lease.alive = False
        self.assertFalse(session.tick().ok)
        self.assertFalse(session.ready)

    def test_cut_from_outside_keeps_the_first_reason(self):
        session = self.up()
        session.cut("global stop")
        session.cut("zone violation")
        self.assertEqual(session.cut_reason, "global stop")
        self.assertEqual(session.observed_machine_state(), MachineState.SAFE_STOP)

    def test_a_silent_link_is_noticed_but_only_cuts_when_the_operator_said_so(self):
        session = self.up(max_link_loss_s=10.0)
        self.reader.mode = "raise"
        self.clock.now += 3
        result = session.tick()
        self.assertTrue(result.ok and "could not be refreshed" in result.reason)
        self.clock.now += 9.5  # the silence is counted from the first reading that failed
        self.assertFalse(session.link_lost)
        self.clock.now += 0.5
        self.assertTrue(session.link_lost)
        self.assertTrue(session.tick().ok, "cut_on_link_loss is off by default: the robot's own timeouts decide")
        self.assertTrue(session.ready)

    def test_with_the_switch_on_the_link_watchdog_cuts_at_the_limit(self):
        session = self.up(max_link_loss_s=10.0, cut_on_link_loss=True)
        self.reader.mode = "none"
        self.assertTrue(session.tick().ok)  # the first silent reading starts the count
        self.clock.now += 9.0
        self.assertTrue(session.tick().ok)
        self.clock.now += 1.0
        result = session.tick()
        self.assertFalse(result.ok)
        self.assertCut(session, "silent for 10 s")

    def test_a_link_that_comes_back_resets_the_watchdog(self):
        session = self.up(max_link_loss_s=10.0, cut_on_link_loss=True)
        self.reader.mode = "raise"
        self.assertTrue(session.tick().ok)
        self.clock.now += 8
        self.assertTrue(session.tick().ok)
        self.reader.mode = "ok"
        self.assertTrue(session.tick().ok)
        self.assertEqual(session.link_silent_s, 0.0)
        self.reader.mode = "raise"
        self.assertTrue(session.tick().ok)
        self.clock.now += 8
        self.assertTrue(session.tick().ok, "the silence is counted again from zero")


class ObservedState(Bench):
    def up(self, state, **config):
        session = self.build(**config)
        self.reader.state = state
        self.assertTrue(session.bring_up().ok)
        return session

    def test_the_mapping_of_robot_state_to_machine_state(self):
        cases = [
            (robot_state(motor="STATE_ESTOPPED"), MachineState.STOPPED),
            (robot_state(faults=["LEG_BLOCKED"]), MachineState.FAULT),
            (robot_state(motor="STATE_OFF"), MachineState.OFFLINE),
            (robot_state(battery=20.0), MachineState.IDLE),
            (robot_state(posture="MOVING"), MachineState.RUNNING),
            (robot_state(posture="SITTING"), MachineState.IDLE),
        ]
        for state, expected in cases:
            self.assertEqual(self.up(state).observed_machine_state(), expected, state)

    def test_a_sinking_battery_means_holding(self):
        session = self.up(robot_state(battery=60.0), min_battery_pct=20.0)
        self.assertEqual(session.observed_machine_state(), MachineState.IDLE)
        self.reader.state = robot_state(battery=19.0)
        self.assertTrue(session.tick().ok)
        self.assertEqual(session.observed_machine_state(), MachineState.HOLDING)

    def test_a_reading_older_than_the_limit_is_not_trusted(self):
        session = self.up(robot_state(), max_state_age_s=5.0)
        self.clock.now += 5.0
        self.assertEqual(session.observed_machine_state(), MachineState.IDLE)
        self.clock.now += 0.001
        self.assertIsNone(session.observed_machine_state())

    def test_estop_wins_over_everything_else_in_the_same_reading(self):
        session = self.up(robot_state(motor="STATE_ESTOPPED", faults=["X"], battery=1.0, posture="MOVING"), min_battery_pct=0.0)
        self.assertEqual(session.observed_machine_state(), MachineState.STOPPED)

    def test_no_reading_yet_is_none_and_not_idle(self):
        self.assertIsNone(self.build().observed_machine_state())


class Shutdown(Bench):
    def test_shutdown_never_raises_whatever_fails(self):
        session = self.build()
        session.bring_up()
        self.power.raises = True
        self.lease.raise_on.add("release")
        result = session.shutdown()
        self.assertTrue(result.ok)
        self.assertTrue(all("failed" in step for step in result.steps))
        self.assertFalse(session.ready)

    def test_an_orderly_shutdown_powers_off_then_releases(self):
        session = self.build()
        session.bring_up()
        result = session.shutdown()
        self.assertEqual(result.steps, ("motors powered off", "lease released"))
        self.assertEqual((self.power.calls, self.lease.calls[-1]), (["off"], "release"))


class FaultStorm(Bench):
    """Four hundred keep-alive rounds with faults drawn from a fixed seed. The invariants hold whatever the order of the faults."""

    def run_storm(self, seed):
        rng = random.Random(seed)
        session = self.build(max_link_loss_s=15.0, cut_on_link_loss=True)
        self.assertTrue(session.bring_up().ok)
        cut_at = None
        for round_number in range(400):
            self.clock.now += rng.choice((0.5, 1.0, 2.0))
            roll = rng.random()
            self.reader.mode = "ok" if roll < 0.8 else rng.choice(("raise", "none", "garbage"))
            self.reader.state = robot_state(battery=rng.uniform(15, 100), posture=rng.choice(("STANDING", "MOVING", "SITTING")))
            self.lease.alive = rng.random() > 0.002
            self.estop.check_in_ok = rng.random() > 0.002
            result = session.tick()
            if cut_at is None and not session.ready:
                cut_at = round_number
            if cut_at is not None:
                self.assertFalse(session.ready, "a cut session never becomes ready again")
                self.assertFalse(result.ok)
                self.assertEqual(session.observed_machine_state(), MachineState.SAFE_STOP)
            else:
                self.assertTrue(result.ok)
        return cut_at, list(self.estop.calls)

    def test_the_invariants_hold_over_twenty_seeds(self):
        outcomes = [self.run_storm(seed) for seed in range(20)]
        self.assertTrue(any(cut is not None for cut, _ in outcomes), "the storm must be rough enough to cut at least once")
        for cut, calls in outcomes:
            if cut is not None:
                self.assertEqual(calls.count("cut"), 1, "the e-stop is cut exactly once")

    def test_the_same_seed_gives_the_same_storm(self):
        self.assertEqual(self.run_storm(7), self.run_storm(7))


if __name__ == "__main__":
    unittest.main()
