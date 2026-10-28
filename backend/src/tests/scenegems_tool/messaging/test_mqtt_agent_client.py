"""The ArduAgent client's conversion of normalized thrust to RC override PWM."""

import pytest

from scenegems_tool.messaging.mqtt_agent_client import normalized_to_pwm


class TestNormalizedToPwm:
    @pytest.mark.parametrize("value,pwm", [(0.0, 1500), (1.0, 2000), (-1.0, 1000), (0.5, 1750), (-0.5, 1250)])
    def test_maps_to_the_standard_range(self, value, pwm):
        assert normalized_to_pwm(value) == pwm

    @pytest.mark.parametrize("value,pwm", [(2.0, 2000), (-7.5, 1000)])
    def test_values_outside_are_clamped(self, value, pwm):
        assert normalized_to_pwm(value) == pwm

    def test_result_is_an_integer(self):
        assert isinstance(normalized_to_pwm(0.123), int)
