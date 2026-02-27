"""Tests for metrics collection module."""

import logging
from unittest.mock import patch


from runpod_flash.runtime.metrics import (
    CircuitBreakerMetrics,
    LoadBalancerMetrics,
    Metric,
    MetricsCollector,
    MetricType,
    RetryMetrics,
    get_metrics_collector,
    set_metrics_collector,
)


class TestMetricType:
    """Test MetricType enum."""

    def test_metric_types(self):
        """Test all metric type values."""
        assert MetricType.COUNTER.value == "counter"
        assert MetricType.GAUGE.value == "gauge"
        assert MetricType.HISTOGRAM.value == "histogram"


class TestMetric:
    """Test Metric dataclass."""

    def test_metric_creation(self):
        """Test creating a Metric instance."""
        metric = Metric(
            metric_type=MetricType.COUNTER,
            metric_name="test_counter",
            value=5.0,
            labels={"endpoint": "test"},
        )

        assert metric.metric_type == MetricType.COUNTER
        assert metric.metric_name == "test_counter"
        assert metric.value == 5.0
        assert metric.labels["endpoint"] == "test"

    def test_metric_to_dict(self):
        """Test converting Metric to dictionary."""
        metric = Metric(
            metric_type=MetricType.GAUGE,
            metric_name="memory_usage",
            value=75.5,
            labels={"unit": "percent"},
        )

        metric_dict = metric.to_dict()

        assert metric_dict["metric_type"] == MetricType.GAUGE
        assert metric_dict["metric_name"] == "memory_usage"
        assert metric_dict["value"] == 75.5
        assert metric_dict["labels"]["unit"] == "percent"

    def test_metric_with_empty_labels(self):
        """Test Metric with empty labels."""
        metric = Metric(
            metric_type=MetricType.HISTOGRAM,
            metric_name="latency",
            value=100.0,
            labels={},
        )

        assert metric.labels == {}

    def test_metric_with_multiple_labels(self):
        """Test Metric with multiple labels."""
        metric = Metric(
            metric_type=MetricType.COUNTER,
            metric_name="requests",
            value=1.0,
            labels={
                "endpoint": "/api/users",
                "method": "GET",
                "status": "200",
                "region": "us-east-1",
            },
        )

        assert len(metric.labels) == 4
        assert metric.labels["method"] == "GET"


class TestMetricsCollector:
    """Test MetricsCollector functionality."""

    def test_collector_initialization(self):
        """Test MetricsCollector initialization."""
        collector = MetricsCollector(namespace="test.metrics", enabled=True)

        assert collector.namespace == "test.metrics"
        assert collector.enabled is True

    def test_collector_disabled(self):
        """Test that disabled collector doesn't emit metrics."""
        collector = MetricsCollector(enabled=False)

        with patch.object(collector, "_emit") as mock_emit:
            collector.counter("test_counter", value=1.0)
            collector.gauge("test_gauge", value=50.0)
            collector.histogram("test_histogram", value=100.0)

            # _emit should never be called
            mock_emit.assert_not_called()

    def test_counter_metric(self):
        """Test emitting counter metric."""
        collector = MetricsCollector()

        with patch.object(collector, "_emit") as mock_emit:
            collector.counter("request_count", value=5.0, labels={"endpoint": "api"})

            mock_emit.assert_called_once()
            metric = mock_emit.call_args[0][0]
            assert metric.metric_type == MetricType.COUNTER
            assert metric.metric_name == "request_count"
            assert metric.value == 5.0

    def test_counter_default_value(self):
        """Test counter with default value of 1.0."""
        collector = MetricsCollector()

        with patch.object(collector, "_emit") as mock_emit:
            collector.counter("page_views")

            metric = mock_emit.call_args[0][0]
            assert metric.value == 1.0

    def test_gauge_metric(self):
        """Test emitting gauge metric."""
        collector = MetricsCollector()

        with patch.object(collector, "_emit") as mock_emit:
            collector.gauge("cpu_usage", value=75.5, labels={"host": "server1"})

            mock_emit.assert_called_once()
            metric = mock_emit.call_args[0][0]
            assert metric.metric_type == MetricType.GAUGE
            assert metric.metric_name == "cpu_usage"
            assert metric.value == 75.5

    def test_histogram_metric(self):
        """Test emitting histogram metric."""
        collector = MetricsCollector()

        with patch.object(collector, "_emit") as mock_emit:
            collector.histogram("request_duration", value=250.0, labels={"path": "/"})

            mock_emit.assert_called_once()
            metric = mock_emit.call_args[0][0]
            assert metric.metric_type == MetricType.HISTOGRAM
            assert metric.metric_name == "request_duration"
            assert metric.value == 250.0

    def test_emit_logs_metric(self, caplog):
        """Test that _emit logs metrics."""
        collector = MetricsCollector(namespace="test.metrics")

        with caplog.at_level(logging.INFO):
            metric = Metric(
                metric_type=MetricType.COUNTER,
                metric_name="test_metric",
                value=1.0,
                labels={},
            )
            collector._emit(metric)

        assert "[METRIC] test_metric=1.0" in caplog.text

    def test_emit_handles_exceptions(self, caplog):
        """Test that _emit handles logging exceptions gracefully."""
        collector = MetricsCollector()

        # Create a metric that will cause an exception during logging
        metric = Metric(
            metric_type=MetricType.COUNTER,
            metric_name="bad_metric",
            value=1.0,
            labels={},
        )

        # Patch logger.info to raise exception
        with patch(
            "runpod_flash.runtime.metrics.logger.info",
            side_effect=Exception("Log error"),
        ):
            with caplog.at_level(logging.ERROR):
                collector._emit(metric)

            assert "Failed to emit metric" in caplog.text

    def test_collector_with_no_labels(self):
        """Test metrics without labels."""
        collector = MetricsCollector()

        with patch.object(collector, "_emit") as mock_emit:
            collector.counter("simple_counter")

            metric = mock_emit.call_args[0][0]
            assert metric.labels == {}


