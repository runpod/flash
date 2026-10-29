"""tests for flash_sentinel module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_client(mock_response):
    """helper to create a properly structured async httpx client mock."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.fixture
def mock_httpx():
    """patch get_authenticated_httpx_client at its source module.

    patches at the source rather than the importing module so sys.modules
    eviction (e.g. by test_dotenv_loading) does not break the mock.
    """
    with patch(
        "runpod_flash.core.utils.http.get_authenticated_httpx_client"
    ) as mock_factory:
        yield mock_factory


class TestFlashHeaders:
    def test_builds_correct_headers(self):
        from runpod_flash.flash_sentinel import _flash_headers

        headers = _flash_headers("myapp", "prod", "gpu-worker")
        assert headers == {
            "X-Flash-App": "myapp",
            "X-Flash-Environment": "prod",
            "X-Flash-Endpoint": "gpu-worker",
        }


class TestHandleSentinelResponse:
    def test_plain_output(self):
        from runpod_flash.flash_sentinel import _handle_sentinel_response

        data = {"output": {"hello": "world"}}
        assert _handle_sentinel_response(data) == {"hello": "world"}

    def test_no_output_or_status_raises(self):
        from runpod_flash.flash_sentinel import _handle_sentinel_response

        data = {"hello": "world"}
        with pytest.raises(RuntimeError, match="unexpected response from sentinel"):
            _handle_sentinel_response(data)

    def test_status_without_output_returns_data(self):
        from runpod_flash.flash_sentinel import _handle_sentinel_response

        data = {"status": "COMPLETED"}
        assert _handle_sentinel_response(data) == {"status": "COMPLETED"}

    def test_failed_status_raises(self):
        from runpod_flash.flash_sentinel import _handle_sentinel_response

        data = {"status": "FAILED", "error": "worker crashed"}
        with pytest.raises(RuntimeError, match="worker crashed"):
            _handle_sentinel_response(data)

    def test_output_error_raises(self):
        """deployed handlers return {'error': ...} in output on exception."""
        from runpod_flash.flash_sentinel import _handle_sentinel_response

        data = {"status": "COMPLETED", "output": {"error": "ImportError"}}
        with pytest.raises(RuntimeError, match="ImportError"):
            _handle_sentinel_response(data)


class TestSentinelQBExecute:
    @pytest.mark.asyncio
    async def test_maps_positional_args_to_kwargs(self, mock_httpx):
        from runpod_flash.flash_sentinel import FLASH_SENTINEL_ID, sentinel_qb_execute

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "COMPLETED",
            "output": {"result": 42},
        }

        mock_client = _make_mock_client(mock_response)
        mock_httpx.return_value = mock_client

        async def my_func(x, y=7):
            return x + y

        result = await sentinel_qb_execute(
            "myapp",
            "prod",
            "gpu-worker",
            my_func,
            10,
            y=32,
        )

        assert result == {"result": 42}

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["X-Flash-App"] == "myapp"
        assert headers["X-Flash-Environment"] == "prod"
        assert headers["X-Flash-Endpoint"] == "gpu-worker"

        url = call_kwargs.args[0]
        assert f"/{FLASH_SENTINEL_ID}/runsync" in url

        sent_payload = call_kwargs.kwargs["json"]
        assert sent_payload == {"input": {"x": 10, "y": 32}}

    @pytest.mark.asyncio
    async def test_raises_on_failed_status(self, mock_httpx):
        from runpod_flash.flash_sentinel import sentinel_qb_execute

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "FAILED",
            "error": "worker crashed",
        }
        mock_httpx.return_value = _make_mock_client(mock_response)

        async def my_func():
            pass

        with pytest.raises(RuntimeError, match="worker crashed"):
            await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

    @pytest.mark.asyncio
    async def test_raises_on_output_error(self, mock_httpx):
        from runpod_flash.flash_sentinel import sentinel_qb_execute

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "COMPLETED",
            "output": {"error": "ImportError: no module named torch"},
        }
        mock_httpx.return_value = _make_mock_client(mock_response)

        async def my_func():
            pass

        with pytest.raises(RuntimeError, match="ImportError"):
            await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)


