import math
import unittest

import numpy as np
from haversine import Unit

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.contracts.sim_utils import (
    Geofence,
    from_true_north,
    to_true_north,
    true_north_heading,
    waypoint_from_state,
)


class TestSimUtils(unittest.TestCase):
    def setUp(self) -> None:
        self.geofence = Geofence(57.757128, 16.673189, 1000)

    def test_geofence_center_property(self):
        center = self.geofence.center
        np.testing.assert_allclose(center, np.array([57.757128, 16.673189]))

    def test_geofence_contains_center(self):
        self.assertTrue(self.geofence.contains(self.geofence.latitude, self.geofence.longitude))

    def test_geofence_contains_points_within_the_radius(self):
        lat, lon = self.geofence.latitude, self.geofence.longitude
        self.assertTrue(self.geofence.contains(lat + 0.005, lon))  # about 556 m north
        self.assertTrue(self.geofence.contains(lat, lon - 0.005))  # about 295 m west

    def test_geofence_excludes_points_beyond_the_radius(self):
        lat, lon = self.geofence.latitude, self.geofence.longitude
        self.assertFalse(self.geofence.contains(lat + 0.01, lon))  # about 1.1 km
        self.assertFalse(self.geofence.contains(lat, lon + 0.02))

    def test_geofence_edge_is_inside_and_one_meter_beyond_is_outside(self):
        border = self.geofence.to_lat_long(np.array([self.geofence.radius_meters - 0.01, 0.0]))
        self.assertTrue(self.geofence.contains(border[0], border[1]))
        beyond = self.geofence.to_lat_long(np.array([self.geofence.radius_meters + 1.0, 0.0]))
        self.assertFalse(self.geofence.contains(beyond[0], beyond[1]))

    def test_geofence_with_zero_radius_contains_only_its_center(self):
        point = Geofence(57.757128, 16.673189, 0.0)
        self.assertTrue(point.contains(57.757128, 16.673189))
        self.assertFalse(point.contains(57.757138, 16.673189))

    def test_to_true_north_degrees(self):
        self.assertAlmostEqual(to_true_north(0.0, Unit.DEGREES), 90.0)
        self.assertAlmostEqual(to_true_north(90.0, Unit.DEGREES), 360.0)  # north is 360, not 0
        self.assertAlmostEqual(to_true_north(-90.0, Unit.DEGREES), 180.0)

    def test_to_true_north_radians(self):
        self.assertAlmostEqual(to_true_north(0.0, Unit.RADIANS), math.pi / 2)
        self.assertAlmostEqual(to_true_north(math.pi / 2, Unit.RADIANS), 2 * math.pi)  # north is 2 pi, not 0

    def test_to_true_north_invalid_unit(self):
        with self.assertRaises(ValueError):
            to_true_north(0.0, Unit.METERS)

    def test_from_true_north_degrees(self):
        self.assertAlmostEqual(from_true_north(0.0, Unit.DEGREES), 90.0)
        self.assertAlmostEqual(from_true_north(90.0, Unit.DEGREES), 0.0)
        self.assertAlmostEqual(from_true_north(270.0, Unit.DEGREES), -180.0)  # headings are in [-180, 180)
        self.assertAlmostEqual(from_true_north(360.0, Unit.DEGREES), 90.0)  # 360 is north, as 0

    def test_from_true_north_radians(self):
        self.assertAlmostEqual(from_true_north(0.0, Unit.RADIANS), math.pi / 2)
        self.assertAlmostEqual(from_true_north(math.pi / 2, Unit.RADIANS), 0.0)

    def test_true_north_heading_axis_aligned(self):
        east = true_north_heading(np.array([0.0, 0.0]), np.array([1.0, 0.0]), unit=Unit.DEGREES)
        north = true_north_heading(np.array([0.0, 0.0]), np.array([0.0, 1.0]), unit=Unit.DEGREES)
        west = true_north_heading(np.array([0.0, 0.0]), np.array([-1.0, 0.0]), unit=Unit.DEGREES)
        south = true_north_heading(np.array([0.0, 0.0]), np.array([0.0, -1.0]), unit=Unit.DEGREES)

        self.assertAlmostEqual(east, 90.0)
        self.assertAlmostEqual(north, 360.0)
        self.assertAlmostEqual(west, 270.0)
        self.assertAlmostEqual(south, 180.0)

    def test_true_north_heading_invalid_unit(self):
        with self.assertRaises(ValueError):
            true_north_heading(np.array([0.0, 0.0]), np.array([1.0, 1.0]), unit=Unit.METERS)

    def test_coord_to_lat_long_returns_center_for_zero_vector(self):
        lat_long = self.geofence.to_lat_long(np.array([0.0, 0.0]))
        np.testing.assert_allclose(lat_long, self.geofence.center)

    def test_lat_long_coord_round_trip(self):
        original = np.array([120.0, -85.0])
        lat_long = self.geofence.to_lat_long(original)
        round_trip = self.geofence.to_coord(lat_long[0], lat_long[1])

        # Geodesic conversion and bearing calculations introduce tiny floating-point drift.
        np.testing.assert_allclose(round_trip, original, atol=0.2)

    def test_geodetic_cardinal_directions_in_the_local_frame(self):
        """Points 0.01 degrees away, converted to the local frame, lie in the cardinal true-north directions.

        The local frame is UTM, whose grid north differs from true north by the meridian convergence
        (about 1.4 degrees here, 16.7 E in a zone centered on 15 E), hence the 2 degree tolerance.
        """
        origin = np.zeros(2)
        lat, lon = self.geofence.latitude, self.geofence.longitude
        expected = {"north": (lat + 0.01, lon, 360.0), "east": (lat, lon + 0.01, 90.0), "south": (lat - 0.01, lon, 180.0), "west": (lat, lon - 0.01, 270.0)}
        for name, (point_lat, point_lon, bearing) in expected.items():
            heading = true_north_heading(origin, self.geofence.to_coord(point_lat, point_lon), unit=Unit.DEGREES)
            difference = abs((heading - bearing + 180.0) % 360.0 - 180.0)
            self.assertLess(difference, 2.0, f"{name}: {heading}")

    def test_waypoint_from_state(self):
        state = ActorState(x=100.0, y=50.0, speed=3.0, heading=0.0)
        waypoint = waypoint_from_state(state, self.geofence)

        self.assertEqual(waypoint["altitude"], 0)
        self.assertEqual(waypoint["rostype"], "GeoPoint")
        self.assertIn("latitude", waypoint)
        self.assertIn("longitude", waypoint)

        expected_lat_long = self.geofence.to_lat_long(state.p)
        self.assertAlmostEqual(waypoint["latitude"], expected_lat_long[0])
        self.assertAlmostEqual(waypoint["longitude"], expected_lat_long[1])


if __name__ == "__main__":
    unittest.main()
