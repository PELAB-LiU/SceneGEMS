# Deployment

Everything needed to build SceneGEMS images and run them lives here. SceneGEMS runs in two ways:

- **Workbench**: everything on this machine, started with `./start.sh`.
- **Cluster**: a master and any number of nodes on other machines. SceneGEMS does not install machines or set up their network. An external deployment tool (Machine Hub) connects the machines over a WireGuard VPN and installs a release bundle on each one. SceneGEMS then uses whatever machines are ready.

The repository root keeps two thin wrappers, `./build.sh` and `./start.sh`, that call the scripts in `deploy/scripts/`.

## Layout

| Path | Content |
|------|---------|
| `images/` | One folder per Docker image: `arduagent`, `gazebo`, `sitl`, `mavproxy`, `mqtt_broker`, `node`, and the four subsystem images `monitoring`, `scenario_generation`, `scenario_execution`, `trajectory_generation` |
| `images/upstream_pins.env` | Upstream commits and base image digest of the Gazebo and SITL images, passed as build arguments and written into `org.scenegems.*` image labels |
| `master/docker-compose.yml` | The stack of one master: Postgres, the cluster broker (TLS, per-node accounts), `master-api`, and the one-off `security` tool (profile `tools`) |
| `master/.env.example` | Every key of a master's `.env` |
| `node/docker-compose.yml` | The stack of one node of one master: the node daemon with the Docker socket. Every name carries the master id and node name, so a machine runs nodes for several masters side by side |
| `node/.env.example` | Every key of a node's `.env` |
| `workbench/docker-compose.yml` | The single-machine workbench: frontend, a plain local broker, backend |
| `scripts/build.sh` | Builds the images, skipping any whose inputs did not change; `--release` also writes a release bundle |
| `scripts/start.sh` | Starts the workbench and tails the backend logs |
| `scripts/docker-common.sh` | Shared helpers: fingerprints, compose wrapper, volume setup |

Docker build contexts are the repository root for the Gazebo, SITL and subsystem images, because those images copy files from `backend/`. That is why `COPY` lines in the Dockerfiles start with `deploy/images/...`.

## Workbench on one machine

Requirements: Docker with Compose v2 and Bash (Git Bash or WSL on Windows). From the repository root:

```bash
./build.sh
./start.sh
```

Open http://localhost:5173 for the web console. Press Ctrl+C in the terminal that runs `start.sh` to stop the stack and the subsystem containers it started.

`build.sh` computes a fingerprint of every image's inputs (repository-relative paths, LF line endings, the pins file for images that declare pins), stores it in the image as the label `org.scenegems.fingerprint` and rebuilds only images whose label differs. The same commit gives the same fingerprints on Windows and Linux. `./build.sh --fingerprints` prints them without building.

| Option | Builds |
|--------|--------|
| `--stack` | backend, subsystems and frontend, no simulation images |
| `--simulation` | Gazebo, ArduPilot SITL, MAVProxy |
| `--node` | the node daemon |
| `--release <folder>` | everything a cluster runs, plus the release bundle |
| `--no-check` | forces a rebuild |

## Cluster: the release bundle

On the machine that builds the images:

```bash
./build.sh --release ../scenegems-release
```

This builds the images a cluster runs, pulls Postgres and writes the bundle:

| File | Content |
|------|---------|
| `release.json` | The revision (and whether the checkout had uncommitted changes), every image with its ID and fingerprint label, and the roles `master` and `node` |
| `stacks/master/docker-compose.yml` | Copy of `deploy/master/docker-compose.yml` |
| `stacks/node/docker-compose.yml` | Copy of `deploy/node/docker-compose.yml` |

The bundle holds no source code. Machines need only Docker with Compose v2. The deployment tool reads `release.json` and, for each machine you give a role:

1. Loads the role's images onto the machine, skipping images it already has.
2. Copies the role's stack and `release.json` into a folder of its own, one per master or node.
3. Writes `.env` with mode 600: the role's fixed values, your parameters (ports, node capabilities with slots, labels), and secrets. Secrets are generated once on the machine and kept on later deployments.
4. For a node: it runs the master's `pairing` output command on the master and writes the four values it prints into the node's `.env`, without logging them.
5. Runs the role's setup commands. For a master, `docker compose --profile tools run --rm -T security init` creates the CA and certificates for the master's VPN address.
6. Runs `docker compose up -d` and waits for the role's ready services.

The roles are defined in `backend/src/scenegems_tool/cluster/release/roles.py`, and `release.json` is the contract with the tool. A test keeps the roles, both compose files and both `.env.example` files in agreement.

The master reads the image fingerprints its nodes must have from its `release.json`. A node whose images differ from the release gets no jobs until the tool loads the release's images onto it.

## Secrets

Real `.env` files are gitignored and stay on the machines. The master's Postgres password, broker password and broker hook secret are generated on the master. A node's pairing token is used once, and the node then keeps its credentials in its state volume. Losing a master's `security_data` folder (the CA key) means pairing every node again.
