# Release System Documentation

## Overview

The runpod-flash project uses a simple, reliable release automation system built on **Release Please v4** with quality gates and automated PyPI publishing via OIDC trusted publishing.

## Architecture

### Simple Workflow Structure
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   CI Workflow   │    │Release Workflow │    │  PyPI Publish   │
│                 │    │                 │    │                 │
│ • PRs to main   │    │ • Push to main  │    │ • Release PR    │
│ • Quality Gates │    │ • Quality Gates │    │   merged        │
│ • Build Check   │    │ • Release Please│    │ • Build & Sign  │
│ • Block if fail │    │ • Create/Update │    │ • Publish       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Key Components

1. **CI Workflow** - Blocks PRs if quality issues found
2. **Release Please** - Automated semantic versioning and changelog generation
3. **PyPI Publishing** - Secure, verified package publication
4. **Quality Gates** - Multi-version testing with code quality enforcement

## Release Process

### Normal Release Flow

1. **Development**: Create feature branches with conventional commits
2. **Pull Request**: CI runs quality gates, blocks if any issues
3. **Merge to main**: Release workflow runs quality gates + Release Please
4. **Release Please**: Automatically creates/updates release PR when ready
5. **Review**: Team reviews the automated release PR
6. **Merge Release PR**: Triggers publication pipeline
7. **PyPI Publication**: Automated build, sign, and publish

### Conventional Commits

The system uses conventional commits for automated versioning:

```bash
# Feature (minor version bump)
feat: add new GPU resource allocation system

# Bug fix (patch version bump)
fix: resolve memory leak in resource cleanup

# Breaking change (major version bump)
feat!: restructure API for better performance

# Documentation (no version bump)
docs: update API documentation

# Other types: fix, perf, refactor, test, build, ci, chore
```

### Version Bumping Rules

- **Major (1.0.0 → 2.0.0)**: Breaking changes (`feat!:`, `fix!:`, etc.)
- **Minor (1.0.0 → 1.1.0)**: New features (`feat:`)
- **Patch (1.0.0 → 1.0.1)**: Bug fixes (`fix:`)

## Quality Standards

### Code Quality Requirements
- **Linting**: Ruff with strict formatting (blocking)
- **Type Checking**: MyPy analysis (non-blocking, for development feedback)
- **Testing**: Full test suite execution (blocking)
- **Build**: Package build and verification (blocking)

### Build Requirements
- **Python Versions**: 3.10, 3.11, 3.12
- **Package Verification**: Twine check and Sigstore signing
- **OIDC Publishing**: Trusted publishing without API keys

## Configuration Files

### `.release-please-config.json`
```json
{
  "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "packages": {
    ".": {
      "release-type": "python",
      "extra-files": [
        {
          "type": "toml", 
          "path": "pyproject.toml",
          "jsonpath": "$.project.version"
        }
      ]
    }
  },
  "pull-request-title-pattern": "chore: release ${version}",
  "pull-request-header": "Release Please automated release PR",
  "separate-pull-requests": false,
  "changelog-sections": [
    {
      "type": "feat",
      "section": "Features",
      "hidden": false
    },
    {
      "type": "fix", 
      "section": "Bug Fixes",
      "hidden": false
    }
  ]
}
```

### `.release-please-manifest.json`
```json
{
  ".": "0.5.2"
}
```

## Workflows

### CI Workflow (`.github/workflows/ci.yml`)
- **Triggers**: Pull requests and pushes to main
- **Purpose**: Quality gates and build verification
- **Jobs**: 
  - Quality gates (multi-Python testing)
  - Build package verification

### Release Workflow (`.github/workflows/release-please.yml`)
- **Triggers**: Push to main only
- **Purpose**: Release orchestration and PyPI publishing
- **Jobs**:
  - Quality gates (same as CI)
  - Release Please (create/update release PRs)
  - PyPI publishing (only when release created)

## Troubleshooting

### Common Issues

#### Release PR Not Created
**Symptoms**: No automatic release PR after feature merges
**Causes**: 
- No conventional commits since last release
- All changes are hidden types (`chore`, `test`, `build`, `ci`)

**Solutions**:
1. Check commit history for conventional commit format
2. Verify `.release-please-config.json` syntax
3. Review `.release-please-manifest.json` for correct version

#### PyPI Publishing Fails
**Symptoms**: Quality gates pass but PyPI publishing fails
**Causes**:
- OIDC configuration issues
- Package build failures
- Version conflicts

**Solutions**:
1. Check OIDC trusted publishing configuration
2. Verify package build locally: `uv build && uv run twine check dist/*`
3. Check PyPI status and version conflicts

#### Quality Gate Failures
**Symptoms**: CI or Release workflow fails on quality checks
**Causes**:
- Linting/formatting issues
- Test failures
- Build problems

**Solutions**:
1. Run checks locally: `make check`
2. Fix failing tests and linting issues
3. Ensure all dependencies are properly installed

## Best Practices

### For Developers
1. **Always use conventional commits** for proper version detection
2. **Run quality checks locally** before pushing changes
3. **Review release PRs carefully** before merging
4. **Monitor CI status** and address failures promptly

### For Maintainers
1. **Keep workflows simple** - avoid complex conditionals and overrides
2. **Monitor release automation** for proper functionality
3. **Update dependencies regularly** to avoid security issues
4. **Document any configuration changes**

## Security Considerations

### OIDC Trusted Publishing
- No API keys stored in repository
- Automatic token generation for each publish
- Scoped permissions for security

### Signing and Verification
- Packages automatically signed with Sigstore
- Build artifacts verified before publication
- Comprehensive audit trail maintained

### Dependency Management
- Dependency pinning for reproducible builds  
- Regular security updates
- Quality gates prevent vulnerable code from being released

## Emergency Procedures

### If Release Please Breaks
1. Check recent commits for conventional commit format
2. Verify configuration files are valid JSON
3. Check GitHub release tags match manifest

### If PyPI Publishing Fails
1. Check workflow logs for specific errors
2. Verify OIDC configuration in PyPI
3. Manually build and verify package locally

### If Quality Gates Fail
1. Address the root cause (tests, linting, etc.)
2. Do not bypass quality gates
3. Ensure all changes meet quality standards

## Monitoring

### Success Indicators
- ✅ CI passes on all PRs
- ✅ Release PRs created automatically
- ✅ Packages successfully published to PyPI
- ✅ No manual intervention required

### Failure Points to Watch
- Quality gate failures blocking releases
- Release Please configuration errors
- PyPI publishing authentication issues
- Build artifact generation problems

---

*This release system prioritizes simplicity and reliability over complex features. The goal is a hands-off, automated process that just works.*