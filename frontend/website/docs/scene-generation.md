---
sidebar_position: 5
title: Scene Generation
---

# Scene Generation

Scene Generation combines a central 3D/nautical canvas with a right sidebar for functional specification editing and a bottom toolbar for generation actions.

## Right sidebar: Functional Scenario Specification

A CodeMirror editor with Refinery `.problem` language support holds the functional scenario specification. Above the editor:

- **Search presets**: Filter the functional model catalog by name
- **Vessel / obstacle filters**: Narrow presets by actor counts
- **Single scene generation** tab: Load one preset, edit inline, load from file, export, or open in [Refinery](https://refinery.services/) (copies spec to clipboard)
- **Batch scene generation** tab: Select multiple presets, visualize individual results, download valid scenes as ZIP, open presets in Refinery

## Scene validity badge

When a scene is displayed, a status badge indicates whether it is *valid* (complies with specification) or *invalid* (generation still in progress).

## Bottom toolbar

| Control | Description |
|---------|-------------|
| Live preview | When checked, streams intermediate visualization frames during generation |
| Timeout (s) | Maximum wait time for scene generation (1–86400 seconds) |
| Generate scene / Generate N scenes | Submits one scene generation job per scene to the active cluster; a batch is submitted at once, so every free slot is used and the rest wait in the queue. Requires complete domain config, a functional spec and a machine that offers scene generation. |
| Stop | Cancels an in-progress generation |
| Load Scenario File… | Import a JSON evaluation/scenario file for visualization |
| Initialize Scenario | Loads the visualized valid scene onto the backend and switches to Simulation (requires connected backend socket) |
| Export Scenario | Downloads the current visualized scene as JSON |

Status lines show the visualized scenario source and what the cluster offers (slots on machines, free). Without a machine that runs scene generation, the toolbar says why and generation stays off.