class TestHandleSentinelTerminalStatuses:
    @pytest.mark.parametrize("status", ["CANCELLED", "TIMED_OUT"])
    def test_cancelled_or_timed_out_raises(self, status):
        from runpod_flash.flash_sentinel import _handle_sentinel_response

        data = {"id": "job-1", "status": status}
        with pytest.raises(RuntimeError, match=status.lower()):
            _handle_sentinel_response(data)


def _json_response(payload):
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    return response


def _http_error_response(status_code):
    import httpx

    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            str(status_code), request=MagicMock(), response=MagicMock()
        )
    )
    return response


class TestSentinelQBPolling:
    """runsync returns IN_QUEUE/IN_PROGRESS when the job outlives the server wait."""

    @pytest.fixture(autouse=True)
    def no_sleep(self):
        with patch("runpod_flash.flash_sentinel.asyncio.sleep", new=AsyncMock()):
            yield

    @pytest.mark.asyncio
    async def test_polls_status_until_completed(self, mock_httpx):
        from runpod_flash.flash_sentinel import FLASH_SENTINEL_ID, sentinel_qb_execute

        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_QUEUE"})
        )
        mock_client.get = AsyncMock(
            side_effect=[
                _json_response({"id": "job-1", "status": "IN_QUEUE"}),
                _json_response({"id": "job-1", "status": "IN_PROGRESS"}),
                _json_response(
                    {"id": "job-1", "status": "COMPLETED", "output": {"image": "b64"}}
                ),
            ]
        )
        mock_httpx.return_value = mock_client

        async def my_func(prompt):
            pass

        result = await sentinel_qb_execute(
            "myapp", "prod", "gpu-worker", my_func, "a cat"
        )

        assert result == {"image": "b64"}
        assert mock_client.get.call_count == 3
        status_call = mock_client.get.call_args
        assert status_call.args[0].endswith(f"/{FLASH_SENTINEL_ID}/status/job-1")
        assert status_call.kwargs["headers"]["X-Flash-Endpoint"] == "gpu-worker"

    @pytest.mark.asyncio
    async def test_polled_failure_raises(self, mock_httpx):
        from runpod_flash.flash_sentinel import sentinel_qb_execute

        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_PROGRESS"})
        )
        mock_client.get = AsyncMock(
            return_value=_json_response(
                {"id": "job-1", "status": "FAILED", "error": "CUDA out of memory"}
            )
        )
        mock_httpx.return_value = mock_client

        async def my_func():
            pass

        with pytest.raises(RuntimeError, match="CUDA out of memory"):
            await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

    @pytest.mark.asyncio
    async def test_polled_timeout_raises(self, mock_httpx):
        from runpod_flash.flash_sentinel import sentinel_qb_execute

        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_QUEUE"})
        )
        mock_client.get = AsyncMock(
            return_value=_json_response({"id": "job-1", "status": "TIMED_OUT"})
        )
        mock_httpx.return_value = mock_client

        async def my_func():
            pass

        with pytest.raises(RuntimeError, match="timed_out"):
            await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

    @pytest.mark.asyncio
    async def test_class_execute_polls_too(self, mock_httpx):
        from runpod_flash.flash_sentinel import sentinel_qb_class_execute
        from runpod_flash.protos.remote_execution import FunctionRequest

        mock_client = _make_mock_client(
            _json_response({"id": "job-2", "status": "IN_PROGRESS"})
        )
        mock_client.get = AsyncMock(
            return_value=_json_response(
                {"id": "job-2", "status": "COMPLETED", "output": {"ok": True}}
            )
        )
        mock_httpx.return_value = mock_client

        request = FunctionRequest(
            execution_type="class", class_name="MyModel", method_name="predict"
        )
        result = await sentinel_qb_class_execute("myapp", "prod", "gpu-worker", request)

        assert result == {"ok": True}
        mock_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pending_without_id_raises(self, mock_httpx):
        from runpod_flash.flash_sentinel import _sentinel_qb_post

        mock_client = _make_mock_client(_json_response({"status": "IN_QUEUE"}))
        mock_client.get = AsyncMock()
        mock_httpx.return_value = mock_client

        with pytest.raises(RuntimeError, match="without a job id"):
            await _sentinel_qb_post("myapp", "prod", "gpu-worker", {"input": {}})
        mock_client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transient_poll_error_is_retried(self, mock_httpx):
        import httpx

        from runpod_flash.flash_sentinel import sentinel_qb_execute

        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_PROGRESS"})
        )
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.ReadTimeout("slow"),
                _json_response(
                    {"id": "job-1", "status": "COMPLETED", "output": {"ok": True}}
                ),
            ]
        )
        mock_httpx.return_value = mock_client

        async def my_func():
            pass

        result = await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

        assert result == {"ok": True}
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_repeated_poll_errors_raise(self, mock_httpx):
        import httpx

        from runpod_flash.flash_sentinel import (
            _STATUS_POLL_MAX_TRANSPORT_ERRORS,
            sentinel_qb_execute,
        )

        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_PROGRESS"})
        )
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
        mock_httpx.return_value = mock_client

        async def my_func():
            pass

        with pytest.raises(RuntimeError, match="lost contact.*job-1"):
            await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)
        assert mock_client.get.call_count == _STATUS_POLL_MAX_TRANSPORT_ERRORS

    @pytest.mark.asyncio
    async def test_poll_client_error_propagates(self, mock_httpx):
        import httpx

        from runpod_flash.flash_sentinel import sentinel_qb_execute

        error_response = _http_error_response(404)
        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_PROGRESS"})
        )
        mock_client.get = AsyncMock(return_value=error_response)
        mock_httpx.return_value = mock_client

        async def my_func():
            pass

        with pytest.raises(RuntimeError, match="job job-1.*gpu-worker") as exc_info:
            await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)
        assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)
        mock_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_poll_non_json_response_raises(self, mock_httpx):
        import json

        from runpod_flash.flash_sentinel import sentinel_qb_execute

        html_response = _json_response(None)
        html_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        html_response.text = "<html>bad gateway</html>"
        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_PROGRESS"})
        )
        mock_client.get = AsyncMock(return_value=html_response)
        mock_httpx.return_value = mock_client

        async def my_func():
            pass

        with pytest.raises(RuntimeError, match="job job-1.*gpu-worker.*non-JSON"):
            await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

    def test_poll_attempt_cap_reaches_max_delay(self):
        from runpod_flash.flash_sentinel import (
            _STATUS_POLL_BASE_SECONDS,
            _STATUS_POLL_MAX_ATTEMPT,
            _STATUS_POLL_MAX_SECONDS,
        )

        capped = _STATUS_POLL_BASE_SECONDS * 2**_STATUS_POLL_MAX_ATTEMPT
        below = _STATUS_POLL_BASE_SECONDS * 2 ** (_STATUS_POLL_MAX_ATTEMPT - 1)
        assert capped >= _STATUS_POLL_MAX_SECONDS > below

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [429, 503])
    async def test_poll_recovers_from_transient_status(self, mock_httpx, status_code):
        from runpod_flash.flash_sentinel import sentinel_qb_execute

        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_PROGRESS"})
        )
        mock_client.get = AsyncMock(
            side_effect=[
                _http_error_response(status_code),
                _json_response(
                    {"id": "job-1", "status": "COMPLETED", "output": {"ok": True}}
                ),
            ]
        )
        mock_httpx.return_value = mock_client

        async def my_func():
            pass

        result = await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

        assert result == {"ok": True}
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_job_stuck_in_queue_is_cancelled(self, mock_httpx):
        from runpod_flash.flash_sentinel import (
            _QUEUE_WAIT_MAX_SECONDS,
            FLASH_SENTINEL_ID,
            sentinel_qb_execute,
        )

        queued = _json_response({"id": "job-1", "status": "IN_QUEUE"})
        mock_client = _make_mock_client(queued)
        mock_client.get = AsyncMock(return_value=queued)
        mock_httpx.return_value = mock_client

        clock = iter([0.0, 10.0, _QUEUE_WAIT_MAX_SECONDS + 1])

        async def my_func():
            pass

        with patch(
            "runpod_flash.flash_sentinel.time.monotonic",
            side_effect=lambda: next(clock),
        ):
            with pytest.raises(RuntimeError, match="still queued.*cancelled"):
                await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

        cancel_url = mock_client.post.call_args.args[0]
        assert cancel_url.endswith(f"/{FLASH_SENTINEL_ID}/cancel/job-1")

    @pytest.mark.asyncio
    async def test_failed_cancel_is_reported(self, mock_httpx):
        from runpod_flash.flash_sentinel import (
            _QUEUE_WAIT_MAX_SECONDS,
            sentinel_qb_execute,
        )

        queued = _json_response({"id": "job-1", "status": "IN_QUEUE"})
        mock_client = _make_mock_client(queued)
        mock_client.post = AsyncMock(side_effect=[queued, _http_error_response(500)])
        mock_client.get = AsyncMock(return_value=queued)
        mock_httpx.return_value = mock_client

        clock = iter([0.0, _QUEUE_WAIT_MAX_SECONDS + 1])

        async def my_func():
            pass

        with patch(
            "runpod_flash.flash_sentinel.time.monotonic",
            side_effect=lambda: next(clock),
        ):
            with pytest.raises(RuntimeError, match="cancelling it failed"):
                await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

    @pytest.mark.asyncio
    async def test_queue_deadline_counts_time_spent_in_runsync(self, mock_httpx):
        from runpod_flash.flash_sentinel import (
            _QUEUE_WAIT_MAX_SECONDS,
            sentinel_qb_execute,
        )

        queued = _json_response({"id": "job-1", "status": "IN_QUEUE"})
        mock_client = _make_mock_client(queued)
        mock_client.get = AsyncMock(return_value=queued)
        mock_httpx.return_value = mock_client

        # submitted at 0, runsync returns pending, first poll is already late
        clock = iter([0.0, _QUEUE_WAIT_MAX_SECONDS + 1])

        async def my_func():
            pass

        with patch(
            "runpod_flash.flash_sentinel.time.monotonic",
            side_effect=lambda: next(clock),
        ):
            with pytest.raises(RuntimeError, match="still queued"):
                await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)
        mock_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_long_running_job_polls_past_backoff_overflow(self, mock_httpx):
        """an uncapped exponent overflows float after ~1024 polls."""
        from runpod_flash.flash_sentinel import sentinel_qb_execute

        running = _json_response({"id": "job-1", "status": "IN_PROGRESS"})
        done = _json_response(
            {"id": "job-1", "status": "COMPLETED", "output": {"ok": True}}
        )
        mock_client = _make_mock_client(running)
        mock_client.get = AsyncMock(side_effect=[running] * 1100 + [done])
        mock_httpx.return_value = mock_client

        async def my_func():
            pass

        result = await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

        assert result == {"ok": True}
        assert mock_client.get.call_count == 1101

    @pytest.mark.asyncio
    async def test_running_job_is_not_cancelled_by_queue_deadline(self, mock_httpx):
        from runpod_flash.flash_sentinel import (
            _QUEUE_WAIT_MAX_SECONDS,
            sentinel_qb_execute,
        )

        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_QUEUE"})
        )
        mock_client.get = AsyncMock(
            side_effect=[
                _json_response({"id": "job-1", "status": "IN_PROGRESS"}),
                _json_response({"id": "job-1", "status": "IN_PROGRESS"}),
                _json_response(
                    {"id": "job-1", "status": "COMPLETED", "output": {"ok": 1}}
                ),
            ]
        )
        mock_httpx.return_value = mock_client

        far = _QUEUE_WAIT_MAX_SECONDS * 10
        clock = iter([0.0, far, far * 2, far * 3])

        async def my_func():
            pass

        with patch(
            "runpod_flash.flash_sentinel.time.monotonic",
            side_effect=lambda: next(clock),
        ):
            result = await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)

        assert result == {"ok": 1}
        assert mock_client.post.await_count == 1  # the runsync call, no cancel


