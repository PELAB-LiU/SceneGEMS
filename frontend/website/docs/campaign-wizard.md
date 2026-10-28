---
sidebar_position: 7
title: Campaign wizard
---

# Campaign wizard

The Campaigns section defines and starts campaigns. A campaign runs a consecutive part of the chain scene generation, trajectory generation and simulation, with an optional monitor after each step. The wizard walks through the choices and checks the finished config on the master before it creates the campaign. Your entries are kept in this browser until the campaign is created or you discard them.

## Pages

The wizard shows only the pages the chosen steps need.

| Page | Shown when | What it holds |
|------|------------|---------------|
| Steps | always | The campaign's name and description, the first and the last step, and the monitor after scene generation and after trajectory generation |
| Input | always | What the first step starts from: catalog classes and scenario files, scenes, or trajectories |
| Domain | always | The master's domain content or customized COLREGS constants, vessel types and obstacle types. The scene generation timeout and the low TCPA option appear only with scene generation |
| Trajectories | trajectory generation is a step | The trajectory generator and its parameters |
| Runs | simulation is a step | The simulation runs: stack, environment, seed, repeats and monitor |
| Resources | always | The machines the campaign may use, with the needs of the chosen steps checked against them. Only the queues of the steps that run are listed |
| Policy | always | Retention, frames, seed and stop conditions |
| Review | always | The generated YAML, the master's check of it and the buttons that create the campaign |

## Steps

Choose **Start with** and **Stop after**. The steps in between run too, so the part is always consecutive: scene generation alone, scene generation and trajectory generation, all three, trajectory generation alone or with simulation, or simulation alone. A step that is not chosen hides its pages and writes nothing into the config.

| Step | Monitor choice |
|------|----------------|
| Scene generation | No monitor, or the post hoc monitor, which judges each generated scene as a one-scene log (the initial situation) |
| Trajectory generation | No monitor, or the post hoc monitor, which judges the planned trajectories |
| Simulation | Set per run on the Runs page: post hoc, live or none, as before |

Changing the first step removes chosen input items that do not fit it, such as scenes when the campaign now starts with simulation.

## Input

The Input page depends on the first step.

### Scene generation

- **Catalog classes**: pick folders, patterns or classes from the master's catalog, each scope entry with a quota and a failure budget.
- **Functional scenario files**: add your own functional scenario files (`.problem` files). Each file is uploaded to the master when you pick it and becomes a class of its own named `scenario/<name>`, with a quota and a failure budget. Give each file a name without a slash; names must differ.

Use either or both. Scope entries without classes are ignored while there are scenario files.

### Trajectory generation and simulation

A campaign that starts with trajectory generation takes **scenes**. One that starts with simulation takes **trajectories**. Each item is one case. Take them from Campaign History, from files, or both.

- **From Campaign History**: choose an entry, then a step of it (the scenes of scene generation, or the planned trajectories of trajectory generation and the recorded trajectories of a simulation run), then add outputs one by one, the outputs shown, or every output of the step (the first 1000 when there are more). Outputs the step dropped or found invalid cannot be added. Each item keeps a link to its source, so Campaign History shows what the campaign was made from.
- **From files**: scene and trajectory files must be JSON. Each file is uploaded to the master when you pick it and keeps the file name as its source.

Items have a name you can change. Remove items from the chosen list at any time.

### Uploads expire

The master keeps an uploaded file for 24 hours unless a campaign uses it. A campaign created with the file keeps it for as long as the campaign exists. The wizard shows how long each upload has left and reports an upload that expired, because a config that refers to a deleted file is refused. Upload the file again in that case. Outputs taken from Campaign History are kept by the master with their entry and do not expire.

## Review and create

The review step checks the config on the master as soon as it is complete and has stopped changing. Reasons the master gives are listed with the page and the entry they belong to, such as a scenario file or an input item that no longer exists on the master. **Create paused** stores the campaign without starting it. **Create and start** also needs a usable machine for every job the steps need; the Resources page lists what is missing. The campaign appears in Campaign History with the kind campaign and the origin wizard.

A draft saved by an earlier version of the wizard opens as a campaign with all three steps, on the Input page in place of the former Scope page.
