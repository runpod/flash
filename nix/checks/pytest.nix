#
# nix/checks/pytest.nix — runpod-flash
#
# Hermetic unit-test gate: runs the `tests/unit` suite against `pythonEnv`
# (flash's deps + pytest toolchain, all from Nix). No uv, no venv.
#
# Faithful to the uv-based CI recipe (`make ci-quality-github`), which matters
# for correctness, not just parity:
#   - Two passes. Non-serial tests run with `-n auto`; serial tests run in a
#     separate pass. The `ResourceManager` singleton keeps class-level mutable
#     state, so serial tests must not share a worker/process with the rest —
#     mixing them makes routing tests see polluted state and fail spuriously.
#   - `-m "not integration"`. Integration tests hit live Runpod; the sandbox
#     has no network.
#   - addopts overridden to "" to drop the repo's `--cov-fail-under=65` gate,
#     which is calibrated for the full suite (coverage is still measured in the
#     dev shell via `check-tests`).
#
# `cacert` + SSL_CERT_FILE give the sandbox a CA bundle so tests that build an
# httpx client (which initializes an SSL context) don't hit FileNotFoundError.
#
{
  mkCheck,
  pkgs,
  pythonEnv,
  src,
}:
mkCheck {
  name = "flash-pytest";
  inherit src;
  runtimeInputs = [
    pythonEnv
    pkgs.cacert
  ];
  text = ''
    export PYTHONPATH="$PWD/src"
    export HOME="$TMPDIR"
    export SSL_CERT_FILE="${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"

    # Pass 1: everything except serial-only tests, parallelized.
    python -m pytest tests/unit -m "not serial and not integration" \
      -o addopts="" -p no:cacheprovider -n auto -q

    # Pass 2: serial tests, in their own process (no xdist).
    python -m pytest tests/unit -m "serial and not integration" \
      -o addopts="" -p no:cacheprovider -q
  '';
}