class TestRunsyncWait:
    """runsync must return a pending status before the client times out."""

    @pytest.mark.parametrize(
        ("timeout", "expected_ms"),
        [(90, 80_000), (30, 20_000), (5, 1_000), (900, 300_000)],
    )
    def test_wait_stays_below_client_timeout(self, timeout, expected_ms):
        from runpod_flash.flash_sentinel import _runsync_wait_ms

        assert _runsync_wait_ms(timeout) == expected_ms

    @pytest.mark.asyncio
    async def test_runsync_sends_wait_param(self, mock_httpx, monkeypatch):
        from runpod_flash.flash_sentinel import _sentinel_qb_post

        monkeypatch.delenv("FLASH_SENTINEL_TIMEOUT", raising=False)
        mock_client = _make_mock_client(
            _json_response({"status": "COMPLETED", "output": {}})
        )
        mock_httpx.return_value = mock_client

        await _sentinel_qb_post("myapp", "prod", "gpu-worker", {"input": {"a": 1}})

        assert mock_client.post.call_args.kwargs["params"] == {"wait": 80_000}
        assert mock_httpx.call_args.kwargs["timeout"] == 90


class TestShortTimeoutUsesRun:
    @pytest.fixture(autouse=True)
    def no_sleep(self):
        with patch("runpod_flash.flash_sentinel.asyncio.sleep", new=AsyncMock()):
            yield

    @pytest.mark.asyncio
    @pytest.mark.parametrize("timeout", [1, 11])
    async def test_short_timeout_submits_with_run(self, mock_httpx, timeout):
        from runpod_flash.flash_sentinel import FLASH_SENTINEL_ID, _sentinel_qb_post

        mock_client = _make_mock_client(
            _json_response({"id": "job-1", "status": "IN_QUEUE"})
        )
        mock_client.get = AsyncMock(
            return_value=_json_response(
                {"id": "job-1", "status": "COMPLETED", "output": {"ok": True}}
            )
        )
        mock_httpx.return_value = mock_client

        data = await _sentinel_qb_post(
            "myapp", "prod", "gpu-worker", {"input": {"a": 1}}, timeout=timeout
        )

        assert data["output"] == {"ok": True}
        call = mock_client.post.call_args
        assert call.args[0].endswith(f"/{FLASH_SENTINEL_ID}/run")
        assert call.kwargs["params"] == {}

    @pytest.mark.asyncio
    async def test_timeout_above_margin_uses_runsync(self, mock_httpx):
        from runpod_flash.flash_sentinel import FLASH_SENTINEL_ID, _sentinel_qb_post

        mock_client = _make_mock_client(
            _json_response({"status": "COMPLETED", "output": {}})
        )
        mock_httpx.return_value = mock_client

        await _sentinel_qb_post(
            "myapp", "prod", "gpu-worker", {"input": {"a": 1}}, timeout=12
        )

        call = mock_client.post.call_args
        assert call.args[0].endswith(f"/{FLASH_SENTINEL_ID}/runsync")
        assert call.kwargs["params"] == {"wait": 2_000}


