"""Tests for dynamic context rendering."""

from runpod_flash.rules.context import render_dynamic_context


SAMPLE_MANIFEST = {
    "version": "1.0",
    "generated_at": "2026-03-16T14:00:00Z",
    "project_name": "test_project",
    "resources": {
        "image_gen": {
            "resource_type": "LiveServerless",
            "file_path": "gpu_worker.py",
            "functions": [
                {
                    "name": "generate",
                    "module": "gpu_worker",
                    "is_async": True,
                    "is_class": False,
                }
            ],
            "is_load_balanced": False,
            "makes_remote_calls": False,
            "gpuIds": "ADA_24",
            "workersMin": 0,
            "workersMax": 3,
        },
        "api": {
            "resource_type": "CpuLiveLoadBalancer",
            "file_path": "pipeline.py",
            "functions": [
                {
                    "name": "classify",
                    "module": "pipeline",
                    "is_async": True,
                    "is_class": False,
                    "http_method": "POST",
                    "http_path": "/classify",
                }
            ],
            "is_load_balanced": True,
            "makes_remote_calls": True,
        },
    },
    "function_registry": {"generate": "image_gen", "classify": "api"},
    "routes": {"api": {"POST /classify": "classify"}},
}


class TestRenderDynamicContext:
    def test_renders_endpoints_table(self):
        result = render_dynamic_context(SAMPLE_MANIFEST)
        assert "image_gen" in result
        assert "api" in result
        assert "gpu_worker.py" in result

    def test_renders_dependency_graph(self):
        result = render_dynamic_context(SAMPLE_MANIFEST)
        assert "Dependency Graph" in result

    def test_renders_per_endpoint_details(self):
        result = render_dynamic_context(SAMPLE_MANIFEST)
        assert "ADA_24" in result
        assert "LiveServerless" in result

    def test_includes_timestamp(self):
        result = render_dynamic_context(SAMPLE_MANIFEST)
        assert "Auto-generated" in result

    def test_empty_manifest_returns_minimal_output(self):
        empty = {"version": "1.0", "resources": {}, "function_registry": {}}
        result = render_dynamic_context(empty)
        assert "No endpoints discovered" in result

    def test_respects_token_budget(self):
        large_manifest = {"version": "1.0", "resources": {}, "function_registry": {}}
        for i in range(50):
            large_manifest["resources"][f"endpoint_{i}"] = {
                "resource_type": "LiveServerless",
                "file_path": f"worker_{i}.py",
                "functions": [
                    {
                        "name": f"func_{i}",
                        "module": f"worker_{i}",
                        "is_async": True,
                        "is_class": False,
                    }
                ],
                "is_load_balanced": False,
                "makes_remote_calls": False,
                "gpuIds": "ADA_24",
                "workersMin": 0,
                "workersMax": 3,
            }
        large_manifest["function_registry"] = {
            f"func_{i}": f"endpoint_{i}" for i in range(50)
        }
        result = render_dynamic_context(large_manifest)
        word_count = len(result.split())
        assert word_count < 3000, f"Dynamic context too large: {word_count} words"
