#
# nix/default.nix — runpod-flash
#
# Per-system aggregator. Called once per system by ../flake.nix with a
# concrete `pkgs`, `lib`, and repo `src`. Wires the individual modules
# together into the flat outputs a flake expects:
#
#   { packages, devShells, checks, apps }
#
# Flash's Nix path is self-contained: the dev shell, every check (lint, format,
# nixfmt, shellcheck, tests), and the packaged CLI are all built from Nix. There
# is no uv and no PyPI step — a single `pythonEnv` (see ./python/env.nix) backs
# both the dev shell and the pytest check.
#
# Modules are wired with plain `import ./x.nix { inherit … }` so every argument
# is visible at its call site; each module declares exactly the inputs it uses.
#
{
  pkgs,
  lib,
  src,
}:
let
  # The one deliberate version pin — Python 3.14 (project direction). Every other
  # tool comes straight from the flake.lock-pinned nixpkgs (pkgs.ruff, etc.).
  python = pkgs.python314;

  # runpod (and its transitive tqdm-loggable) are not in nixpkgs; built from PyPI.
  runpod = import ./packages/runpod.nix { inherit pkgs lib python; };

  # One interpreter env — flash's runtime deps + the test/typecheck toolchain —
  # shared by the dev shell and the hermetic pytest check.
  pythonEnv = import ./python/env.nix { inherit python runpod; };

  # The packaged flash CLI (packages.default / apps.default).
  flash = import ./packages/flash.nix {
    inherit
      pkgs
      lib
      python
      runpod
      src
      ;
  };

  devShell = import ./dev/shell.nix { inherit pkgs lib pythonEnv; };

  checks = import ./checks {
    inherit
      pkgs
      lib
      src
      pythonEnv
      ;
  };
in
{
  packages = {
    default = flash;
    flash = flash;
    runpod = runpod;
  };

  devShells.default = devShell;

  inherit checks;

  apps.default = {
    type = "app";
    program = "${lib.getExe flash}";
    meta = {
      description = "Run the flash CLI (runpod-flash)";
      mainProgram = "flash";
    };
  };
}