class TestGlobalMetricsCollector:
    """Test global metrics collector functions."""

    def test_get_metrics_collector_lazy_load(self):
        """Test lazy loading of global metrics collector."""
        # Reset global collector
        import runpod_flash.runtime.metrics as metrics_module

        metrics_module._collector = None

        collector1 = get_metrics_collector()
        collector2 = get_metrics_collector()

        # Should return same instance
        assert collector1 is collector2

    def test_get_metrics_collector_with_params(self):
        """Test get_metrics_collector with custom parameters."""
        import runpod_flash.runtime.metrics as metrics_module

        metrics_module._collector = None

        collector = get_metrics_collector(namespace="custom.metrics", enabled=False)

        # Note: After first call, namespace is set and won't change
        assert collector.namespace == "custom.metrics"
        assert collector.enabled is False

    def test_set_metrics_collector(self):
        """Test setting custom metrics collector."""
        custom_collector = MetricsCollector(namespace="custom")

        set_metrics_collector(custom_collector)

        retrieved = get_metrics_collector()
        assert retrieved is custom_collector


class TestCircuitBreakerMetrics:
    """Test CircuitBreakerMetrics helper."""

    def test_initialization(self):
        """Test CircuitBreakerMetrics initialization."""
        collector = MetricsCollector()
        cb_metrics = CircuitBreakerMetrics(collector=collector)

        assert cb_metrics.collector is collector

    def test_initialization_uses_global_collector(self):
        """Test that CircuitBreakerMetrics uses global collector by default."""
        cb_metrics = CircuitBreakerMetrics()

        assert cb_metrics.collector is not None

    def test_state_changed_metric(self):
        """Test emitting state change metric."""
        collector = MetricsCollector()
        cb_metrics = CircuitBreakerMetrics(collector=collector)

        with patch.object(collector, "counter") as mock_counter:
            cb_metrics.state_changed(
                endpoint_url="https://test.com",
                new_state="OPEN",
                previous_state="CLOSED",
            )

            mock_counter.assert_called_once()
            assert mock_counter.call_args[0][0] == "circuit_breaker_state_changes"
            labels = mock_counter.call_args[1]["labels"]
            assert labels["new_state"] == "OPEN"
            assert labels["previous_state"] == "CLOSED"

    def test_endpoint_requests_metric(self):
        """Test emitting endpoint requests metric."""
        collector = MetricsCollector()
        cb_metrics = CircuitBreakerMetrics(collector=collector)

        with patch.object(collector, "counter") as mock_counter:
            cb_metrics.endpoint_requests(
                endpoint_url="https://test.com",
                status="success",
                count=5,
            )

            mock_counter.assert_called_once()
            assert mock_counter.call_args[1]["value"] == 5.0

    def test_endpoint_latency_metric(self):
        """Test emitting endpoint latency metric."""
        collector = MetricsCollector()
        cb_metrics = CircuitBreakerMetrics(collector=collector)

        with patch.object(collector, "histogram") as mock_histogram:
            cb_metrics.endpoint_latency(
                endpoint_url="https://test.com",
                latency_ms=150.5,
            )

            mock_histogram.assert_called_once()
            assert mock_histogram.call_args[1]["value"] == 150.5

    def test_in_flight_requests_metric(self):
        """Test emitting in-flight requests metric."""
        collector = MetricsCollector()
        cb_metrics = CircuitBreakerMetrics(collector=collector)

        with patch.object(collector, "gauge") as mock_gauge:
            cb_metrics.in_flight_requests(
                endpoint_url="https://test.com",
                count=3,
            )

            mock_gauge.assert_called_once()
            assert mock_gauge.call_args[1]["value"] == 3.0


