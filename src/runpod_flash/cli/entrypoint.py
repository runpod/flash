"""Thin CLI entrypoint that catches corrupted credentials at import time.

The runpod package reads ~/.runpod/config.toml at import time (in its
__init__.py). If that file contains invalid TOML, the import raises a
TOMLDecodeError before any Flash error handling can run. This wrapper
catches that and surfaces a clean error message.
"""

import sys


def main() -> None:
    """Entry point for the ``flash`` console script."""
    try:
        from runpod_flash.cli.main import app
    except ValueError as exc:
        # TOML decode errors from toml/tomli/tomllib are ValueError subclasses.
        # The runpod package calls a TOML loader at import time; a corrupted
        # ~/.runpod/config.toml triggers this before Flash code executes.
        exc_type = type(exc)
        exc_module = getattr(exc_type, "__module__", "").lower()
        is_toml_decode_error = exc_type.__name__ == "TOMLDecodeError" and (
            exc_module.startswith("toml")
            or exc_module.startswith("tomli")
            or exc_module.startswith("tomllib")
        )
        if is_toml_decode_error:
            print(
                "Error: ~/.runpod/config.toml is corrupted and cannot be parsed.\n"
                "Run 'flash login' to re-authenticate, or delete the file and retry.",
                file=sys.stderr,
            )
            raise SystemExit(1) from None
        raise

    app()
