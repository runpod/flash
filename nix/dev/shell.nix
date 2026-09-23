#
# nix/dev/shell.nix — runpod-flash
#
# The `nix develop` environment. Provides Python 3.14 with flash's full
# dependency + test graph (via ../python/env.nix) and the quality toolchain,
# plus a `flash-help` banner and `check-*` helpers that mirror the Makefile
# targets.
#
# Everything comes from Nix. There is no `uv sync` and no virtualenv to
# materialize — the interpreter on PATH already imports `runpod_flash` (from
# ./src) and every dependency, so `pytest`/`mypy` run directly.
#
# The `check-*` helpers and the help table are BOTH generated from the single
# command list in ./commands.nix, so that list is written exactly once.
#
{
  pkgs,
  lib,
  pythonEnv,
}:
let
  commands = import ./commands.nix;

  # The dev-shell toolchain: the interpreter env (flash's deps + the pytest/mypy
  # toolchain) plus the source-only static-analysis binaries. Tools come
  # straight from the flake.lock-pinned nixpkgs.
  devPackages = [
    pythonEnv
    pkgs.ruff
    pkgs.bandit
    pkgs.shellcheck
    pkgs.nixfmt
    pkgs.git
  ];

  # Left-justify a helper name into a fixed column so the help table lines up.
  pad =
    s:
    let
      n = 17 - lib.stringLength s;
    in
    s + lib.concatStrings (lib.genList (_: " ") n);

  # A shell function per command, plus the composite `check-all` over the keys.
  funcDefs = lib.concatStringsSep "\n  " (
    lib.mapAttrsToList (name: cmd: "${name}() { ${cmd}; }") commands
  );
  checkAllChain = lib.concatStringsSep " && " (lib.attrNames commands);

  # The help banner, assembled line-by-line (no heredoc indentation pitfalls).
  helpRows = lib.mapAttrsToList (name: cmd: "      ${pad name}${cmd}") commands;
  banner = lib.concatStringsSep "\n" (
    [
      ""
      "    flash dev shell — Python 3.14, all-Nix (no uv, no venv)"
      ""
      "    The interpreter on PATH already has flash + every dependency and the"
      "    test toolchain. runpod_flash imports from ./src directly; run the tools:"
      ""
      "    Checks (run against the project config):"
    ]
    ++ helpRows
    ++ [
      "      ${pad "check-all"}run every check above in order"
      ""
      "    Hermetic gate (sandboxed, no network):"
      "      ${pad "nix flake check"}ruff lint + format, nixfmt, shellcheck, pytest"
      ""
      "    ${pad "flash-help"}show this message"
    ]
  );
in
pkgs.mkShell {
  packages = devPackages;

  shellHook = ''
    # Make the in-tree package importable without an install step (src layout).
    export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"

    ${funcDefs}
    check-all() { ${checkAllChain}; }

    flash-help() { printf '%s\n' ${lib.escapeShellArg banner}; }

    flash-help
  '';
}