class TestRetryMetrics:
    """Test RetryMetrics helper."""

    def test_initialization(self):
        """Test RetryMetrics initialization."""
        collector = MetricsCollector()
        retry_metrics = RetryMetrics(collector=collector)

        assert retry_metrics.collector is collector

    def test_retry_attempt_metric(self):
        """Test emitting retry attempt metric."""
        collector = MetricsCollector()
        retry_metrics = RetryMetrics(collector=collector)

        with patch.object(collector, "counter") as mock_counter:
            retry_metrics.retry_attempt(
                function_name="test_function",
                attempt=2,
                error="Connection timeout",
            )

            mock_counter.assert_called_once()
            labels = mock_counter.call_args[1]["labels"]
            assert labels["function_name"] == "test_function"
            assert labels["attempt"] == "2"
            assert labels["error"] == "Connection timeout"

    def test_retry_attempt_without_error(self):
        """Test retry attempt metric without error message."""
        collector = MetricsCollector()
        retry_metrics = RetryMetrics(collector=collector)

        with patch.object(collector, "counter") as mock_counter:
            retry_metrics.retry_attempt(
                function_name="test_function",
                attempt=1,
            )

            labels = mock_counter.call_args[1]["labels"]
            assert "error" not in labels

    def test_retry_success_metric(self):
        """Test emitting retry success metric."""
        collector = MetricsCollector()
        retry_metrics = RetryMetrics(collector=collector)

        with patch.object(collector, "counter") as mock_counter:
            retry_metrics.retry_success(
                function_name="test_function",
                total_attempts=3,
            )

            mock_counter.assert_called_once()
            assert mock_counter.call_args[0][0] == "retry_success"
            labels = mock_counter.call_args[1]["labels"]
            assert labels["attempts"] == "3"

    def test_retry_exhausted_metric(self):
        """Test emitting retry exhausted metric."""
        collector = MetricsCollector()
        retry_metrics = RetryMetrics(collector=collector)

        with patch.object(collector, "counter") as mock_counter:
            retry_metrics.retry_exhausted(
                function_name="test_function",
                max_attempts=5,
            )

            mock_counter.assert_called_once()
            assert mock_counter.call_args[0][0] == "retry_exhausted"
            labels = mock_counter.call_args[1]["labels"]
            assert labels["max_attempts"] == "5"


class TestLoadBalancerMetrics:
    """Test LoadBalancerMetrics helper."""

    def test_initialization(self):
        """Test LoadBalancerMetrics initialization."""
        collector = MetricsCollector()
        lb_metrics = LoadBalancerMetrics(collector=collector)

        assert lb_metrics.collector is collector

    def test_endpoint_selected_metric(self):
        """Test emitting endpoint selected metric."""
        collector = MetricsCollector()
        lb_metrics = LoadBalancerMetrics(collector=collector)

        with patch.object(collector, "counter") as mock_counter:
            lb_metrics.endpoint_selected(
                strategy="round_robin",
                endpoint_url="https://endpoint1.com",
                total_candidates=3,
            )

            mock_counter.assert_called_once()
            assert mock_counter.call_args[0][0] == "load_balancer_selection"
            labels = mock_counter.call_args[1]["labels"]
            assert labels["strategy"] == "round_robin"
            assert labels["endpoint_url"] == "https://endpoint1.com"
            assert labels["candidates"] == "3"

    def test_endpoint_selected_with_different_strategies(self):
        """Test endpoint selection with various strategies."""
        collector = MetricsCollector()
        lb_metrics = LoadBalancerMetrics(collector=collector)

        strategies = ["round_robin", "random", "least_connections"]

        with patch.object(collector, "counter") as mock_counter:
            for strategy in strategies:
                lb_metrics.endpoint_selected(
                    strategy=strategy,
                    endpoint_url=f"https://{strategy}.com",
                    total_candidates=5,
                )

            assert mock_counter.call_count == 3


class TestMetricsIntegration:
    """Test integration scenarios with metrics."""

    def test_multiple_metric_types_together(self):
        """Test emitting different metric types."""
        collector = MetricsCollector()

        with patch.object(collector, "_emit") as mock_emit:
            collector.counter("requests", value=100.0)
            collector.gauge("memory_usage", value=75.0)
            collector.histogram("latency", value=50.0)

            assert mock_emit.call_count == 3

    def test_metrics_with_complex_labels(self):
        """Test metrics with complex label structures."""
        collector = MetricsCollector()

        labels = {
            "endpoint": "https://api.example.com/users",
            "method": "POST",
            "status_code": "201",
            "user_agent": "Mozilla/5.0",
            "region": "us-west-2",
            "version": "v1.2.3",
        }

        with patch.object(collector, "_emit") as mock_emit:
            collector.counter("api_requests", value=1.0, labels=labels)

            metric = mock_emit.call_args[0][0]
            assert len(metric.labels) == 6

    def test_metrics_lifecycle(self):
        """Test complete metrics lifecycle."""
        # Initialize
        collector = MetricsCollector(namespace="app.metrics")

        # Emit various metrics
        cb_metrics = CircuitBreakerMetrics(collector=collector)
        retry_metrics = RetryMetrics(collector=collector)
        lb_metrics = LoadBalancerMetrics(collector=collector)

        with patch.object(collector, "_emit") as mock_emit:
            # Circuit breaker metrics
            cb_metrics.state_changed("https://test.com", "OPEN", "CLOSED")

            # Retry metrics
            retry_metrics.retry_attempt("test_func", 1)

            # Load balancer metrics
            lb_metrics.endpoint_selected("random", "https://test.com", 3)

            # Should have emitted 3 metrics
            assert mock_emit.call_count == 3
