# flash login

Authenticate with Runpod via browser and save your API key locally.

## Overview

The `flash login` command opens a browser-based authentication flow with Runpod. On approval, your API key is saved to `~/.runpod/config.toml` -- the same credentials file used by runpod-python. This is the recommended way to authenticate for local development.

### When to use this command
- First-time setup after installing Flash
- Switching between Runpod accounts
- Re-authenticating after revoking an API key

## Usage

```bash
flash login [OPTIONS]
```

## Options

- `--force`: Re-authenticate even if valid credentials already exist
- `--no-open`: Print the auth URL instead of opening the browser
- `--timeout`: Maximum wait time in seconds (default: 600)

## Examples

```bash
# Standard login (opens browser)
flash login

# Re-authenticate with a different account
flash login --force

# Login on a headless server (copy URL manually)
flash login --no-open
```

## How It Works

1. Flash creates an auth request and prints a URL
2. You approve the request in your browser at runpod.io
3. Flash polls for approval, then saves the API key to `~/.runpod/config.toml`
4. File permissions are set to `0600` (owner read/write only)

If you already have valid credentials on file, `flash login` detects this and exits early. Use `--force` to bypass this check and re-authenticate.

## Credential Resolution Order

Flash checks for an API key in this order, using the first one found:

| Priority | Source | How to set |
|----------|--------|------------|
| 1 | `RUNPOD_API_KEY` environment variable | `export RUNPOD_API_KEY=your_key` |
| 2 | `RUNPOD_API_KEY` in `.env` file | `echo "RUNPOD_API_KEY=your_key" >> .env` |
| 3 | `~/.runpod/config.toml` credentials file | `flash login` |

The `.env` file is loaded into the environment automatically via `python-dotenv` at startup, so priorities 1 and 2 both resolve through `os.getenv("RUNPOD_API_KEY")`. An explicitly exported shell variable takes precedence over a `.env` value.

### Scope of `flash login`

`flash login` manages **only the credentials file** (priority 3). It does not read or write environment variables or `.env` files. The pre-flight check that detects existing credentials also only checks the file -- if your key comes from an env var or `.env`, `flash login` will not see it and will proceed with the browser flow.

This separation means you can use `flash login` for persistent, machine-wide credentials while still overriding per-project or per-session with env vars.

## Credentials File Format

Flash delegates credential storage to runpod-python. The file uses TOML with a `[default]` profile:

```toml
[default]
api_key = "your_api_key_here"
```

**Location:** `~/.runpod/config.toml` (shared with runpod-python CLI)

This means `runpod config` and `flash login` write to the same file. A key saved by either tool is visible to both.

## Troubleshooting

### "Already logged in" but I want to re-authenticate

```bash
flash login --force
```

### Login works but `flash deploy` says key is missing

Check which source your key is coming from:

```bash
# Is the env var set?
echo $RUNPOD_API_KEY

# Is there a .env file?
cat .env | grep RUNPOD_API_KEY

# Is the credentials file present?
cat ~/.runpod/config.toml
```

If the env var or `.env` has a stale key, it takes precedence over the credentials file. Remove or update it.

### Headless server / SSH session

Use `--no-open` to get a URL you can copy to another machine's browser:

```bash
flash login --no-open
```

### Timeout during login

The default timeout is 10 minutes. Increase it for slow connections:

```bash
flash login --timeout 1200
```
