from pathlib import Path

import pytest

from runpod_flash.cli.commands.build import (
    _defines_endpoint,
    augment_with_local_modules,
)
from runpod_flash.core.exceptions import LocalModuleResolutionError


def test_force_includes_module_dropped_by_ignore_rule(tmp_path: Path):
    # endpoint imports a module whose name matches the built-in test_*.py ignore rule
    (tmp_path / "test_helpers.py").write_text("def h():\n    return 1\n")
    endpoint = tmp_path / "endpoint.py"
    endpoint.write_text(
        "import test_helpers\n\ndef handler():\n    return test_helpers.h()\n"
    )

    # simulate the ignore filter having dropped test_helpers.py
    files = [endpoint]
    augmented = augment_with_local_modules(files, tmp_path)

    assert (tmp_path / "test_helpers.py") in augmented
    assert endpoint in augmented


def test_leaves_files_untouched_when_no_local_imports(tmp_path: Path):
    endpoint = tmp_path / "endpoint.py"
    endpoint.write_text("import os\n\ndef handler():\n    return os.getpid()\n")
    files = [endpoint]
    assert augment_with_local_modules(files, tmp_path) == [endpoint]


def test_endpoint_file_with_unresolvable_import_raises(tmp_path: Path):
    endpoint = tmp_path / "endpoint.py"
    endpoint.write_text(
        "from . import nonexistent_sibling\n\n"
        "from runpod_flash import Endpoint\n\n"
        "@Endpoint\n"
        "def handler():\n"
        "    return nonexistent_sibling.value\n"
    )
    files = [endpoint]

    with pytest.raises(LocalModuleResolutionError):
        augment_with_local_modules(files, tmp_path)


def test_non_endpoint_file_with_unresolvable_import_does_not_raise(tmp_path: Path):
    incidental = tmp_path / "incidental.py"
    incidental.write_text(
        "from . import nonexistent_sibling\n\n"
        "def helper():\n"
        "    return nonexistent_sibling.value\n"
    )
    files = [incidental]

    augmented = augment_with_local_modules(files, tmp_path)

    assert augmented == [incidental]


def test_defines_endpoint_true_for_decorated_functions(tmp_path: Path):
    endpoint_call = tmp_path / "endpoint_call.py"
    endpoint_call.write_text(
        "from runpod_flash import Endpoint\n\n@Endpoint(name='foo')\ndef handler():\n    return 1\n"
    )
    remote_plain = tmp_path / "remote_plain.py"
    remote_plain.write_text(
        "from runpod_flash import remote\n\n@remote\ndef handler():\n    return 1\n"
    )

    assert _defines_endpoint(endpoint_call) is True
    assert _defines_endpoint(remote_plain) is True


def test_defines_endpoint_false_for_plain_module(tmp_path: Path):
    plain = tmp_path / "plain.py"
    plain.write_text("def helper():\n    return 1\n")

    assert _defines_endpoint(plain) is False