class TestSentinelQBClassExecute:
    @pytest.mark.asyncio
    async def test_dispatches_on_method_name(self, mock_httpx):
        import base64

        import cloudpickle

        from runpod_flash.flash_sentinel import sentinel_qb_class_execute
        from runpod_flash.protos.remote_execution import FunctionRequest

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "COMPLETED",
            "output": {"prediction": [1, 2, 3]},
        }
        mock_httpx.return_value = _make_mock_client(mock_response)

        encoded_x = base64.b64encode(cloudpickle.dumps(5)).decode()

        request = FunctionRequest(
            execution_type="class",
            class_name="MyModel",
            method_name="predict",
            kwargs={"x": encoded_x},
        )

        result = await sentinel_qb_class_execute(
            "myapp",
            "prod",
            "gpu-worker",
            request,
        )

        assert result == {"prediction": [1, 2, 3]}

        call_kwargs = mock_httpx.return_value.post.call_args
        sent_payload = call_kwargs.kwargs["json"]
        assert sent_payload == {"input": {"method": "predict", "x": 5}}

    @pytest.mark.asyncio
    async def test_raises_on_404(self, mock_httpx):
        from runpod_flash.flash_sentinel import sentinel_qb_execute

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx.return_value = _make_mock_client(mock_response)

        async def my_func():
            pass

        with pytest.raises(RuntimeError, match="not found.*deploy"):
            await sentinel_qb_execute("myapp", "prod", "gpu-worker", my_func)


