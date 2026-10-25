# Deployment

Everything needed to build and run SceneGEMS lives here. The repository root keeps two thin wrappers, `./build.sh` and `./start.sh`, that call the scripts in `deploy/scripts/`.

## Layout

| Path | Content |
|------|---------|
| `images/` | One folder per Docker image: `arduagent`, `gazebo`, `sitl`, `mavproxy`, `mqtt_broker`, and the four subsystem images `monitoring`, `scenario_generation`, `scenario_execution`, `trajectory_generation` |
| `images/upstream_pins.env` | Upstream commits and base image digest the Gazebo and SITL images build from; passed as build arguments and written into `org.scenegems.*` image labels. apt and pip packages stay unpinned; their installed versions are recorded in `/etc/scenegems/package_versions` inside both images |
| `master/docker-compose.yml` | The main stack: frontend, MQTT broker, backend, and Postgres for the master's job store (`postgres`, volume `scenegems_postgres_data`) |
| `master/.env.example` | Template of `master/.env` (gitignored), the master's secrets and ports; Compose reads `master/.env` itself. The `postgres` service refuses to start without `POSTGRES_PASSWORD`. Create the tables with `PYTHONPATH=src python -m scenegems_tool.persistence.migrate upgrade head` from `backend/` |
| `scripts/build.sh` | Builds the images, skipping any whose inputs did not change |
| `scripts/start.sh` | Starts the main stack and tails the backend logs |
| `scripts/docker-common.sh` | Shared helpers: fingerprints, compose wrapper, volume setup |

Docker build contexts are the repository root for the Gazebo, SITL and subsystem images, because those images copy files from `backend/`. That is why `COPY` lines in the Dockerfiles start with `deploy/images/...`.

## Run SceneGEMS on one machine

Requirements: Docker with Compose v2 and Bash (Git Bash or WSL on Windows). From the repository root:

```bash
./build.sh
./start.sh
```

`build.sh` computes a fingerprint of every image's inputs (repository-relative paths, LF line endings, the pins file for images that declare pins), stores it in the image as the label `org.scenegems.fingerprint` and rebuilds only images whose label differs. The same commit gives the same fingerprints on Windows and Linux. `./build.sh --fingerprints` prints them without building. The first build after this change rebuilds every image once, because the fingerprint algorithm changed.

Open http://localhost:5173 for the web console. Press Ctrl+C in the terminal that runs `start.sh` to stop the stack and the subsystem containers it started.

Useful build options (`./build.sh --help` lists all):

| Option | Builds |
|--------|--------|
| `--stack` | backend, subsystems and frontend, no simulation images |
| `--simulation` | Gazebo, ArduPilot SITL, MAVProxy |
| `--arduagent` | the ArduPilot agent |
| `--no-check` | forces a rebuild |

## Worker machines

Setting up a worker machine is added together with the node daemon (phase 3 of `system_revision/architecture_design.md`). The target is three steps: clone the repository, run an install script with the master address and the one-time pairing token from the control panel, done. The install script will check Docker, build the images pinned by the campaign, write the node configuration and start the node daemon as a service. Scripts for Linux, macOS and Windows will live in `deploy/node/`.
