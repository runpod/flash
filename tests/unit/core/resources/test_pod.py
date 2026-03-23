"""Tests for Pod core models."""

from __future__ import annotations


import pytest

from runpod_flash.core.resources.pod import (
    API_STATUS_MAP,
    VALID_TRANSITIONS,
    Pod,
    PodConfig,
    PodState,
)


class TestPodState:
    def test_enum_values(self) -> None:
        assert PodState.DEFINED == "defined"
        assert PodState.PROVISIONING == "provisioning"
        assert PodState.RUNNING == "running"
        assert PodState.STOPPING == "stopping"
        assert PodState.STOPPED == "stopped"
        assert PodState.RESUMING == "resuming"
        assert PodState.TERMINATING == "terminating"
        assert PodState.TERMINATED == "terminated"

    def test_all_states_defined(self) -> None:
        expected = {
            "defined",
            "provisioning",
            "running",
            "stopping",
            "stopped",
            "resuming",
            "terminating",
            "terminated",
        }
        actual = {s.value for s in PodState}
        assert actual == expected

    def test_transition_table_completeness(self) -> None:
        """Every PodState must appear as a key in VALID_TRANSITIONS."""
        for state in PodState:
            assert state in VALID_TRANSITIONS, f"{state} missing from VALID_TRANSITIONS"

    def test_transition_defined(self) -> None:
        assert VALID_TRANSITIONS[PodState.DEFINED] == {PodState.PROVISIONING}

    def test_transition_provisioning(self) -> None:
        assert VALID_TRANSITIONS[PodState.PROVISIONING] == {
            PodState.RUNNING,
            PodState.TERMINATED,
        }

    def test_transition_running(self) -> None:
        assert VALID_TRANSITIONS[PodState.RUNNING] == {
            PodState.STOPPING,
            PodState.TERMINATING,
        }

    def test_transition_stopping(self) -> None:
        assert VALID_TRANSITIONS[PodState.STOPPING] == {
            PodState.STOPPED,
            PodState.TERMINATED,
        }

    def test_transition_stopped(self) -> None:
        assert VALID_TRANSITIONS[PodState.STOPPED] == {
            PodState.RESUMING,
            PodState.TERMINATING,
        }

    def test_transition_resuming(self) -> None:
        assert VALID_TRANSITIONS[PodState.RESUMING] == {
            PodState.RUNNING,
            PodState.TERMINATED,
        }

    def test_transition_terminating(self) -> None:
        assert VALID_TRANSITIONS[PodState.TERMINATING] == {PodState.TERMINATED}

    def test_transition_terminated(self) -> None:
        assert VALID_TRANSITIONS[PodState.TERMINATED] == set()

    def test_api_status_map(self) -> None:
        assert API_STATUS_MAP["RUNNING"] == PodState.RUNNING
        assert API_STATUS_MAP["EXITED"] == PodState.STOPPED
        assert API_STATUS_MAP["TERMINATED"] == PodState.TERMINATED
        assert API_STATUS_MAP["CREATED"] == PodState.PROVISIONING


class TestPodConfig:
    def test_defaults(self) -> None:
        cfg = PodConfig()
        assert cfg.gpu_count == 1
        assert cfg.cloud_type == "ALL"
        assert cfg.container_disk_in_gb == 10
        assert cfg.volume_in_gb == 0
        assert cfg.volume_mount_path == "/runpod-volume"
        assert cfg.network_volume_id is None
        assert cfg.ports is None
        assert cfg.docker_args == ""
        assert cfg.start_ssh is True
        assert cfg.support_public_ip is True
        assert cfg.data_center_id is None
        assert cfg.country_code is None
        assert cfg.min_vcpu_count == 1
        assert cfg.min_memory_in_gb == 1
        assert cfg.allowed_cuda_versions is None
        assert cfg.min_download is None
        assert cfg.min_upload is None
        assert cfg.instance_id is None
        assert cfg.template_id is None

    def test_frozen(self) -> None:
        cfg = PodConfig()
        with pytest.raises(AttributeError):
            cfg.gpu_count = 2  # type: ignore[misc]

    def test_ports_str_none(self) -> None:
        cfg = PodConfig(ports=None)
        assert cfg.ports_str is None

    def test_ports_str_single(self) -> None:
        cfg = PodConfig(ports=["8080/http"])
        assert cfg.ports_str == "8080/http"

    def test_ports_str_multiple(self) -> None:
        cfg = PodConfig(ports=["8080/http", "22/tcp"])
        assert cfg.ports_str == "8080/http,22/tcp"


class TestPod:
    def test_minimal_construction(self) -> None:
        pod = Pod(name="test-pod", image="ubuntu:latest")
        assert pod.name == "test-pod"
        assert pod.image == "ubuntu:latest"
        assert pod.gpu is None
        assert pod.env == {}
        assert pod.config == PodConfig()
        assert pod._pod_id is None
        assert pod._state == PodState.DEFINED
        assert pod._address is None

    def test_with_gpu(self) -> None:
        pod = Pod(name="gpu-pod", image="cuda:12", gpu="NVIDIA A100 80GB PCIe")
        assert pod.gpu == "NVIDIA A100 80GB PCIe"

    def test_with_env(self) -> None:
        env = {"MODEL": "llama", "BATCH": "32"}
        pod = Pod(name="env-pod", image="ubuntu:latest", env=env)
        assert pod.env == env

    def test_with_explicit_config(self) -> None:
        cfg = PodConfig(gpu_count=4, container_disk_in_gb=50)
        pod = Pod(name="cfg-pod", image="ubuntu:latest", config=cfg)
        assert pod.config is cfg
        assert pod.config.gpu_count == 4

    def test_kwargs_become_config(self) -> None:
        pod = Pod(name="kw-pod", image="ubuntu:latest", gpu_count=2, start_ssh=False)
        assert pod.config.gpu_count == 2
        assert pod.config.start_ssh is False

    def test_config_hash_stability(self) -> None:
        """Same inputs produce same hash."""
        pod_a = Pod(name="stable", image="img:1", gpu="A100")
        pod_b = Pod(name="stable", image="img:1", gpu="A100")
        assert pod_a.config_hash == pod_b.config_hash

    def test_config_hash_changes(self) -> None:
        """Different inputs produce different hashes."""
        pod_a = Pod(name="a", image="img:1")
        pod_b = Pod(name="b", image="img:1")
        assert pod_a.config_hash != pod_b.config_hash

    def test_config_and_kwargs_raises_valueerror(self) -> None:
        cfg = PodConfig()
        with pytest.raises(ValueError, match="Cannot provide both"):
            Pod(name="bad", image="img", config=cfg, gpu_count=2)
