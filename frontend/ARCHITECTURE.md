# Architecture

## Layers

```
src/
  app/           AppShell layout and UI-only Zustand (uiStore)
  domain/        Simulation protocol, WebSocket client, playback store
  features/      React UI by section of the control panel. Today only workbench/ exists
                 (connection, controls, metrics, monitor, scene). campaigns/, cluster/,
                 observe/ and results/ are added by later phases.
  language/      Lezer grammar for .problem files
```

## Data flow

```mermaid
flowchart LR
  Backend[(Python WS backend)]
  WS[BackendWsClient]
  Protocol[protocol.ts Zod]
  Playback[playbackStore]
  Scene[SceneCanvas R3F]
  Backend --> WS --> Protocol --> Playback --> Scene
```

## WebSocket lifecycle

1. **Connect**: `BackendWsClient` to `VITE_WS_URL`
2. **Generate scene**: `generate_scene` with functional spec + domain YAML -> `generated_scene`
3. **Load scenario**: `load_scenario_file` -> `preview_trajectory_chunk`(s)
   A bare scene loads as its initial scene only (`initial_state` with trajectory length 0); trajectories come from the trajectory generator (`generate_trajectories` with `generator` monitor_driven_rrt or straight), and the simulation workflow refuses to initialize without them.
4. **Initialize simulation**: `initialize_simulation` -> `initial_state`
5. **Run**: `start_simulation` -> `simulation_trajectory_chunk`(s) and live `frame` pushes

Preview and simulation trajectories are stored separately in `playbackStore` for side-by-side analysis.

## Performance

Large trajectory chunks may be merged in a **Web Worker** (`mergeFrames.worker.ts`) before updating the store. Playback uses **requestAnimationFrame** for smooth time advancement.
