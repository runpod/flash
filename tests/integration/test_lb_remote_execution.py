"""Integration tests for @remote with LoadBalancerSlsResource.

These tests verify the full flow of using @remote with load-balanced endpoints,
including local development with LiveLoadBalancer and HTTP execution.
"""

import base64
import pytest
from unittest.mock import MagicMock

import cloudpickle

from runpod_flash import remote, LiveLoadBalancer, LoadBalancerSlsResource


class TestRemoteWithLoadBalancerIntegration:
    """Integration tests for @remote decorator with LB endpoints."""

    def test_decorator_accepts_lb_resource_with_routing(self):
        """Test that @remote accepts LoadBalancerSlsResource with method/path."""
        lb = LoadBalancerSlsResource(name="test-api", imageName="test:latest")

        @remote(lb, method="POST", path="/api/process")
        async def process_data(x: int, y: int):
            return {"result": x + y}

        # Should not raise - decorator accepts the parameters
        assert hasattr(process_data, "__remote_config__")
        assert process_data.__remote_config__["method"] == "POST"
        assert process_data.__remote_config__["path"] == "/api/process"

    def test_decorator_validates_method_and_path_required(self):
        """Test that @remote requires both method and path for LB resources."""
        lb = LoadBalancerSlsResource(name="test-api", imageName="test:latest")

        with pytest.raises(ValueError, match="requires both 'method' and 'path'"):

            @remote(lb)
            async def missing_routing():
                pass

    def test_decorator_validates_invalid_http_method(self):
        """Test that @remote rejects invalid HTTP methods."""
        lb = LoadBalancerSlsResource(name="test-api", imageName="test:latest")

        with pytest.raises(ValueError, match="must be one of"):

            @remote(lb, method="INVALID", path="/api/test")
            async def bad_method():
                pass

    def test_decorator_validates_path_starts_with_slash(self):
        """Test that @remote requires path to start with /."""
        lb = LoadBalancerSlsResource(name="test-api", imageName="test:latest")

        with pytest.raises(ValueError, match="must start with '/'"):

            @remote(lb, method="GET", path="api/test")
            async def bad_path():
                pass

    @pytest.mark.asyncio
    async def test_remote_function_serialization_roundtrip(self):
        """Test that function code and args serialize/deserialize correctly."""
        from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub

        mock_resource = MagicMock()
        stub = LoadBalancerSlsStub(mock_resource)

        def add(x: int, y: int) -> int:
            """Simple add function."""
            return x + y

        # Prepare request
        request = await stub._prepare_request(add, None, None, True, 5, 3)

        # Verify request structure
        assert request["function_name"] == "add"
        assert "def add" in request["function_code"]
        assert len(request["args"]) == 2

        # Deserialize and verify arguments
        arg0 = cloudpickle.loads(base64.b64decode(request["args"][0]))
        arg1 = cloudpickle.loads(base64.b64decode(request["args"][1]))
        assert arg0 == 5
        assert arg1 == 3

    @pytest.mark.asyncio
    async def test_stub_response_deserialization(self):
        """Test that response deserialization works correctly."""
        from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub

        mock_resource = MagicMock()
        stub = LoadBalancerSlsStub(mock_resource)

        result_value = {"status": "success", "count": 42}
        result_b64 = base64.b64encode(cloudpickle.dumps(result_value)).decode("utf-8")

        response = {"success": True, "result": result_b64}

        # Handle response
        result = stub._handle_response(response)

        assert result == result_value

    def test_live_load_balancer_creation(self):
        """Test that LiveLoadBalancer can be created and used with @remote."""
        lb = LiveLoadBalancer(name="test-live-api")

        @remote(lb, method="POST", path="/api/echo")
        async def echo(message: str):
            return {"echo": message}

        # Verify resource is correctly configured
        # Note: name may have "-fb" appended by flash boot validator
        assert "test-live-api" in lb.name
        assert "flash-lb" in lb.imageName
        assert echo.__remote_config__["method"] == "POST"

    def test_live_load_balancer_image_locked(self):
        """Test that LiveLoadBalancer locks the image to Flash LB image."""
        lb = LiveLoadBalancer(name="test-api")

        # Verify image is locked and cannot be overridden
        original_image = lb.imageName
        assert "flash-lb" in original_image

        # Try to set a different image (should be ignored due to property)
        lb.imageName = "custom-image:latest"

        # Image should still be locked to Flash
        assert lb.imageName == original_image

    def test_load_balancer_vs_queue_based_endpoints(self):
        """Test that LB and QB endpoints have different characteristics."""
        from runpod_flash import ServerlessEndpoint

        lb = LoadBalancerSlsResource(name="lb-api", imageName="test:latest")
        qb = ServerlessEndpoint(name="qb-api", imageName="test:latest")

        @remote(lb, method="POST", path="/api/echo")
        async def lb_func():
            return "lb"

        @remote(qb)
        async def qb_func():
            return "qb"

        # Both should have __remote_config__
        assert hasattr(lb_func, "__remote_config__")
        assert hasattr(qb_func, "__remote_config__")

        # LB should have routing config
        assert lb_func.__remote_config__["method"] == "POST"
        assert lb_func.__remote_config__["path"] == "/api/echo"

        # QB should have None values for routing (not LB-specific)
        assert qb_func.__remote_config__["method"] is None
        assert qb_func.__remote_config__["path"] is None

    def test_scanner_discovers_load_balancer_resources(self):
        """Test that scanner can discover LiveLoadBalancer and LoadBalancerSlsResource."""
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner
        from pathlib import Path
        import tempfile

        # Create temporary Python file with LoadBalancer resource
        code = """
from runpod_flash import LiveLoadBalancer, LoadBalancerSlsResource, remote

# Test LiveLoadBalancer discovery
api = LiveLoadBalancer(name="test-api")

@remote(api, method="POST", path="/api/process")
async def process_data(x: int):
    return {"result": x}

# Test LoadBalancerSlsResource discovery
deployed = LoadBalancerSlsResource(name="deployed-api", imageName="test:latest")

@remote(deployed, method="GET", path="/api/status")
def get_status():
    return {"status": "ok"}
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            py_file = project_dir / "api_worker.py"
            py_file.write_text(code)

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            # Verify both resources were discovered
            assert len(functions) == 2

            # Verify resource types are correctly identified
            resource_types = {f.resource_type for f in functions}
            assert "LiveLoadBalancer" in resource_types
            assert "LoadBalancerSlsResource" in resource_types

            # Verify resource configs were extracted
            assert "test-api" in scanner.resource_types
            assert scanner.resource_types["test-api"] == "LiveLoadBalancer"
            assert "deployed-api" in scanner.resource_types
            assert scanner.resource_types["deployed-api"] == "LoadBalancerSlsResource"
