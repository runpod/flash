# Flash Apps & Environments

## Overview
Flash apps are the top-level packaging unit for Flash projects. Each app tracks the source builds you've uploaded, the deployment environments that consume those builds, and metadata needed by the CLI to orchestrate everything on RunPod. Environments sit under an app and describe a concrete runtime surface (workers, endpoints, network volumes) that can be updated independently.

## Key Concepts
- **Flash App**: Logical container created once per project. It owns the ID used for uploads, holds references to environments/builds, and backs the `flash app` CLI.
- **Flash Environment**: Named deployment target under an app. Environments point to the currently active build, maintain endpoint + network volume associations, and power the `flash deploy` CLI.
- **Flash Build**: Tarball artifacts uploaded per app (.flash/artifact.tar.gz). Used for extracting manifest and deploying to endpoints during resource provisioning.

## Lifecycle
1. **App Discovery/Hydration**
   - `FlashApp` instances call `_hydrate()` to fetch or create the remote app ID before doing any work.
   - CLI helpers (`flash app ...`, `flash deploy ...`) call `discover_flash_project()` when `--app` is omitted, then hydrate via `FlashApp.from_name` or eager constructors.
2. **Environment Creation**
   - `flash env create <env>` calls `FlashApp.create_environment_and_app` to ensure the parent app exists and to create the environment in a single async transaction.
   - Once created, the CLI prints both a confirmation panel and a table summarizing the environment metadata so operators can confirm IDs/states.
3. **Build Upload & Resource Provisioning**
   - `flash build` generates `.flash/artifact.tar.gz` artifacts containing source code and flash_manifest.json. `flash deploy --env <env>` uploads the archive and provisions all resources upfront before environment activation, extracting the manifest on each resource during boot.
4. **Inspection & Operations**
   - `flash app list/get` surface app-level metadata: environment counts, build history, IDs.
   - `flash env list/get` zoom into environment state, showing associated endpoints and volumes, while `flash env delete` undeploys associated resources before deleting the environment (aborting on failures) with confirmation prompts.

## Operational Notes
- Flash app CLI entrypoint wraps async helpers with `asyncio.run`, so tests patch that boundary and the shared Rich `console` to keep assertions deterministic.
- Environment deletion requires confirmation because the API call is irreversible. The CLI renders a warning `Panel` with the app/env IDs before prompting.
