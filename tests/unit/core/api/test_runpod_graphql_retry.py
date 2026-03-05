"""Tests for Runpod GraphQL retry behavior."""

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from runpod_flash.core.api import runpod as runpod_api
from runpod_flash.core.api.runpod import (
    RunpodGraphQLClient,
    _is_transient_graphql_error_message,
)


class TestTransientGraphQLErrorMatching:
    @pytest.mark.parametrize(
        "message",
        [
            "please try again later",
            "INTERNAL SERVER ERROR",
            "service unavailable",
            "too many requests",
            "temporarily unavailable",
        ],
    )
    def test_returns_true_for_known_transient_patterns(self, message):
        assert _is_transient_graphql_error_message(message)

    @pytest.mark.parametrize(
        "message",
        [
            "validation failed: missing field",
            "authentication failed",
            "forbidden",
        ],
    )
    def test_returns_false_for_permanent_patterns(self, message):
        assert not _is_transient_graphql_error_message(message)


class TestExecuteGraphQLRetry:
    @pytest.mark.asyncio
    async def test_retries_on_transient_graphql_errors_then_succeeds(self):
        client = RunpodGraphQLClient(api_key="test-api-key")

        with (
            patch.object(
                client,
                "_execute_graphql_once",
                new=AsyncMock(
                    side_effect=[
                        runpod_api._GraphQLErrorResponse(
                            "GraphQL errors: internal server error",
                            [{"message": "internal server error"}],
                        ),
                        {"saveEndpoint": {"id": "endpoint-id"}},
                    ]
                ),
            ) as execute_once,
            patch(
                "runpod_flash.core.api.runpod.get_backoff_delay", return_value=0.01
            ) as backoff,
            patch(
                "runpod_flash.core.api.runpod.asyncio.sleep", new=AsyncMock()
            ) as sleep,
        ):
            result = await client._execute_graphql("query { ping }")

        assert result == {"saveEndpoint": {"id": "endpoint-id"}}
        assert execute_once.await_count == 2
        backoff.assert_called_once_with(
            0,
            base=runpod_api.GRAPHQL_BACKOFF_BASE_SECONDS,
            max_seconds=runpod_api.GRAPHQL_BACKOFF_MAX_SECONDS,
            strategy=runpod_api.BackoffStrategy.EXPONENTIAL,
        )
        sleep.assert_awaited_once_with(0.01)

    @pytest.mark.asyncio
    async def test_retries_on_http_5xx_then_succeeds(self):
        client = RunpodGraphQLClient(api_key="test-api-key")

        with (
            patch.object(
                client,
                "_execute_graphql_once",
                new=AsyncMock(
                    side_effect=[
                        runpod_api._GraphQLHTTPStatusError(
                            503,
                            "GraphQL request failed: 503 - {'error': 'service unavailable'}",
                        ),
                        {"data": "ok"},
                    ]
                ),
            ) as execute_once,
            patch("runpod_flash.core.api.runpod.get_backoff_delay", return_value=0.01),
            patch(
                "runpod_flash.core.api.runpod.asyncio.sleep", new=AsyncMock()
            ) as sleep,
        ):
            result = await client._execute_graphql("query { ping }")

        assert result == {"data": "ok"}
        assert execute_once.await_count == 2
        sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_immediately_for_http_4xx(self):
        client = RunpodGraphQLClient(api_key="test-api-key")
        error = runpod_api._GraphQLHTTPStatusError(
            401,
            "GraphQL request failed: 401 - {'error': 'unauthorized'}",
        )

        with (
            patch.object(
                client,
                "_execute_graphql_once",
                new=AsyncMock(side_effect=error),
            ) as execute_once,
            patch(
                "runpod_flash.core.api.runpod.asyncio.sleep", new=AsyncMock()
            ) as sleep,
        ):
            with pytest.raises(runpod_api._GraphQLHTTPStatusError, match="401"):
                await client._execute_graphql("query { ping }")

        assert execute_once.await_count == 1
        sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retries_on_network_error_until_exhausted(self):
        client = RunpodGraphQLClient(api_key="test-api-key")

        with (
            patch.object(
                client,
                "_execute_graphql_once",
                new=AsyncMock(side_effect=aiohttp.ClientError("connection reset")),
            ) as execute_once,
            patch("runpod_flash.core.api.runpod.get_backoff_delay", return_value=0.01),
            patch(
                "runpod_flash.core.api.runpod.asyncio.sleep", new=AsyncMock()
            ) as sleep,
        ):
            with pytest.raises(aiohttp.ClientError, match="connection reset"):
                await client._execute_graphql("query { ping }")

        assert execute_once.await_count == runpod_api.GRAPHQL_MAX_RETRIES + 1
        assert sleep.await_count == runpod_api.GRAPHQL_MAX_RETRIES

    @pytest.mark.asyncio
    async def test_raises_immediately_for_non_transient_graphql_error(self):
        client = RunpodGraphQLClient(api_key="test-api-key")

        with (
            patch.object(
                client,
                "_execute_graphql_once",
                new=AsyncMock(
                    side_effect=runpod_api._GraphQLErrorResponse(
                        "GraphQL errors: validation failed",
                        [{"message": "validation failed"}],
                    )
                ),
            ) as execute_once,
            patch(
                "runpod_flash.core.api.runpod.asyncio.sleep", new=AsyncMock()
            ) as sleep,
        ):
            with pytest.raises(
                runpod_api._GraphQLErrorResponse, match="validation failed"
            ):
                await client._execute_graphql("query { ping }")

        assert execute_once.await_count == 1
        sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_retry_for_untyped_exception_with_transient_pattern(self):
        client = RunpodGraphQLClient(api_key="test-api-key")

        with (
            patch.object(
                client,
                "_execute_graphql_once",
                new=AsyncMock(
                    side_effect=Exception(
                        "validation failed with internal server error details"
                    )
                ),
            ) as execute_once,
            patch(
                "runpod_flash.core.api.runpod.asyncio.sleep", new=AsyncMock()
            ) as sleep,
        ):
            with pytest.raises(Exception, match="validation failed"):
                await client._execute_graphql("query { ping }")

        assert execute_once.await_count == 1
        sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_retry_mutation_by_default(self):
        client = RunpodGraphQLClient(api_key="test-api-key")

        with (
            patch.object(
                client,
                "_execute_graphql_once",
                new=AsyncMock(
                    side_effect=runpod_api._GraphQLErrorResponse(
                        "GraphQL errors: try again later",
                        [{"message": "try again later"}],
                    )
                ),
            ) as execute_once,
            patch(
                "runpod_flash.core.api.runpod.asyncio.sleep", new=AsyncMock()
            ) as sleep,
        ):
            with pytest.raises(
                runpod_api._GraphQLErrorResponse, match="try again later"
            ):
                await client._execute_graphql(
                    "mutation { saveEndpoint(input: {}) { id } }"
                )

        assert execute_once.await_count == 1
        sleep.assert_not_awaited()
