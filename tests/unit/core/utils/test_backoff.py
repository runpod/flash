"""Tests for backoff strategy implementation."""

import pytest

from runpod_flash.core.utils.backoff import BackoffStrategy, get_backoff_delay


class TestBackoffStrategy:
    """Test backoff strategy functionality."""

    def test_exponential_backoff(self):
        """Test exponential backoff strategy."""
        # Test with no jitter for predictable results
        delays = []
        for attempt in range(5):
            delay = get_backoff_delay(
                attempt=attempt,
                base=1.0,
                max_seconds=100.0,
                jitter=0.0,
                strategy=BackoffStrategy.EXPONENTIAL,
            )
            delays.append(delay)

        # Exponential: base * 2^attempt
        # attempt 0: 1.0 * 2^0 = 1.0
        # attempt 1: 1.0 * 2^1 = 2.0
        # attempt 2: 1.0 * 2^2 = 4.0
        # attempt 3: 1.0 * 2^3 = 8.0
        # attempt 4: 1.0 * 2^4 = 16.0
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0
        assert delays[3] == 8.0
        assert delays[4] == 16.0

    def test_linear_backoff(self):
        """Test linear backoff strategy."""
        delays = []
        for attempt in range(5):
            delay = get_backoff_delay(
                attempt=attempt,
                base=1.0,
                max_seconds=100.0,
                jitter=0.0,
                strategy=BackoffStrategy.LINEAR,
            )
            delays.append(delay)

        # Linear: base + (attempt * base)
        # attempt 0: 1.0 + (0 * 1.0) = 1.0
        # attempt 1: 1.0 + (1 * 1.0) = 2.0
        # attempt 2: 1.0 + (2 * 1.0) = 3.0
        # attempt 3: 1.0 + (3 * 1.0) = 4.0
        # attempt 4: 1.0 + (4 * 1.0) = 5.0
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 3.0
        assert delays[3] == 4.0
        assert delays[4] == 5.0

    def test_logarithmic_backoff(self):
        """Test logarithmic backoff strategy."""
        delays = []
        for attempt in range(5):
            delay = get_backoff_delay(
                attempt=attempt,
                base=1.0,
                max_seconds=100.0,
                jitter=0.0,
                strategy=BackoffStrategy.LOGARITHMIC,
            )
            delays.append(delay)

        # Logarithmic: base * log2(attempt + 2)
        import math

        expected = [
            1.0 * math.log2(0 + 2),  # log2(2) = 1.0
            1.0 * math.log2(1 + 2),  # log2(3) ≈ 1.585
            1.0 * math.log2(2 + 2),  # log2(4) = 2.0
            1.0 * math.log2(3 + 2),  # log2(5) ≈ 2.322
            1.0 * math.log2(4 + 2),  # log2(6) ≈ 2.585
        ]

        for i, (actual, exp) in enumerate(zip(delays, expected)):
            assert abs(actual - exp) < 0.001, f"Attempt {i}: {actual} != {exp}"

    def test_max_seconds_cap(self):
        """Test that delay is capped at max_seconds."""
        # Exponential backoff with small max
        delay = get_backoff_delay(
            attempt=10,  # Would be 1024 without cap
            base=1.0,
            max_seconds=5.0,
            jitter=0.0,
            strategy=BackoffStrategy.EXPONENTIAL,
        )

        assert delay == 5.0

    def test_jitter_adds_randomness(self):
        """Test that jitter adds randomness to delays."""
        delays = []
        for _ in range(100):
            delay = get_backoff_delay(
                attempt=3,
                base=1.0,
                max_seconds=100.0,
                jitter=0.2,  # ±20%
                strategy=BackoffStrategy.EXPONENTIAL,
            )
            delays.append(delay)

        # Base delay for attempt 3: 1.0 * 2^3 = 8.0
        # With 20% jitter: 8.0 * [0.8, 1.2] = [6.4, 9.6]
        min_delay = min(delays)
        max_delay = max(delays)

        # Should have some variation
        assert min_delay < 8.0
        assert max_delay > 8.0

        # Should be within jitter bounds
        assert min_delay >= 6.4
        assert max_delay <= 9.6

    def test_jitter_with_max_seconds(self):
        """Test that jitter is applied after max_seconds cap."""
        delays = []
        for _ in range(100):
            delay = get_backoff_delay(
                attempt=10,  # Would be 1024 without cap
                base=1.0,
                max_seconds=10.0,
                jitter=0.2,  # ±20%
                strategy=BackoffStrategy.EXPONENTIAL,
            )
            delays.append(delay)

        # Capped at 10.0, then jitter: 10.0 * [0.8, 1.2] = [8.0, 12.0]
        min_delay = min(delays)
        max_delay = max(delays)

        assert min_delay >= 8.0
        assert max_delay <= 12.0

    def test_base_parameter(self):
        """Test that base parameter affects delay magnitude."""
        delay_base_1 = get_backoff_delay(
            attempt=3,
            base=1.0,
            max_seconds=100.0,
            jitter=0.0,
            strategy=BackoffStrategy.EXPONENTIAL,
        )

        delay_base_2 = get_backoff_delay(
            attempt=3,
            base=2.0,
            max_seconds=100.0,
            jitter=0.0,
            strategy=BackoffStrategy.EXPONENTIAL,
        )

        # base=2.0 should give double the delay
        assert delay_base_2 == delay_base_1 * 2

    def test_small_base_value(self):
        """Test with small base value."""
        delay = get_backoff_delay(
            attempt=5,
            base=0.01,
            max_seconds=100.0,
            jitter=0.0,
            strategy=BackoffStrategy.EXPONENTIAL,
        )

        # 0.01 * 2^5 = 0.01 * 32 = 0.32
        assert delay == 0.32

    def test_zero_attempt(self):
        """Test delay for first attempt (attempt=0)."""
        delay = get_backoff_delay(
            attempt=0,
            base=1.0,
            max_seconds=100.0,
            jitter=0.0,
            strategy=BackoffStrategy.EXPONENTIAL,
        )

        # 1.0 * 2^0 = 1.0
        assert delay == 1.0

    def test_large_attempt_number(self):
        """Test that large attempt numbers don't cause overflow."""
        delay = get_backoff_delay(
            attempt=100,
            base=1.0,
            max_seconds=10.0,
            jitter=0.0,
            strategy=BackoffStrategy.EXPONENTIAL,
        )

        # Should be capped at max_seconds
        assert delay == 10.0

    def test_invalid_strategy(self):
        """Test that invalid strategy raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported backoff strategy"):
            get_backoff_delay(
                attempt=1,
                base=1.0,
                max_seconds=10.0,
                jitter=0.0,
                strategy="invalid_strategy",  # type: ignore
            )

    def test_exponential_with_default_params(self):
        """Test exponential backoff with default parameters."""
        # Default: base=0.1, max_seconds=10.0, jitter=0.2
        delays = []
        for attempt in range(10):
            delay = get_backoff_delay(
                attempt=attempt,
                strategy=BackoffStrategy.EXPONENTIAL,
            )
            delays.append(delay)

        # All delays should be positive
        assert all(d > 0 for d in delays)

        # Should not exceed max_seconds * (1 + jitter)
        assert all(d <= 10.0 * 1.2 for d in delays)

    def test_linear_stays_below_exponential(self):
        """Test that linear backoff grows slower than exponential."""
        linear_delays = []
        exponential_delays = []

        for attempt in range(10):
            linear = get_backoff_delay(
                attempt=attempt,
                base=1.0,
                max_seconds=1000.0,
                jitter=0.0,
                strategy=BackoffStrategy.LINEAR,
            )
            exponential = get_backoff_delay(
                attempt=attempt,
                base=1.0,
                max_seconds=1000.0,
                jitter=0.0,
                strategy=BackoffStrategy.EXPONENTIAL,
            )
            linear_delays.append(linear)
            exponential_delays.append(exponential)

        # After a few attempts, exponential should be larger
        assert exponential_delays[5] > linear_delays[5]
        assert exponential_delays[9] > linear_delays[9]

    def test_logarithmic_grows_slowest(self):
        """Test that logarithmic backoff grows slowest."""
        for attempt in [5, 10, 20]:
            log_delay = get_backoff_delay(
                attempt=attempt,
                base=1.0,
                max_seconds=1000.0,
                jitter=0.0,
                strategy=BackoffStrategy.LOGARITHMIC,
            )
            linear_delay = get_backoff_delay(
                attempt=attempt,
                base=1.0,
                max_seconds=1000.0,
                jitter=0.0,
                strategy=BackoffStrategy.LINEAR,
            )
            exp_delay = get_backoff_delay(
                attempt=attempt,
                base=1.0,
                max_seconds=1000.0,
                jitter=0.0,
                strategy=BackoffStrategy.EXPONENTIAL,
            )

            # Logarithmic should be smallest
            assert log_delay < linear_delay
            assert log_delay < exp_delay

    def test_consistency_with_same_seed(self):
        """Test that delays are consistent for same inputs (minus jitter)."""
        delay1 = get_backoff_delay(
            attempt=5,
            base=1.0,
            max_seconds=100.0,
            jitter=0.0,
            strategy=BackoffStrategy.EXPONENTIAL,
        )
        delay2 = get_backoff_delay(
            attempt=5,
            base=1.0,
            max_seconds=100.0,
            jitter=0.0,
            strategy=BackoffStrategy.EXPONENTIAL,
        )

        assert delay1 == delay2

    def test_enum_values(self):
        """Test that BackoffStrategy enum has expected values."""
        assert BackoffStrategy.EXPONENTIAL.value == "exponential"
        assert BackoffStrategy.LINEAR.value == "linear"
        assert BackoffStrategy.LOGARITHMIC.value == "logarithmic"

    def test_all_strategies_positive_delays(self):
        """Test that all strategies produce positive delays."""
        strategies = [
            BackoffStrategy.EXPONENTIAL,
            BackoffStrategy.LINEAR,
            BackoffStrategy.LOGARITHMIC,
        ]

        for strategy in strategies:
            for attempt in range(20):
                delay = get_backoff_delay(
                    attempt=attempt,
                    base=0.1,
                    max_seconds=10.0,
                    jitter=0.2,
                    strategy=strategy,
                )
                assert delay > 0, f"Strategy {strategy} produced non-positive delay"
