# =============================================================================
# HYDRA-UMC-BRIDGE-DROIDS - tests/test_walk_limits.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The limits of a platform profile on a walk: distance, speed and forbidden zones, enforced where the command is sent."""

import math
import unittest

from hydra_umc_bridge_droids import DroidCoordinator, DroidDispatch, SpotDroidControl
from hydra_umc_bridge_droids.platform_profiles import MOBILE_ONLY, ForbiddenZone, PlatformProfile
from hydra_umc_bridge_droids.spot_transport import bosdyn_speed_params


class Builder:
    def __init__(self):
        self.calls = []

    def synchro_trajectory_command_in_body_frame(self, x, y, heading, snapshot, params=None):
        self.calls.append((x, y, heading, params))
        return "WALK"


class Sink:
    def __init__(self):
        self.sent = []

    def robot_command(self, command, end_time_secs=None):
        self.sent.append(command)
        return None


def walk(x, y):
    return DroidDispatch(True, DroidCoordinator.WALK_TO, "ok", parameters={"x": x, "y": y})


def go(profile, x, y, **extra):
    builder, sink = Builder(), Sink()
    kwargs = dict(profile.walk_limits())
    kwargs.update(extra)
    result = SpotDroidControl().walk_to(builder, sink, walk(x, y), frame_tree_snapshot=None, command_timeout_s=5.0, **kwargs)
    return result, builder, sink


def profile(**kw):
    return PlatformProfile("test", MOBILE_ONLY.actions, **kw)


class ZoneTests(unittest.TestCase):
    ZONE = ForbiddenZone("stairs", 2.0, -1.0, 3.0, 1.0)

    def test_a_goal_inside_the_zone_is_refused(self):
        result, _, sink = go(profile(forbidden_zones=(self.ZONE,)), 2.5, 0.0)
        self.assertFalse(result.sent)
        self.assertIn("stairs", result.reason)
        self.assertEqual(sink.sent, [])

    def test_a_straight_walk_through_the_zone_is_refused_even_if_it_ends_beyond(self):
        self.assertFalse(go(profile(forbidden_zones=(self.ZONE,)), 5.0, 0.0)[0].sent)

    def test_a_walk_that_passes_beside_the_zone_is_sent(self):
        result, builder, _ = go(profile(forbidden_zones=(self.ZONE,)), 5.0, 4.0)
        self.assertTrue(result.sent)
        self.assertEqual(len(builder.calls), 1)

    def test_a_goal_short_of_the_zone_is_sent(self):
        self.assertTrue(go(profile(forbidden_zones=(self.ZONE,)), 1.9, 0.0)[0].sent)

    def test_touching_the_edge_counts_as_inside(self):
        self.assertFalse(go(profile(forbidden_zones=(self.ZONE,)), 2.0, 0.0)[0].sent)

    def test_a_zone_around_the_robot_blocks_every_walk(self):
        around = ForbiddenZone("around", -1.0, -1.0, 1.0, 1.0)
        self.assertFalse(go(profile(forbidden_zones=(around,)), 0.0, 3.0)[0].sent)

    def test_a_zone_that_is_not_valid_cannot_be_built(self):
        for args in (("", 0, 0, 1, 1), ("z", 2, 0, 1, 1), ("z", 0, 2, 1, 1), ("z", math.nan, 0, 1, 1), ("z", 0, 0, math.inf, 1), ("z", True, 0, 1, 1)):
            with self.assertRaises(ValueError, msg=args):
                ForbiddenZone(*args)

    def test_any_of_several_zones_blocks(self):
        far = ForbiddenZone("far", 50.0, 50.0, 60.0, 60.0)
        self.assertFalse(go(profile(forbidden_zones=(far, self.ZONE)), 2.5, 0.0)[0].sent)


class SpeedTests(unittest.TestCase):
    def test_the_speed_limit_is_handed_to_the_command(self):
        result, builder, _ = go(profile(max_speed_mps=0.5), 1.0, 0.0, speed_params=lambda v: ("limit", v))
        self.assertTrue(result.sent)
        self.assertEqual(builder.calls[0][3], ("limit", 0.5))

    def test_a_speed_limit_that_cannot_be_applied_refuses_the_walk(self):
        result, builder, sink = go(profile(max_speed_mps=0.5), 1.0, 0.0)
        self.assertFalse(result.sent)
        self.assertEqual((builder.calls, sink.sent), ([], []))

    def test_no_speed_limit_sends_the_command_without_parameters(self):
        _, builder, _ = go(profile(), 1.0, 0.0)
        self.assertIsNone(builder.calls[0][3])

    def test_bad_speed_values_are_refused_by_the_profile_and_the_transport(self):
        for value in (0, -1, math.nan, math.inf, True, "1"):
            with self.assertRaises(ValueError, msg=value):
                profile(max_speed_mps=value)
        self.assertFalse(go(profile(), 1.0, 0.0, max_speed_mps=0, speed_params=lambda v: v)[0].sent)

    def test_the_speed_helper_says_clearly_when_bosdyn_is_missing(self):
        try:
            import bosdyn.api  # noqa: F401
        except ImportError:
            with self.assertRaises(RuntimeError):
                bosdyn_speed_params(0.5)


class DefaultsTests(unittest.TestCase):
    def test_the_builtin_profiles_set_no_limit(self):
        self.assertEqual(MOBILE_ONLY.walk_limits(), {"max_distance_m": None, "max_speed_mps": None, "forbidden_zones": ()})

    def test_all_three_limits_apply_together(self):
        limited = profile(max_walk_distance_m=10.0, max_speed_mps=1.0, forbidden_zones=(ForbiddenZone("z", 4, 4, 5, 5),))
        self.assertFalse(go(limited, 11.0, 0.0, speed_params=lambda v: v)[0].sent)
        self.assertFalse(go(limited, 4.5, 4.5, speed_params=lambda v: v)[0].sent)
        self.assertTrue(go(limited, 6.0, 0.0, speed_params=lambda v: v)[0].sent)


if __name__ == "__main__":
    unittest.main()
