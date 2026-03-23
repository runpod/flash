"""Pod lifecycle manager and drift detection.

Manages pod state transitions (provision, stop, resume, terminate)
and persists pod tracking data to .flash/pods.json for drift detection.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from runpod_flash.core.exceptions import InvalidPodStateError
from runpod_flash.core.resources.pod import API_STATUS_MAP, PodState, VALID_TRANSITIONS

if TYPE_CHECKING:
    from runpod_flash.core.api.pod_client import PodApiClient, PodApiResponse
    from runpod_flash.core.resources.pod import Pod

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PodTrackerEntry:
    """Persisted snapshot of a pod's identity and config at save time."""

    name: str
    pod_id: str
    image: str
    gpu: str | None
    state: str
    address: str | None
    config_hash: str
    created_at: str


class PodTracker:
    """Persists pod state to .flash/pods.json for drift detection.

    Uses a separate lock file for write safety, compatible with the
    binary-handle file_lock utility.

    Args:
        flash_dir: Path to the .flash directory.
    """

    def __init__(self, flash_dir: Path) -> None:
        self._path = flash_dir / "pods.json"

    def save(self, pod: Pod) -> None:
        """Write or update a pod entry.

        Args:
            pod: Pod instance to persist.
        """
        entries = self._read_all()
        entries[pod.name] = PodTrackerEntry(
            name=pod.name,
            pod_id=pod._pod_id or "",
            image=pod.image,
            gpu=str(pod.gpu) if pod.gpu is not None else None,
            state=pod._state.value,
            address=pod._address,
            config_hash=pod.config_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._write_all(entries)

    def load(self, pod_name: str) -> PodTrackerEntry | None:
        """Load a single pod entry by name.

        Args:
            pod_name: Name of the pod to look up.

        Returns:
            PodTrackerEntry if found, None otherwise.
        """
        entries = self._read_all()
        return entries.get(pod_name)

    def load_all(self) -> list[PodTrackerEntry]:
        """Load all tracked pod entries.

        Returns:
            List of all PodTrackerEntry instances.
        """
        return list(self._read_all().values())

    def remove(self, pod_name: str) -> None:
        """Remove a pod entry by name.

        Args:
            pod_name: Name of the pod to remove.
        """
        entries = self._read_all()
        entries.pop(pod_name, None)
        self._write_all(entries)

    def _read_all(self) -> dict[str, PodTrackerEntry]:
        """Deserialize all entries from disk.

        No locking needed -- reads are safe enough, and the lock file
        may not exist yet on first access.

        Returns:
            Dict mapping pod name to PodTrackerEntry.
        """
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Failed to read pods.json, returning empty tracker")
            return {}
        return {name: PodTrackerEntry(**data) for name, data in raw.items()}

    def _write_all(self, entries: dict[str, PodTrackerEntry]) -> None:
        """Serialize all entries to disk with file locking.

        Args:
            entries: Dict mapping pod name to PodTrackerEntry.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(".lock")
        lock_path.touch(exist_ok=True)
        with open(lock_path, "rb+") as lock_fh:
            from runpod_flash.core.utils.file_lock import file_lock

            with file_lock(lock_fh, exclusive=True):
                data = {name: asdict(entry) for name, entry in entries.items()}
                with open(self._path, "w") as f:
                    json.dump(data, f, indent=2)


class PodLifecycleManager:
    """Drives pod state transitions through the Runpod API.

    Each method validates the transition, calls the API, updates pod
    runtime state, and persists via PodTracker.

    Args:
        api_client: Async Runpod pod API client.
        tracker: PodTracker for persistence.
    """

    def __init__(self, api_client: PodApiClient, tracker: PodTracker) -> None:
        self._api = api_client
        self._tracker = tracker

    async def provision(self, pod: Pod) -> Pod:
        """Create a new pod: DEFINED -> PROVISIONING -> RUNNING.

        Args:
            pod: Pod in DEFINED state.

        Returns:
            Pod updated with pod_id, state=RUNNING, and address.
        """
        self._assert_transition(pod, PodState.PROVISIONING)
        pod._state = PodState.PROVISIONING

        response = await self._api.create(pod)

        pod._pod_id = response.pod_id
        pod._state = PodState.RUNNING
        pod._address = self._resolve_address(response)
        self._tracker.save(pod)
        return pod

    async def stop(self, pod: Pod) -> Pod:
        """Stop a running pod: RUNNING -> STOPPING -> STOPPED.

        Args:
            pod: Pod in RUNNING state.

        Returns:
            Pod with state=STOPPED.
        """
        self._assert_transition(pod, PodState.STOPPING)
        pod._state = PodState.STOPPING

        await self._api.stop(pod._pod_id)

        pod._state = PodState.STOPPED
        pod._address = None
        self._tracker.save(pod)
        return pod

    async def resume(self, pod: Pod) -> Pod:
        """Resume a stopped pod: STOPPED -> RESUMING -> RUNNING.

        Args:
            pod: Pod in STOPPED state.

        Returns:
            Pod with state=RUNNING and updated address.
        """
        self._assert_transition(pod, PodState.RESUMING)
        pod._state = PodState.RESUMING

        response = await self._api.resume(pod._pod_id, pod.config.gpu_count)

        pod._state = PodState.RUNNING
        pod._address = self._resolve_address(response)
        self._tracker.save(pod)
        return pod

    async def terminate(self, pod: Pod) -> Pod:
        """Terminate a pod from any state: * -> TERMINATING -> TERMINATED.

        Args:
            pod: Pod in any non-TERMINATED state.

        Returns:
            Pod with state=TERMINATED.
        """
        self._assert_transition(pod, PodState.TERMINATING)
        pod._state = PodState.TERMINATING

        await self._api.terminate(pod._pod_id)

        pod._state = PodState.TERMINATED
        pod._address = None
        self._tracker.remove(pod.name)
        return pod

    async def sync_state(self, pod: Pod) -> Pod:
        """Query the API and reconcile local state.

        Args:
            pod: Pod with a known pod_id.

        Returns:
            Pod with state updated from API status.
        """
        response = await self._api.get(pod._pod_id)
        api_state = API_STATUS_MAP.get(response.desired_status)
        if api_state is not None:
            pod._state = api_state
        pod._address = self._resolve_address(response)
        self._tracker.save(pod)
        return pod

    def _assert_transition(self, pod: Pod, target: PodState) -> None:
        """Validate that the transition from current state to target is allowed.

        Args:
            pod: Pod whose current state to check.
            target: Desired target state.

        Raises:
            InvalidPodStateError: If the transition is not in VALID_TRANSITIONS.
        """
        valid = VALID_TRANSITIONS.get(pod._state, set())
        if target not in valid:
            raise InvalidPodStateError(pod.name, pod._state, target, valid)

    @staticmethod
    def _resolve_address(response: PodApiResponse) -> str | None:
        """Extract a public URL from the first port mapping.

        Args:
            response: API response with optional ports dict.

        Returns:
            URL string like "http://ip:port" or None.
        """
        if not response.ports:
            return None
        first = next(iter(response.ports.values()))
        return f"http://{first.host_ip}:{first.host_port}"


@dataclass(frozen=True, slots=True)
class PodDrift:
    """Result of comparing a Pod definition against a tracked entry."""

    image_changed: bool
    env_changed: bool
    gpu_changed: bool
    config_changed: bool

    @property
    def requires_rebuild(self) -> bool:
        """True if image or GPU changed, requiring pod recreation."""
        return self.image_changed or self.gpu_changed


def detect_pod_drift(pod: Pod, entry: PodTrackerEntry) -> PodDrift | None:
    """Compare a Pod definition against a PodTrackerEntry.

    Args:
        pod: Current pod definition.
        entry: Previously tracked entry.

    Returns:
        PodDrift describing what changed, or None if no drift detected.
    """
    gpu_str = str(pod.gpu) if pod.gpu is not None else None
    image_changed = pod.image != entry.image
    gpu_changed = gpu_str != entry.gpu
    config_changed = pod.config_hash != entry.config_hash
    # env is captured in config_hash but not separately tracked in entry,
    # so env_changed is True when config hash differs but image/gpu are same
    env_changed = config_changed and not image_changed and not gpu_changed

    drift = PodDrift(
        image_changed=image_changed,
        env_changed=env_changed,
        gpu_changed=gpu_changed,
        config_changed=config_changed,
    )

    if not any(
        [
            drift.image_changed,
            drift.env_changed,
            drift.gpu_changed,
            drift.config_changed,
        ]
    ):
        return None

    return drift
