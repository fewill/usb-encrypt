"""Tests for quiet hours logic in notify_slack.py"""

from datetime import datetime, time as dtime
from unittest.mock import patch

from notify_slack import in_quiet_hours, next_delivery_time, DELIVER_AT


class TestInQuietHours:
    def _at(self, hour, minute=0):
        return datetime(2026, 4, 8, hour, minute, 0)

    def test_midnight_is_quiet(self):
        with patch("notify_slack.datetime") as mock_dt:
            mock_dt.now.return_value = self._at(0, 0)
            assert in_quiet_hours() is True

    def test_3am_is_quiet(self):
        with patch("notify_slack.datetime") as mock_dt:
            mock_dt.now.return_value = self._at(3, 0)
            assert in_quiet_hours() is True

    def test_7am_is_not_quiet(self):
        with patch("notify_slack.datetime") as mock_dt:
            mock_dt.now.return_value = self._at(7, 0)
            assert in_quiet_hours() is False

    def test_noon_is_not_quiet(self):
        with patch("notify_slack.datetime") as mock_dt:
            mock_dt.now.return_value = self._at(12, 0)
            assert in_quiet_hours() is False

    def test_10pm_is_quiet(self):
        with patch("notify_slack.datetime") as mock_dt:
            mock_dt.now.return_value = self._at(22, 0)
            assert in_quiet_hours() is True

    def test_just_before_quiet_start_is_not_quiet(self):
        with patch("notify_slack.datetime") as mock_dt:
            mock_dt.now.return_value = self._at(21, 59)
            assert in_quiet_hours() is False


class TestNextDeliveryTime:
    def _at(self, hour, minute=0):
        return datetime(2026, 4, 8, hour, minute, 0)

    def test_delivery_during_quiet_hours_is_today(self):
        with patch("notify_slack.datetime") as mock_dt:
            mock_dt.now.return_value = self._at(3, 0)
            ts = next_delivery_time()
            dt = datetime.fromtimestamp(ts)
            assert dt.hour == DELIVER_AT.hour
            assert dt.date() == self._at(3).date()

    def test_delivery_after_7am_is_tomorrow(self):
        with patch("notify_slack.datetime") as mock_dt:
            mock_dt.now.return_value = self._at(9, 0)
            ts = next_delivery_time()
            dt = datetime.fromtimestamp(ts)
            assert dt.hour == DELIVER_AT.hour
            assert dt.day == self._at(9).day + 1
