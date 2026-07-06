from pathlib import Path

from runpod_flash.stubs.local_modules import (
    MAX_INLINE_MODULE_BYTES,
    is_stdlib,
    local_path_for,
)


def test_cap_is_8_mib():
    assert MAX_INLINE_MODULE_BYTES == 8 * 1024 * 1024


def test_is_stdlib_true_for_os_and_dotted():
    assert is_stdlib("os")
    assert is_stdlib("os.path")


def test_is_stdlib_false_for_unknown():
    assert not is_stdlib("utils")


def test_local_path_for_finds_sibling_module(tmp_path: Path):
    (tmp_path / "utils.py").write_text("x = 1\n")
    assert local_path_for("utils", [tmp_path]) == tmp_path / "utils.py"


def test_local_path_for_finds_package_init(tmp_path: Path):
    pkg = tmp_path / "helpers"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("\n")
    assert local_path_for("helpers", [tmp_path]) == pkg / "__init__.py"


def test_local_path_for_finds_dotted_submodule(tmp_path: Path):
    pkg = tmp_path / "helpers"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("\n")
    (pkg / "audio.py").write_text("y = 2\n")
    assert local_path_for("helpers.audio", [tmp_path]) == pkg / "audio.py"


def test_local_path_for_returns_none_for_external(tmp_path: Path):
    assert local_path_for("numpy", [tmp_path]) is None
