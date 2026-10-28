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
| Generate scene / Generate N scenes | Runs the scene generation as a workbench entry on the active cluster (see [Workbench pages and entries](./workbench-pages)). A batch is one entry with a case per scenario, submitted at once, so every free slot is used and the rest wait in the queue. Requires complete domain config, a functional spec and a machine that offers scene generation. |
| Stop | Stops the generation and its entry |
| Next: Trajectory Generation | Makes the shown valid scene the input of the Trajectory Generation page and opens it |
| Load Scenario File… | Shows a scenario file's scene and judges it with the cluster's monitor; the scene is no entry |
| Load for Simulation | Makes a scenario file with full trajectories the input of the Simulation page (requires the connected gateway) |
| Export Scenario | Downloads the current visualized scene as JSON |

Status lines show the scenario the page generates from, the entry the page shows, and what the cluster offers (slots on machines, free). Without a machine that runs scene generation, the toolbar says why and generation stays off. A generated scene is judged by the scene monitor when a machine offers monitoring; its verdicts are shown with the scene.

Clicking a batch result shows that case of the batch entry.
