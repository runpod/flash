# Testing Guide

## Quick Reference

```bash
# Development (fast, incomplete - bypasses packaging)
uv pip install -e .

# Development (complete - includes packaging validation)
# Build wheel and install it to test CLI from anywhere
cd /path/to/runpod_flash && uv build && pip install dist/runpod_flash-*.whl --force-reinstall
cd /tmp && flash init test_project

# Unit tests
make test-unit

# Code quality
make quality-check

# Wheel validation (required before release)
make validate-wheel
```

## Development vs Release Testing

| Test Type | Command | Use Case | Catches Packaging Issues |
|-----------|---------|----------|--------------------------|
| Editable install | `uv pip install -e .` | Fast iteration during development | No |
| Wheel install | `uv build && pip install dist/*.whl --force-reinstall` | Test CLI with full packaging | Yes |
| Full validation | `make validate-wheel` | Pre-release validation (builds, installs, tests) | Yes |
| Unit tests | `make test-unit` | Test code logic | N/A |

## Known Issues

**Editable installs hide packaging problems**
- Files read directly from source, not from `[tool.setuptools.package-data]`
- Always run `make validate-wheel` before releasing

**Coverage threshold failures**
- Use `--no-cov` flag for focused testing: `uv run pytest tests/unit/test_skeleton.py -v --no-cov`
- Or test specific module: `uv run pytest --cov=src/runpod_flash/cli/utils/skeleton`

**Hidden files require explicit glob patterns**
- Pattern `**/.*` needed in pyproject.toml to include `.env`, `.gitignore`
- Verify with: `unzip -l dist/runpod_flash-*.whl | grep skeleton_template`

## Pre-Release Checklist

- [ ] `make test-unit` - All tests pass
- [ ] `make quality-check` - Formatting, linting, coverage pass
- [ ] `make validate-wheel` - Wheel packaging validated
- [ ] Test `flash init` in-place and with project name

## CI/CD

Wheel validation runs automatically on all PRs and pushes to main via [.github/workflows/ci.yml](.github/workflows/ci.yml).
