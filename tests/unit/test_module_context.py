"""Tests for module_context — AST-based module-level dependency extraction.

Validates that extract_module_context() correctly identifies and extracts
module-level definitions (imports, constants, helpers, classes) that a
@remote function references, so the augmented source is self-contained
when exec()'d in an empty namespace on the worker.
"""

import textwrap
import time


# ---------------------------------------------------------------------------
# Helpers: write temp modules and create functions from them
# ---------------------------------------------------------------------------


def _write_module(tmp_path, filename, source):
    """Write a Python module to tmp_path and return the file path."""
    path = tmp_path / filename
    path.write_text(textwrap.dedent(source))
    return path


def _load_function_from_module(module_path, func_name):
    """Import a function from a module file by path, return the function object."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_test_mod", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, func_name)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestExtractModuleContext:
    """Tests for extract_module_context() public API."""

    def test_function_references_module_constant(self, tmp_path):
        """Module-level constant referenced by function is included."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            MAX_RETRIES = 3

            def process(x):
                return x * MAX_RETRIES
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "MAX_RETRIES = 3" in context

    def test_function_references_module_import(self, tmp_path):
        """Module-level import used by function is included."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            import os

            def get_cwd():
                return os.getcwd()
            """,
        )
        func = _load_function_from_module(mod_path, "get_cwd")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "import os" in context

    def test_function_references_from_import(self, tmp_path):
        """from X import Y used by function is included."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            from pathlib import Path

            def make_path(s):
                return Path(s)
            """,
        )
        func = _load_function_from_module(mod_path, "make_path")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "from pathlib import Path" in context

    def test_function_calls_module_helper(self, tmp_path):
        """Module-level helper function called by target is included."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            def _validate(x):
                return x > 0

            def process(x):
                if _validate(x):
                    return x * 2
                return 0
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "def _validate(x):" in context

    def test_transitive_dependency(self, tmp_path):
        """Helper that uses a constant pulls in both helper and constant."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            TIME_FORMAT = "%Y-%m-%d"

            def parse_timestamp(ts):
                from datetime import datetime
                return datetime.strptime(ts, TIME_FORMAT)

            def process(ts):
                return parse_timestamp(ts)
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "parse_timestamp" in context
        assert 'TIME_FORMAT = "%Y-%m-%d"' in context

    def test_function_references_module_class(self, tmp_path):
        """Module-level class referenced by function is included."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            class Config:
                timeout = 30
                retries = 3

            def get_timeout():
                return Config.timeout
            """,
        )
        func = _load_function_from_module(mod_path, "get_timeout")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "class Config:" in context

    def test_only_builtins_and_locals_returns_empty(self, tmp_path):
        """Function using only builtins and local vars produces empty context."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            UNUSED_CONST = 42

            def process(x):
                result = x + 1
                return str(result)
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert context == ""

    def test_main_guard_excluded(self, tmp_path):
        """if __name__ == '__main__': block is never included."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            CONST = 10

            def process(x):
                return x + CONST

            if __name__ == "__main__":
                process(5)
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "CONST = 10" in context
        assert "__main__" not in context

    def test_remote_decorated_function_excluded(self, tmp_path):
        """@remote-decorated definitions are excluded (handled by stubs)."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            def remote(func):
                func.__remote_config__ = {}
                return func

            SCALE = 2

            @remote
            def gpu_worker(x):
                return x * SCALE

            def process(x):
                return gpu_worker(x) + SCALE
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        # SCALE should be included (it's a constant process uses)
        assert "SCALE = 2" in context
        # gpu_worker should NOT be included (it has @remote decorator)
        assert "def gpu_worker" not in context

    def test_augmented_source_executes_in_empty_namespace(self, tmp_path):
        """Combined context + function source exec()s without NameError."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            import json

            DEFAULT_CONFIG = {"timeout": 30}

            def merge_config(overrides):
                base = DEFAULT_CONFIG.copy()
                base.update(overrides)
                return json.dumps(base)

            def process(data):
                return merge_config(data)
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source
        from runpod_flash.stubs.dependency_resolver import build_augmented_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)
        augmented = build_augmented_source(source, [context]) if context else source

        # Execute in empty namespace — should not raise NameError
        namespace = {}
        exec(augmented, namespace)
        result = namespace["process"]({"retries": 5})
        assert '"timeout": 30' in result
        assert '"retries": 5' in result

    def test_caching_returns_same_result(self, tmp_path):
        """Second call with same function hits cache."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            CONST = 42

            def process(x):
                return x + CONST
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import (
            extract_module_context,
            _MODULE_AST_CACHE,
        )
        from runpod_flash.stubs.live_serverless import get_function_source

        # Clear cache to start fresh
        _MODULE_AST_CACHE.clear()

        source, _ = get_function_source(func)
        result1 = extract_module_context(func, source)
        result2 = extract_module_context(func, source)

        assert result1 == result2
        # Cache should have exactly one entry for the module
        assert len(_MODULE_AST_CACHE) == 1

    def test_mtime_change_invalidates_cache(self, tmp_path):
        """Modifying the source file invalidates the AST cache."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            OLD_CONST = 1

            def process(x):
                return x + OLD_CONST
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import (
            extract_module_context,
            _MODULE_AST_CACHE,
        )
        from runpod_flash.stubs.live_serverless import get_function_source

        _MODULE_AST_CACHE.clear()

        source, _ = get_function_source(func)
        result1 = extract_module_context(func, source)
        assert "OLD_CONST = 1" in result1

        # Modify the file (ensure mtime changes)
        time.sleep(0.05)
        mod_path.write_text(
            textwrap.dedent("""\
            NEW_CONST = 99

            def process(x):
                return x + NEW_CONST
            """)
        )

        # Reload the function from the modified module
        func2 = _load_function_from_module(mod_path, "process")
        source2, _ = get_function_source(func2)
        result2 = extract_module_context(func2, source2)

        assert "NEW_CONST = 99" in result2
        assert "OLD_CONST" not in result2

    def test_non_file_backed_function_returns_empty(self):
        """Function not backed by a source file (e.g., exec'd) returns empty."""
        # Create a function via exec — no source file
        namespace = {}
        exec("def dynamic_func(x): return x + 1", namespace)
        func = namespace["dynamic_func"]

        from runpod_flash.stubs.module_context import extract_module_context

        context = extract_module_context(func, "def dynamic_func(x): return x + 1\n")
        assert context == ""

    def test_preserves_module_order(self, tmp_path):
        """Extracted definitions maintain their original module order."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            import os

            BASE_DIR = "/tmp"

            def build_path(name):
                return os.path.join(BASE_DIR, name)

            def process(name):
                return build_path(name)
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        # os import should come before BASE_DIR, which should come before build_path
        os_pos = context.index("import os")
        base_pos = context.index("BASE_DIR")
        build_pos = context.index("def build_path")
        assert os_pos < base_pos < build_pos

    def test_multiline_assignment(self, tmp_path):
        """Multi-line constant assignment is fully captured."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            DEFAULTS = {
                "timeout": 30,
                "retries": 3,
                "debug": False,
            }

            def process():
                return DEFAULTS.copy()
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source
        from runpod_flash.stubs.dependency_resolver import build_augmented_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "DEFAULTS" in context
        # Verify it actually works when exec'd
        augmented = build_augmented_source(source, [context]) if context else source
        ns = {}
        exec(augmented, ns)
        assert ns["process"]() == {"timeout": 30, "retries": 3, "debug": False}

    def test_type_annotated_assignment(self, tmp_path):
        """Type-annotated module-level assignment is captured."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            THRESHOLD: float = 0.95

            def check(value):
                return value >= THRESHOLD
            """,
        )
        func = _load_function_from_module(mod_path, "check")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "THRESHOLD" in context
        assert "0.95" in context

    def test_async_helper_function(self, tmp_path):
        """Async helper function referenced by target is included."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            async def fetch_data(url):
                return {"data": url}

            async def process(url):
                return await fetch_data(url)
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "async def fetch_data" in context

    def test_bare_expressions_excluded(self, tmp_path):
        """Bare expressions (function calls, prints) are not included."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            import logging
            logging.basicConfig(level=logging.INFO)

            CONST = 5

            def process(x):
                return x + CONST
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "CONST = 5" in context
        # The bare logging.basicConfig() call should not be included
        assert "basicConfig" not in context

    def test_class_with_inheritance(self, tmp_path):
        """Class that inherits from a module-level base pulls in both."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            class Base:
                value = 10

            class Config(Base):
                extra = 20

            def process():
                return Config.value + Config.extra
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source
        from runpod_flash.stubs.dependency_resolver import build_augmented_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "class Config" in context
        # Base should be pulled in transitively (Config references Base)
        assert "class Base:" in context

        # Verify execution
        augmented = build_augmented_source(source, [context]) if context else source
        ns = {}
        exec(augmented, ns)
        assert ns["process"]() == 30


def _load_function_with_sys_path(tmp_path, module_path, func_name):
    """Load a function after temporarily adding tmp_path to sys.path."""
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        return _load_function_from_module(module_path, func_name)
    finally:
        sys.path.remove(str(tmp_path))


class TestExcludeNames:
    """Tests for exclude_names parameter — prevents extracting imports
    for names that will be provided as @remote stubs."""

    def test_excluded_names_omit_import(self, tmp_path):
        """Import providing only excluded names is not included in context."""
        # helper.py provides compute(); main.py imports and calls it
        _write_module(tmp_path, "helper.py", "def compute(x): return x * 2\n")
        mod_path = _write_module(
            tmp_path,
            "main.py",
            """\
            from helper import compute

            SCALE = 10

            def process(x):
                return compute(x) + SCALE
            """,
        )
        func = _load_function_with_sys_path(tmp_path, mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)

        # Without exclusion: import IS included
        context_full = extract_module_context(func, source)
        assert "from helper import compute" in context_full
        assert "SCALE = 10" in context_full

        # With exclusion: import for 'compute' is dropped, SCALE remains
        context_excluded = extract_module_context(
            func, source, exclude_names={"compute"}
        )
        assert "from helper import compute" not in context_excluded
        assert "SCALE = 10" in context_excluded

    def test_excluded_names_partial_import_still_included(self, tmp_path):
        """Import providing both excluded and needed names is still included."""
        _write_module(
            tmp_path,
            "helpers.py",
            """\
            def compute(x): return x * 2
            def validate(x): return x > 0
            """,
        )
        mod_path = _write_module(
            tmp_path,
            "main.py",
            """\
            from helpers import compute, validate

            def process(x):
                if validate(x):
                    return compute(x)
                return 0
            """,
        )
        func = _load_function_with_sys_path(tmp_path, mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)

        # Only 'compute' excluded; 'validate' still needed → import stays
        context = extract_module_context(func, source, exclude_names={"compute"})
        assert "from helpers import" in context

    def test_excluded_names_default_empty(self, tmp_path):
        """Default behavior unchanged when exclude_names not provided."""
        mod_path = _write_module(
            tmp_path,
            "mod.py",
            """\
            SCALE = 5

            def process(x):
                return x * SCALE
            """,
        )
        func = _load_function_from_module(mod_path, "process")

        from runpod_flash.stubs.module_context import extract_module_context
        from runpod_flash.stubs.live_serverless import get_function_source

        source, _ = get_function_source(func)
        context = extract_module_context(func, source)

        assert "SCALE = 5" in context
