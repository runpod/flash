# File-Based Logging

Flash automatically logs CLI activity to local files during development, providing a persistent record of operations for debugging and auditing.

## Overview

File-based logging is enabled by default in local development mode and automatically disabled in deployed containers. Logs are written to daily rotating files with configurable retention.

**Key Features:**
- Automatic daily log rotation at midnight
- Configurable retention period (default: 30 days)
- Same format as console output
- Graceful degradation (continues with stdout-only if file logging fails)
- Zero configuration required (sensible defaults)

## Log Location

By default, logs are written to:

```
.flash/logs/activity.log
```

Rotated logs use date suffixes:

```
.flash/logs/
├── activity.log                    # Current day
├── activity.log.2026-02-11         # Previous days
├── activity.log.2026-02-10
└── activity.log.2026-02-09
```

## Configuration

File-based logging can be customized via environment variables:

### FLASH_FILE_LOGGING_ENABLED

Enable or disable file-based logging.

**Type:** Boolean (true/false)
**Default:** `true`
**Example:**

```bash
# Disable file logging
export FLASH_FILE_LOGGING_ENABLED=false
flash init

# Re-enable file logging
export FLASH_FILE_LOGGING_ENABLED=true
flash build
```

### FLASH_LOG_RETENTION_DAYS

Number of days to retain rotated log files.

**Type:** Integer (minimum: 1)
**Default:** `30`
**Example:**

```bash
# Keep only 7 days of logs
export FLASH_LOG_RETENTION_DAYS=7
flash deploy --preview
```

**Note:** Invalid values (< 1) log a warning and fall back to the default (30 days).

### FLASH_LOG_DIR

Custom directory for log files.

**Type:** String (directory path)
**Default:** `.flash/logs`
**Example:**

```bash
# Use custom log directory
export FLASH_LOG_DIR=/var/log/flash
flash run
```

**Note:** The directory will be created automatically if it doesn't exist.

## Examples

### Disable File Logging

Useful for CI/CD environments or when disk space is limited:

```bash
export FLASH_FILE_LOGGING_ENABLED=false
flash build
flash deploy
```

### Short Retention for Development

Keep only recent logs during active development:

```bash
export FLASH_LOG_RETENTION_DAYS=3
flash run
```

### Custom Log Directory

Store logs in a shared location for team debugging:

```bash
export FLASH_LOG_DIR=/shared/team-logs/flash
flash build
flash test
```

### Combine Multiple Settings

```bash
export FLASH_LOG_RETENTION_DAYS=14
export FLASH_LOG_DIR=~/logs/flash
flash deploy --preview
```

## Log Format

Logs use the same format as console output. The format automatically adjusts based on the `LOG_LEVEL` environment variable:

**INFO level and above (default):**

```
2026-02-12 10:30:45 | INFO  | Building Docker image...
2026-02-12 10:30:50 | WARN  | No GPU resources found
```

**DEBUG level:**

```
2026-02-12 10:30:45 | DEBUG | runpod_flash.cli | build.py:123 | Starting build process
2026-02-12 10:30:46 | DEBUG | runpod_flash.core | scanner.py:45 | Scanning directory: /app
```

Set the log level via:

```bash
export LOG_LEVEL=DEBUG
flash build
```

## Behavior in Deployed Containers

File-based logging is **automatically disabled** in deployed Runpod containers, regardless of environment variable settings. This prevents unnecessary disk I/O and storage usage in production.

Only stdout/stderr logging is active in deployed environments, which is automatically captured by Runpod's logging infrastructure.

## Troubleshooting

### Logs Not Being Created

**Symptom:** No log files appear in `.flash/logs/`

**Possible causes:**

1. File logging is disabled:
   ```bash
   # Check current setting
   echo $FLASH_FILE_LOGGING_ENABLED

   # Enable if needed
   export FLASH_FILE_LOGGING_ENABLED=true
   ```

2. Running in deployed container (expected behavior)

3. Directory creation failed (check permissions)

### Disk Space Issues

**Symptom:** Logs consuming too much disk space

**Solution:** Reduce retention period:

```bash
export FLASH_LOG_RETENTION_DAYS=7
```

Or disable file logging:

```bash
export FLASH_FILE_LOGGING_ENABLED=false
```

### Log Directory Not Writable

**Symptom:** Warning message "Could not set up file logging"

**Solution:**

1. Check directory permissions:
   ```bash
   ls -ld .flash/logs
   ```

2. Use a writable directory:
   ```bash
   export FLASH_LOG_DIR=/tmp/flash-logs
   ```

3. If warnings persist, CLI will continue with stdout-only logging (graceful degradation)

### Old Logs Not Rotating

**Symptom:** Logs older than retention period still present

**Explanation:** Python's `TimedRotatingFileHandler` only deletes old logs when new rotation occurs. If you haven't run Flash commands recently, old logs remain until the next rotation at midnight.

**Solution:** Old logs will be cleaned up automatically at the next midnight rotation. To force cleanup:

```bash
# Manually remove old logs
find .flash/logs -name "activity.log.*" -mtime +30 -delete
```

## Related Configuration

- `LOG_LEVEL`: Controls console and file log verbosity (DEBUG, INFO, WARNING, ERROR)
- See [flash-run.md](./flash-run.md) for environment variable usage in local development
- See [flash-build.md](./flash-build.md) for build-time logging behavior

## Summary

File-based logging provides automatic, configurable activity logging for Flash CLI operations:

| Setting | Default | Description |
|---------|---------|-------------|
| `FLASH_FILE_LOGGING_ENABLED` | `true` | Enable/disable file logging |
| `FLASH_LOG_RETENTION_DAYS` | `30` | Days to retain rotated logs |
| `FLASH_LOG_DIR` | `.flash/logs` | Log file directory |

All settings are optional and override-only. Default behavior is production-ready and requires no configuration.