class TestSentinelQBClassExecuteWithMethodRef:
    """test that positional args get mapped to named params via method_ref."""

    @pytest.mark.asyncio
    async def test_maps_positional_args_via_method_ref(self, mock_httpx):
        import base64

        import cloudpickle

        from runpod_flash.flash_sentinel import sentinel_qb_class_execute
        from runpod_flash.protos.remote_execution import FunctionRequest

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "COMPLETED",
            "output": 6,
        }
        mock_httpx.return_value = _make_mock_client(mock_response)

        class Counter:
            async def add(self, x: int) -> int:
                return x + 1

        encoded_x = base64.b64encode(cloudpickle.dumps(5)).decode()

        request = FunctionRequest(
            execution_type="class",
            class_name="Counter",
            method_name="add",
            args=[encoded_x],
        )

        result = await sentinel_qb_class_execute(
            "myapp",
            "prod",
            "gpu-worker",
            request,
            method_ref=Counter.add,
        )

        assert result == 6

        call_kwargs = mock_httpx.return_value.post.call_args
        sent_payload = call_kwargs.kwargs["json"]
        assert sent_payload == {"input": {"method": "add", "x": 5}}

    @pytest.mark.asyncio
    async def test_no_args_sends_empty_marker(self, mock_httpx):
        from runpod_flash.flash_sentinel import sentinel_qb_class_execute
        from runpod_flash.protos.remote_execution import FunctionRequest

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "COMPLETED",
            "output": 0,
        }
        mock_httpx.return_value = _make_mock_client(mock_response)

        request = FunctionRequest(
            execution_type="class",
            class_name="Counter",
            method_name="reset",
        )

        result = await sentinel_qb_class_execute("myapp", "prod", "gpu-worker", request)

        assert result == 0

        call_kwargs = mock_httpx.return_value.post.call_args
        sent_payload = call_kwargs.kwargs["json"]
        assert sent_payload == {"input": {"method": "reset", "__empty": True}}


