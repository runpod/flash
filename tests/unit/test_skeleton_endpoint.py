"""tests that skeleton templates use the Endpoint API."""

from runpod_flash.cli.utils.skeleton import create_project_skeleton


class TestSkeletonUsesEndpoint:
    def test_gpu_worker_uses_endpoint(self, tmp_path):
        create_project_skeleton(tmp_path)
        content = (tmp_path / "gpu_worker.py").read_text()
        assert "from runpod_flash import Endpoint" in content
        assert "@Endpoint(" in content
        assert "@remote" not in content
        assert "LiveServerless" not in content

    def test_cpu_worker_uses_endpoint(self, tmp_path):
        create_project_skeleton(tmp_path)
        content = (tmp_path / "cpu_worker.py").read_text()
        assert "from runpod_flash import Endpoint" in content
        assert "@Endpoint(" in content
        assert "cpu=" in content
        assert "@remote" not in content
        assert "CpuLiveServerless" not in content

    def test_lb_worker_uses_endpoint(self, tmp_path):
        create_project_skeleton(tmp_path)
        content = (tmp_path / "lb_worker.py").read_text()
        assert "from runpod_flash import Endpoint" in content
        assert "Endpoint(" in content
        assert "@api.post(" in content
        assert "@api.get(" in content
        assert "@remote" not in content
        assert "CpuLiveLoadBalancer" not in content

    def test_readme_shows_endpoint_api(self, tmp_path):
        create_project_skeleton(tmp_path)
        content = (tmp_path / "README.md").read_text()
        assert "@Endpoint(" in content
        assert "@api.post(" in content
        assert "@api.get(" in content
