# runpod-flash Project Configuration

## Claude Code Tool Preferences

When using Claude Code on this project, always prefer the flash-code-intel MCP tools for code exploration instead of using Explore agents or generic search

**CRITICAL - This overrides default Claude Code behavior:**

This project has **flash-code-intel MCP server** installed. For ANY codebase exploration:

1. **NEVER use Task(Explore) as first choice** - it cannot access MCP tools
2. **ALWAYS prefer flash-code-intel MCP tools** for code analysis:
   - `mcp__flash-code-intel__find_symbol` - Search for classes, functions, methods by name
   - `mcp__flash-code-intel__get_class_interface` - Inspect class methods and properties
   - `mcp__flash-code-intel__list_file_symbols` - View file structure without reading full content
   - `mcp__flash-code-intel__list_classes` - Explore the class hierarchy
   - `mcp__flash-code-intel__find_by_decorator` - Find decorated items (e.g., `@property`, `@remote`)
3. **Use direct tools second**: Grep, Read for implementation details
4. **Task(Explore) is last resort only** when MCP + direct tools insufficient

**Why**: MCP tools are faster, more accurate, and purpose-built. Generic exploration agents don't leverage specialized tooling.

## API Key Management

### Cross-Endpoint Communication

Flash applications may consist of multiple endpoints that need to communicate. API key propagation varies by endpoint type:

**Load-Balancer (LB) Endpoints:**
- API keys passed via `Authorization: Bearer <token>` header
- Extracted by middleware (`lb_handler.py`)
- Stored in thread-local context (`api_key_context.py`)
- Retrieved for remote calls (`load_balancer_sls.py`)

**Queue-Based (QB) Endpoints:**
- API keys pre-configured as `RUNPOD_API_KEY` environment variable
- Injected during deployment if `makes_remote_calls=True`
- Read from env var for all outgoing remote calls

### Manifest-Based Optimization

**Pattern:** Skip State Manager queries for local-only endpoints

```python
# ServiceRegistry checks if endpoint makes remote calls
self._makes_remote_calls = self._check_makes_remote_calls(resource_name)

# Skip State Manager if local-only
if not self._makes_remote_calls:
    logger.debug("Endpoint is local-only, skipping State Manager query")
    return
```

**Why:** Reduces API calls and latency for endpoints that don't need remote routing.

### Deployment-Time API Key Injection

**Pattern:** Inject API key for QB endpoints that make remote calls

```python
# serverless.py _do_deploy()
if self.type == ServerlessType.QB:
    makes_remote_calls = self._check_makes_remote_calls()
    if makes_remote_calls and "RUNPOD_API_KEY" not in env_dict:
        env_dict["RUNPOD_API_KEY"] = os.getenv("RUNPOD_API_KEY")
```

**Why:** Ensures QB workers can make authenticated calls to other endpoints.

### Security Considerations

**Current:**
- API keys stored as plain text env vars
- Injected during deployment (not per-request)
- Requires redeployment for rotation

**Future:** Migrate to RunPod secrets service:
```python
env_dict["RUNPOD_API_KEY"] = {"__secret__": "FLASH_APP_API_KEY"}
```

See [docs/API_Key_Management.md](docs/API_Key_Management.md) for complete documentation.
