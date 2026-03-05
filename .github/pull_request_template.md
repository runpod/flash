> NOTE: delete contents after reading below...

# Guidelines

This guide applies to commit messages and pull request titles.

Please use [Conventional Commits](https://www.conventionalcommits.org/) specification for more details.

### 🚀 Quick Reference

**Most Common Patterns:**
- New functionality: `feat: add new feature`
- Bug fixes: `fix: resolve issue with X`
- Documentation: `docs: update/add documentation`
- Refactoring: `refactor: improve code structure`
- Performance: `perf: optimize X for better performance`

### 💥 Breaking Changes
For breaking changes, use either:
1. Add `!` after the type: `feat!: redesign API interface`
2. Add `BREAKING CHANGE:` in the footer:
   ```
   feat: add new authentication method
   
   BREAKING CHANGE: The old auth method is no longer supported
   ```

### 🎯 Examples

**Good Examples ✅**
```
feat: add CPU endpoint support
fix: resolve memory leak in resource cleanup
perf: optimize GraphQL query batching
docs: update installation instructions
refactor: simplify resource manager singleton
test: add unit tests for remote execution
```

**Bad Examples ❌**
```
Update readme                  # Missing type
feat add new feature           # Missing colon
Fix: bug in client             # Incorrect capitalization
feat(client) add CPU support   # Missing colon
```

### 🔄 Version Impact

| Commit Type | Version Bump | Appears in Changelog | Example |
|-------------|-------------|-------------------|---------|
| `feat` | **Minor** (0.4.2 → 0.5.0) | ✅ Features | `feat: add batch processing` |
| `fix` | **Patch** (0.4.2 → 0.4.3) | ✅ Bug Fixes | `fix: handle connection timeout` |
| `perf` | **Patch** (0.4.2 → 0.4.3) | ✅ Performance | `perf: optimize memory usage` |
| `refactor` | **Patch** (0.4.2 → 0.4.3) | ✅ Code Refactoring | `refactor: simplify error handling` |
| `docs` | **Patch** (0.4.2 → 0.4.3) | ✅ Documentation | `docs: add GPU configuration guide` |
| `style` | **Patch** (0.4.2 → 0.4.3) | ❌ Hidden | `style: fix linting issues` |
| `test` | **Patch** (0.4.2 → 0.4.3) | ❌ Hidden | `test: add integration tests` |
| `build` | **Patch** (0.4.2 → 0.4.3) | ❌ Hidden | `build: update dependencies` |
| `ci` | **Patch** (0.4.2 → 0.4.3) | ❌ Hidden | `ci: add Python 3.13 support` |
| `chore` | **Patch** (0.4.2 → 0.4.3) | ❌ Hidden | `chore: remove unused imports` |
