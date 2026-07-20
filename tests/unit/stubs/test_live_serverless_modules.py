import pytest

from runpod_flash.core.exceptions import LocalModulePayloadTooLargeError
from runpod_flash.stubs import live_serverless
from runpod_flash.stubs.live_serverless import build_modules_map


def test_build_modules_map_collects_sibling(tmp_path):
    (tmp_path / "utils.py").write_text("def x():\n    return 1\n")
    entry = tmp_path / "endpoint.py"
    func_source = "def handler():\n    import utils\n    return utils.x()\n"
    entry.write_text(func_source)
    modules = build_modules_map(func_source, str(entry))
    assert modules == {"utils.py": "def x():\n    return 1\n"}


def test_build_modules_map_enforces_size_cap(tmp_path, monkeypatch):
    (tmp_path / "big.py").write_text("x = 1\n")
    entry = tmp_path / "endpoint.py"
    func_source = "def handler():\n    import big\n    return big.x\n"
    entry.write_text(func_source)
    monkeypatch.setattr(live_serverless, "MAX_INLINE_MODULE_BYTES", 1)
    with pytest.raises(LocalModulePayloadTooLargeError):
        build_modules_map(func_source, str(entry))


def test_build_modules_map_no_file_returns_empty():
    # No __file__ (e.g. REPL-defined function) -> nothing to resolve, no crash.
    assert build_modules_map("def handler():\n    return 1\n", None) == {}
