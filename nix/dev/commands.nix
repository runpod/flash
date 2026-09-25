#
# nix/dev/commands.nix — runpod-flash
#
# Single source of truth for the dev-shell `check-*` helpers. Each entry maps a
# helper name to the exact command it runs against the project's own config.
# ./shell.nix renders this attrset into BOTH the shell functions and the help
# banner, so the command list is written exactly once (the composite `check-all`
# is derived from these keys, and so lives in ./shell.nix).
#
{
  check-format = "ruff format --check .";
  check-lint = "ruff check .";
  check-types = "mypy .";
  check-security = ''bandit -r src/ -ll -x "**/tests/**"'';
  check-tests = "pytest tests/ -n auto";
}
