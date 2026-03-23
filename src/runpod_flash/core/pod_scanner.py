"""Pod scanner for discovering Pod instances in application modules.

Walks module-level attributes to find all Pod instances defined by the user.
"""

from __future__ import annotations

import inspect
from types import ModuleType

from runpod_flash.core.resources.pod import Pod


class PodScanner:
    """Scans a Python module for Pod instances.

    Examines all module-level attributes and returns those that are
    instances of Pod, preserving discovery order.
    """

    def scan(self, app_module: ModuleType) -> list[Pod]:
        """Walk module attributes and return all Pod instances.

        Args:
            app_module: The imported module to scan.

        Returns:
            List of Pod instances found at module level.
        """
        pods: list[Pod] = []
        for _name, obj in inspect.getmembers(app_module):
            if isinstance(obj, Pod):
                pods.append(obj)
        return pods
