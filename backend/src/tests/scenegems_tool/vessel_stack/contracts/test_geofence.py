"""Geofence projection and the PWM helper of sim_utils.

The heading conversions of sim_utils (to_true_north, from_true_north, true_north_heading) are covered
by test_sim_utils.py, whose expectations wait for a decision on their boundary conventions.
"""

import numpy as np
import pytest

from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence, normalized_to_pwm


class TestUtmZone:
    @pytest.mark.parametrize(
        "latitude,longitude,epsg",
        [(57.757128, 16.673189, "EPSG:32633"), (-33.9, 18.4, "EPSG:32734"), (0.0, -179.9, "EPSG:32601"), (51.5, -0.1, "EPSG:32630")],
    )
    def test_zone_and_hemisphere(self, latitude, longitude, epsg):
        assert Geofence(latitude, longitude, 1000).utm_epsg == epsg


class TestProjection:
    def test_the_center_is_the_local_origin(self):
        geofence = Geofence(57.757128, 16.673189, 1000)
        np.testing.assert_allclose(geofence.to_coord(57.757128, 16.673189), [0.0, 0.0], atol=1e-6)

    def test_north_is_plus_y_and_east_is_plus_x(self):
        geofence = Geofence(57.757128, 16.673189, 1000)
        north = geofence.to_coord(57.757128 + 0.001, 16.673189)
        east = geofence.to_coord(57.757128, 16.673189 + 0.001)
        assert north[1] > 100 and abs(north[0]) < 25, "0.001 degrees of latitude are about 111 m"
        assert east[0] > 50 and abs(east[1]) < 5

    def test_round_trip_within_a_decimeter(self):
        geofence = Geofence(57.757128, 16.673189, 1000)
        original = np.array([321.0, -654.0])
        np.testing.assert_allclose(geofence.to_coord(*geofence.to_lat_long(original)), original, atol=0.01)

    def test_southern_hemisphere_round_trip(self):
        geofence = Geofence(-33.9, 18.4, 1000)
        original = np.array([-50.0, 80.0])
        np.testing.assert_allclose(geofence.to_coord(*geofence.to_lat_long(original)), original, atol=0.01)

    def test_center_property_is_latitude_longitude(self):
        np.testing.assert_allclose(Geofence(1.0, 2.0, 3.0).center, [1.0, 2.0])

    def test_radius_is_kept_for_the_subsystem_environments(self):
        assert Geofence(1.0, 2.0, 3.5).radius_meters == 3.5


class TestNormalizedToPwm:
    @pytest.mark.parametrize("value,pwm", [(0.0, 1500), (1.0, 2000), (-1.0, 1000), (0.5, 1750), (-0.5, 1250)])
    def test_maps_to_the_standard_range(self, value, pwm):
        assert normalized_to_pwm(value) == pwm

    @pytest.mark.parametrize("value,pwm", [(2.0, 2000), (-7.5, 1000)])
    def test_values_outside_are_clamped(self, value, pwm):
        assert normalized_to_pwm(value) == pwm

    def test_result_is_an_integer(self):
        assert isinstance(normalized_to_pwm(0.123), int)
