<!--
  nix/README.md — runpod-flash
  Guide to the Nix flake: installing Nix, running flash straight from GitHub,
  the dev shell, and the hermetic checks. Linked from the top-level README.
-->

# Flash — Nix flake

This document explains how to use **[Nix](https://nixos.org)** with **runpod-flash**: how to run the `flash` CLI straight from GitHub with a single command, and how to get a reproducible development environment.

## Why Nix?

- **Fastest way to try flash** — one command runs the CLI with the right Python and every dependency pinned, without touching your system Python or creating a virtualenv.
- **Reproducible dev environment** — every contributor gets the identical toolchain (Python 3.14, ruff, mypy, bandit, shellcheck), so "works on my machine" stops being a thing.
- **Hermetic checks** — `nix flake check` runs the lint/format/test gate in an isolated sandbox that doesn't depend on what's installed locally.

> **The Nix path is optional and self-contained.** It's built entirely from Nix — no `uv`, no virtualenv. If you'd rather not use Nix, ignore this directory: the `uv` + `pip`/PyPI workflow (`make dev`, `uv sync`, `make test`, `make build`) is unchanged and remains the primary path. Nix is here only to help those who want it.

Nix is a package manager for Linux and macOS that gives **reproducible, isolated** environments. It tracks every dependency by content hash, so the versions you get are exactly the versions the flake pins in `flake.lock`. Nothing is installed into `/usr` or your global environment — everything lives in `/nix/store` and disappears when you leave the shell.

> **Platforms:** the dev shell, checks, and packaged CLI are verified on `x86_64-linux`, `aarch64-darwin` (Apple Silicon), and `aarch64-linux` (including the Raspberry Pi 5). Other systems build from the same definitions. Note the flake's own derivations (`runpod-flash`, `runpod`, `tqdm-loggable`) aren't published to a binary cache, so Nix builds those locally; their upstream nixpkgs dependencies still come from the public binary cache (`cache.nixos.org`).

---

## 1. Install Nix

If you already have Nix with flakes enabled, skip to [section 2](#2-run-flash-straight-from-github).

Choose a **multi-user** (daemon) or **single-user** install:

- **Multi-user** (recommended on most systems) — [docs](https://nix.dev/manual/nix/2.24/installation/#multi-user)
  ```bash
  bash <(curl -L https://nixos.org/nix/install) --daemon
  ```
- **Single-user** — [docs](https://nix.dev/manual/nix/2.24/installation/#single-user)
  ```bash
  bash <(curl -L https://nixos.org/nix/install) --no-daemon
  ```

### Video walkthroughs

| Platform | Video |
|----------|-------|
| Ubuntu | [Installing Nix on Ubuntu](https://youtu.be/cb7BBZLhuUY) |
| Fedora | [Installing Nix on Fedora](https://youtu.be/RvaTxMa4IiY) |

### Enable flakes

Flakes are still an opt-in feature. Enable them permanently:

```bash
test -d /etc/nix || sudo mkdir /etc/nix
echo 'experimental-features = nix-command flakes' | sudo tee -a /etc/nix/nix.conf
```

Or enable them per-command without editing config:

```bash
nix --extra-experimental-features 'nix-command flakes' run github:runpod/flash -- --help
```

See the [Nix flakes wiki](https://nixos.wiki/wiki/flakes) for more.

> **First run** downloads and builds dependencies (a few minutes). Later runs reuse the `/nix/store` cache and are effectively instant.

---

## 2. Run flash straight from GitHub

No clone required — reference the repository directly:

```bash
# Run the CLI without installing anything
nix run github:runpod/flash -- --help

# Install flash onto your PATH
nix profile install github:runpod/flash

# Drop into the full dev shell
nix develop github:runpod/flash

# Run the hermetic checks
nix flake check github:runpod/flash
```

The bare `github:runpod/flash` reference resolves to the repository's **default branch**. You can pin a branch, tag, or commit instead:

```bash
nix run github:runpod/flash/v1.19.0 -- --help     # a tag
nix run github:runpod/flash/<commit-sha> -- --help # an exact commit
```

Because the flake carries its own pinned `flake.lock`, these commands are reproducible regardless of your local Nix channels.

---

## 3. Local development

From a clone of the repo:

```bash
nix develop        # dev shell with the full toolchain
nix flake check    # ruff lint + format, nixfmt, shellcheck, pytest (hermetic)
nix build .#default   # build the flash CLI -> ./result/bin/flash
nix run   .#default -- --help
```

### Dev shell helpers

Entering `nix develop` prints a banner (`flash-help` re-prints it). The shell provides Python 3.14 with flash's full dependency + test graph already importable — **no `uv sync`, no virtualenv to materialize.** `runpod_flash` imports directly from `./src`, so the helpers just run the tools:

| Helper | Runs |
|--------|------|
| `check-format`   | `ruff format --check .` |
| `check-lint`     | `ruff check .` |
| `check-types`    | `mypy .` |
| `check-security` | `bandit -r src/ -ll -x "**/tests/**"` |
| `check-tests`    | `pytest tests/ -n auto` |
| `check-all`      | all of the above, in order |

---

## 4. What's in here

The flake is intentionally modular and hierarchical — a thin `flake.nix` orchestrator at the repo root delegates to the files under `nix/`, grouped by concern. Modules are wired with plain `import ./x.nix { inherit … }` so every argument is visible at its call site:

| Path | Purpose |
|------|---------|
| `../flake.nix` | Entry point: inputs + `import ./nix`; exposes `packages`, `devShells`, `checks`, `apps` |
| `default.nix` | Per-system aggregator; pins Python 3.14 and wires the modules together |
| `python/deps.nix` | **Single source of truth** for flash's runtime deps (mirrors `[project.dependencies]`); consumed by both the env and the CLI |
| `python/env.nix` | The Python environment — the runtime deps + the pytest/mypy toolchain, all from Nix. Shared by the dev shell and the pytest check |
| `packages/flash.nix` | `packages.default` / `apps.default` — the flash CLI (version read from `pyproject.toml`) |
| `packages/runpod.nix`, `packages/tqdm-loggable.nix` | Runtime deps not yet in nixpkgs, built from PyPI |
| `dev/shell.nix` | `nix develop` shell + the generated `check-*` helpers |
| `dev/commands.nix` | Single source for the `check-*` command list (shell functions + help banner are generated from it) |
| `checks/default.nix` | The hermetic `nix flake check` gate — fileset scoping + a data-driven table of the simple checks |
| `checks/mk-check.nix` | Helper: each check is a shellchecked `writeShellApplication` + a one-line runner, so the check logic is itself `set -euo pipefail` + shellcheck-verified |
| `checks/pytest.nix` | The one bespoke check — the two-pass `tests/unit` suite |

Standalone tools (`ruff`, `bandit`, `shellcheck`, `nixfmt`, `git`) come straight from the `flake.lock`-pinned nixpkgs; only the Python 3.14 interpreter is pinned explicitly, in `default.nix`.

> **Two lockfiles, pinned independently.** `flake.lock` pins the Nix toolchain (ruff, mypy, …) via nixpkgs, while `uv.lock` pins the same tools for the `uv`/CI path. They're kept in sync by hand — when you bump one (`nix flake update` or `uv lock --upgrade`), check the other so, e.g., the Nix ruff and the CI ruff don't drift into disagreeing lint verdicts.

### The checks

`nix flake check` runs, in a sandbox with no network and no virtualenv:

- **ruff-lint** — `ruff check .`
- **ruff-format** — `ruff format --check .`
- **nixfmt** — every `*.nix` file is formatted
- **shellcheck** — every `*.sh` script passes, with no ignores
- **pytest** — the `tests/unit` suite, against the Nix-built dependency graph

This gate mirrors what the `uv`-based CI actually blocks on (ruff + the unit tests), plus the Nix-native `nixfmt`/`shellcheck`. Three things run from the dev shell rather than the hard gate, matching the project's existing policy:

- **mypy** (`check-types`) — the tree has pre-existing type errors; CI only runs mypy under the aspirational `quality-check-strict`, never as a merge gate.
- **bandit** (`check-security`) — informational, as in the `Makefile`.
- **integration tests** — need live Runpod, which the sandbox denies.

All Nix packages come from [nixpkgs](https://github.com/NixOS/nixpkgs) and are searchable at [search.nixos.org](https://search.nixos.org/packages?channel=unstable).

---

## Troubleshooting

**`error: experimental Nix feature 'nix-command' is disabled`** — flakes aren't enabled; see [Enable flakes](#enable-flakes) above, or prefix the command with `--extra-experimental-features 'nix-command flakes'`.

**`nix run github:...` is slow the first time** — that's the initial download/build; subsequent runs use the `/nix/store` cache.

**Want a newer dependency pin?** — from a clone, run `nix flake update` to refresh `flake.lock`.
