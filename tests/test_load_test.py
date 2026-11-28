"""Yük testi istatistiklerinin ve giriş doğrulamasının küçük kontrolleri."""

import pytest

from tools.load_test import _percentile, run_benchmark_pass


def test_percentile_uses_linear_interpolation():
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.5
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.95) == pytest.approx(3.85)


def test_percentile_handles_empty_values():
    assert _percentile([], 0.95) == 0.0


@pytest.mark.parametrize("requests,concurrency", [(0, 1), (-1, 1), (1, 0), (1, -1)])
def test_load_test_rejects_non_positive_arguments(requests, concurrency):
    with pytest.raises(ValueError):
        run_benchmark_pass(total_requests=requests, concurrency=concurrency)
