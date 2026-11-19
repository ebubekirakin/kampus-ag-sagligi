"""TCP bağlantı ve hız hesabı testleri; harici ağa istek göndermez."""

import unittest
from unittest.mock import MagicMock, patch

from client.network_tests import (
    calculate_speed_mbps,
    measure_download_speed,
    measure_tcp_latency_and_loss,
    measure_upload_speed,
    run_network_tests,
)


class TestNetworkMeasurements(unittest.TestCase):
    @patch("client.network_tests.socket.create_connection")
    @patch("client.network_tests.time.perf_counter", side_effect=[0, 0.01, 1, 2, 2.02])
    def test_tcp_median_and_failure_ratio(self, _clock, connect):
        connect.side_effect = [MagicMock(), OSError("test timeout"), MagicMock()]
        rtt, loss = measure_tcp_latency_and_loss("test.local:443", attempts=3)
        self.assertEqual(rtt, 15.0)
        self.assertEqual(loss, 33.3)

    @patch("client.network_tests.socket.create_connection")
    def test_invalid_target_makes_no_connection(self, connect):
        self.assertEqual(measure_tcp_latency_and_loss("", attempts=10), (None, None))
        connect.assert_not_called()

    def test_speed_formula_and_invalid_values(self):
        self.assertEqual(calculate_speed_mbps(1_000_000, 2), 4.0)
        self.assertIsNone(calculate_speed_mbps(0, 2))
        self.assertIsNone(calculate_speed_mbps(100, 0))

    def test_missing_urls_return_none_without_starting_http(self):
        with patch("client.network_tests.asyncio.run") as run_async:
            self.assertIsNone(measure_download_speed(""))
            self.assertIsNone(measure_upload_speed(""))
        run_async.assert_not_called()

    def test_missing_endpoints_return_none_without_network(self):
        self.assertEqual(
            run_network_tests({}),
            {"rtt_ms": None, "loss_pct": None, "down_mbps": None, "up_mbps": None},
        )


if __name__ == "__main__":
    unittest.main()