class TestSentinelLBRequest:
    @pytest.mark.asyncio
    async def test_sends_correct_request(self, mock_httpx):
        from runpod_flash.flash_sentinel import FLASH_SENTINEL_ID, sentinel_lb_request

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_httpx.return_value = _make_mock_client(mock_response)

        result = await sentinel_lb_request(
            "myapp",
            "prod",
            "my-api",
            "POST",
            "/api/compute",
            body={"x": 1},
        )

        assert result == {"result": "ok"}

        call_kwargs = mock_httpx.return_value.request.call_args
        assert call_kwargs.args[0] == "POST"
        url = call_kwargs.args[1]
        assert url.startswith(f"https://{FLASH_SENTINEL_ID}.")
        assert url.endswith("/api/compute")

        headers = call_kwargs.kwargs["headers"]
        assert headers["X-Flash-App"] == "myapp"
        assert headers["X-Flash-Environment"] == "prod"
        assert headers["X-Flash-Endpoint"] == "my-api"

    @pytest.mark.asyncio
    async def test_raises_on_404(self, mock_httpx):
        from runpod_flash.flash_sentinel import sentinel_lb_request

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx.return_value = _make_mock_client(mock_response)

        with pytest.raises(RuntimeError, match="not found.*deploy"):
            await sentinel_lb_request("myapp", "prod", "my-api", "POST", "/api/compute")
