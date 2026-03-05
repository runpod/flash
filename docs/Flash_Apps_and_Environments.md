# Flash Apps and Environments

Flash organizes deployments into **apps** and **environments**.

- **App**: A top-level container that groups everything for a single project. Created automatically on first `flash deploy`, or manually with `flash app create`.
- **Environment**: An isolated deployment context within an app (e.g., `dev`, `staging`, `production`). Each environment has its own endpoints, build version, and network volumes.

```
Flash App (my-project)
├── Environment: dev        → endpoints, build v3
├── Environment: staging    → endpoints, build v2
└── Environment: production → endpoints, build v1
```

See [flash app](../src/runpod_flash/cli/docs/flash-app.md) and [flash env](../src/runpod_flash/cli/docs/flash-env.md) for CLI usage.
