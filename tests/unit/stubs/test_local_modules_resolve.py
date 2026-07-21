from pathlib import Path

import pytest

from runpod_flash.core.exceptions import LocalModuleResolutionError
from runpod_flash.stubs.local_modules import resolve_local_modules


def _entry(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "endpoint.py"
    f.write_text(body)
    return f


def test_includes_sibling_module(tmp_path: Path):
    (tmp_path / "utils.py").write_text("def x():\n    return 1\n")
    entry = _entry(tmp_path, "import utils\n\ndef handler():\n    return utils.x()\n")
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert "utils.py" in result.files


def test_skips_stdlib_and_external(tmp_path: Path):
    entry = _entry(
        tmp_path, "import os\nimport numpy\n\ndef handler():\n    return os.getpid()\n"
    )
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert result.files == {}


def test_follows_transitive_local_imports(tmp_path: Path):
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text("import c\n")
    (tmp_path / "c.py").write_text("VALUE = 3\n")
    entry = _entry(tmp_path, "import a\n\ndef handler():\n    return a\n")
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert set(result.files) == {"a.py", "b.py", "c.py"}


def test_pulls_package_init_for_submodule(tmp_path: Path):
    pkg = tmp_path / "helpers"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("\n")
    (pkg / "audio.py").write_text("def load():\n    return 1\n")
    entry = _entry(
        tmp_path,
        "from helpers.audio import load\n\ndef handler():\n    return load()\n",
    )
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert set(result.files) == {"helpers/__init__.py", "helpers/audio.py"}


def test_from_package_import_submodule_by_name(tmp_path: Path):
    # `from helpers import audio` where audio is a submodule (helpers/audio.py),
    # not a symbol re-exported by helpers/__init__.py. The submodule file must be
    # bundled, otherwise the worker raises ModuleNotFoundError at import time.
    pkg = tmp_path / "helpers"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("\n")
    (pkg / "audio.py").write_text("def load():\n    return 1\n")
    entry = _entry(
        tmp_path,
        "from helpers import audio\n\ndef handler():\n    return audio.load()\n",
    )
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert set(result.files) == {"helpers/__init__.py", "helpers/audio.py"}


def test_from_package_import_reexported_symbol_is_not_a_module(tmp_path: Path):
    # `from helpers import load` where load is a function defined in __init__.py,
    # not a submodule. Only the package init ships; the name is not mistaken for a
    # missing submodule file and does not raise.
    pkg = tmp_path / "helpers"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def load():\n    return 1\n")
    entry = _entry(
        tmp_path,
        "from helpers import load\n\ndef handler():\n    return load()\n",
    )
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert set(result.files) == {"helpers/__init__.py"}


def test_relative_from_package_import_submodule_by_name(tmp_path: Path):
    # Relative form: `from .helpers import audio`. A name that does not back a
    # submodule file (a re-exported symbol) must not raise on the relative path.
    pkg = tmp_path / "helpers"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("VALUE = 1\n")
    (pkg / "audio.py").write_text("def load():\n    return 1\n")
    entry = _entry(
        tmp_path,
        "from .helpers import audio, VALUE\n\ndef handler():\n    return audio.load()\n",
    )
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert set(result.files) == {"helpers/__init__.py", "helpers/audio.py"}


def test_in_body_import_is_discovered(tmp_path: Path):
    (tmp_path / "utils.py").write_text("def x():\n    return 1\n")
    entry = _entry(tmp_path, "def handler():\n    import utils\n    return utils.x()\n")
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert "utils.py" in result.files


def test_import_cycle_terminates(tmp_path: Path):
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text("import a\n")
    entry = _entry(tmp_path, "import a\n")
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert set(result.files) == {"a.py", "b.py"}


def test_unresolved_relative_import_raises(tmp_path: Path):
    entry = _entry(tmp_path, "from . import missing\n")
    with pytest.raises(LocalModuleResolutionError):
        resolve_local_modules(entry.read_text(), entry, tmp_path)


def test_dynamic_literal_is_resolved(tmp_path: Path):
    (tmp_path / "plugin.py").write_text("Z = 9\n")
    entry = _entry(
        tmp_path,
        "import importlib\n\ndef handler():\n    return importlib.import_module('plugin')\n",
    )
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert "plugin.py" in result.files


def test_dynamic_nonliteral_warns_not_raises(tmp_path: Path):
    entry = _entry(
        tmp_path,
        "import importlib\n\ndef handler(name):\n    return importlib.import_module(name)\n",
    )
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert result.files == {}
    assert any("dynamic import" in w for w in result.warnings)


def test_bare_relative_import_resolves_submodule(tmp_path):
    (tmp_path / "__init__.py").write_text("\n")
    (tmp_path / "helper.py").write_text("X = 1\n")
    entry = _entry(
        tmp_path, "from . import helper\n\ndef handler():\n    return helper.X\n"
    )
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert "helper.py" in result.files


def test_local_file_outside_project_root_raises(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (tmp_path / "utils.py").write_text("x = 1\n")
    entry = _entry(tmp_path, "import utils\n\ndef handler():\n    return utils.x\n")
    with pytest.raises(LocalModuleResolutionError):
        resolve_local_modules(entry.read_text(), entry, proj)


def test_bare_relative_star_import_resolves_package_init(tmp_path):
    (tmp_path / "__init__.py").write_text("VALUE = 1\n")
    entry = _entry(tmp_path, "from . import *\n\ndef handler():\n    return VALUE\n")
    result = resolve_local_modules(entry.read_text(), entry, tmp_path)
    assert "__init__.py" in result.files
