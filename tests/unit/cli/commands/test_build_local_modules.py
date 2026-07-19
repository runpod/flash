from pathlib import Path

import pytest

from runpod_flash.cli.commands.build import validate_local_module_imports
from runpod_flash.cli.commands.build_utils.scanner import defines_endpoint
from runpod_flash.core.exceptions import LocalModuleResolutionError


def test_endpoint_import_of_ignored_file_raises(tmp_path: Path):
    # endpoint imports a module whose file the ignore rules dropped (its name
    # matches the built-in test_*.py rule), so it is not among the shipped files.
    # Force-including it would silently override a deliberate exclusion; refuse.
    (tmp_path / "test_helpers.py").write_text("def h():\n    return 1\n")
    endpoint = tmp_path / "endpoint.py"
    endpoint.write_text(
        "import test_helpers\n\ndef handler():\n    return test_helpers.h()\n"
    )
    files = [endpoint]  # test_helpers.py excluded by the ignore filter

    with pytest.raises(LocalModuleResolutionError, match="test_helpers.py"):
        validate_local_module_imports(files, tmp_path)


def test_non_endpoint_import_of_ignored_file_raises(tmp_path: Path):
    # The refusal is not scoped to endpoint files: any shipped file that imports
    # an excluded local module would break the worker, so the build fails loudly.
    (tmp_path / "test_helpers.py").write_text("def h():\n    return 1\n")
    incidental = tmp_path / "incidental.py"
    incidental.write_text(
        "import test_helpers\n\ndef helper():\n    return test_helpers.h()\n"
    )
    files = [incidental]

    with pytest.raises(LocalModuleResolutionError, match="test_helpers.py"):
        validate_local_module_imports(files, tmp_path)


def test_leaves_build_alone_when_all_imports_are_shipped(tmp_path: Path):
    # A locally imported sibling that is itself shipped is not a conflict.
    sibling = tmp_path / "helpers.py"
    sibling.write_text("def h():\n    return 1\n")
    endpoint = tmp_path / "endpoint.py"
    endpoint.write_text("import helpers\n\ndef handler():\n    return helpers.h()\n")
    files = [endpoint, sibling]

    assert validate_local_module_imports(files, tmp_path) is None


def test_leaves_build_alone_when_no_local_imports(tmp_path: Path):
    endpoint = tmp_path / "endpoint.py"
    endpoint.write_text("import os\n\ndef handler():\n    return os.getpid()\n")
    files = [endpoint]

    assert validate_local_module_imports(files, tmp_path) is None


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
        validate_local_module_imports(files, tmp_path)


def test_endpoint_file_with_non_utf8_sibling_raises_resolution_error(tmp_path: Path):
    # A valid endpoint importing a sibling with non-UTF-8 bytes triggers a raw
    # UnicodeDecodeError during resolution. It must be normalized to
    # LocalModuleResolutionError so run_build() reports it cleanly.
    (tmp_path / "badsibling.py").write_bytes(b"\xff\xfe not valid utf-8\n")
    endpoint = tmp_path / "endpoint.py"
    endpoint.write_text(
        "import badsibling\n\n"
        "from runpod_flash import Endpoint\n\n"
        "@Endpoint\n"
        "def handler():\n"
        "    return badsibling.value\n"
    )
    files = [endpoint]

    with pytest.raises(LocalModuleResolutionError, match="endpoint.py") as excinfo:
        validate_local_module_imports(files, tmp_path)
    # the raw decode error is preserved as the cause for debugging
    assert isinstance(excinfo.value.__cause__, UnicodeDecodeError)


def test_non_endpoint_file_with_unresolvable_import_does_not_raise(tmp_path: Path):
    incidental = tmp_path / "incidental.py"
    incidental.write_text(
        "from . import nonexistent_sibling\n\n"
        "def helper():\n"
        "    return nonexistent_sibling.value\n"
    )
    files = [incidental]

    assert validate_local_module_imports(files, tmp_path) is None


def test_defines_endpoint_true_for_decorated_functions(tmp_path: Path):
    endpoint_call = tmp_path / "endpoint_call.py"
    endpoint_call.write_text(
        "from runpod_flash import Endpoint\n\n@Endpoint(name='foo')\ndef handler():\n    return 1\n"
    )
    remote_plain = tmp_path / "remote_plain.py"
    remote_plain.write_text(
        "from runpod_flash import remote\n\n@remote\ndef handler():\n    return 1\n"
    )

    assert defines_endpoint(endpoint_call) is True
    assert defines_endpoint(remote_plain) is True


def test_defines_endpoint_false_for_plain_module(tmp_path: Path):
    plain = tmp_path / "plain.py"
    plain.write_text("def helper():\n    return 1\n")

    assert defines_endpoint(plain) is False
