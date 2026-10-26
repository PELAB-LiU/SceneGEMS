# Upstream pins come from deploy/images/upstream_pins.env (passed by deploy/scripts/build.sh).
ARG UBUNTU_BASE_IMAGE
FROM ${UBUNTU_BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

# 1. Install minimal tools to add the Gazebo repository
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 2. Add the Gazebo Harmonic repository
RUN wget -O /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg https://packages.osrfoundation.org/gazebo.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable noble main" \
    > /etc/apt/sources.list.d/gazebo-stable.list

# 3. Install Build Tools, OpenCV, ZeroMQ, RapidJSON, and Gazebo Headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    pkg-config \
    # ArduPilot plugin requirements
    libopencv-dev \
    rapidjson-dev \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    cppzmq-dev \
    libzmq3-dev \
    libgflags-dev \
    libprotobuf-dev \
    protobuf-compiler \
    # asv_wave_sim specific dependencies
    libcgal-dev \
    libfftw3-dev \
    libboost-all-dev \
    libboost-iostreams-dev \
    libboost-system-dev \
    # Gazebo Harmonic suite and dev headers
    gz-harmonic \
    libgz-sim8-dev \
    # gz-sim-waves-system (world plugin) lives in plugins, not pulled by gz-harmonic alone
    libgz-sim8-plugins \
    # srmainwaring/asv_sim (anemometer + wind systems) links sensors + sdformat14 on Harmonic
    libgz-sensors8-dev \
    libsdformat14-dev \
    libgz-common5-dev \
    libgz-math7-dev \
    libgz-msgs10-dev \
    libgz-plugin2-dev \
    libgz-transport13-dev \
    && rm -rf /var/lib/apt/lists/*

# 4. Build ArduPilot Gazebo Plugin at the pinned commit: the head of
# https://github.com/ArduPilot/ardupilot_gazebo/pull/166 (multi-instance ArduPilotPlugin: stable
# per-plugin FCU IP via inet_ntop; offline recovery duplicate-frame fix), which fast-forwards main
# at the pinned base commit.
ARG ARDUPILOT_GAZEBO_REPO
ARG ARDUPILOT_GAZEBO_BASE_COMMIT
ARG ARDUPILOT_GAZEBO_COMMIT
WORKDIR /opt/ardupilot_gazebo
RUN : "${ARDUPILOT_GAZEBO_REPO:?missing build arg, see deploy/images/upstream_pins.env}" && \
    : "${ARDUPILOT_GAZEBO_BASE_COMMIT:?missing build arg, see deploy/images/upstream_pins.env}" && \
    : "${ARDUPILOT_GAZEBO_COMMIT:?missing build arg, see deploy/images/upstream_pins.env}" && \
    git init -q && \
    git remote add origin "$ARDUPILOT_GAZEBO_REPO" && \
    git fetch -q origin "$ARDUPILOT_GAZEBO_BASE_COMMIT" "$ARDUPILOT_GAZEBO_COMMIT" && \
    git merge-base --is-ancestor "$ARDUPILOT_GAZEBO_BASE_COMMIT" "$ARDUPILOT_GAZEBO_COMMIT" && \
    git checkout -q "$ARDUPILOT_GAZEBO_COMMIT" && \
    test "$(git rev-parse HEAD)" = "$ARDUPILOT_GAZEBO_COMMIT" && \
    cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo && \
    cmake --build build -j$(nproc) && \
    cmake --install build

# 5. ASV Sim2 system plugins (the generated world: asv_sim2-anemometer-system, asv_sim2-wind-system)
# https://github.com/srmainwaring/asv_sim at the pinned commit: build the Harmonic plugin stack
# (GZ_VERSION selects gz-sim8).
ARG ASV_SIM_REPO
ARG ASV_SIM_COMMIT
WORKDIR /opt/asv_sim
RUN : "${ASV_SIM_REPO:?missing build arg, see deploy/images/upstream_pins.env}" && \
    : "${ASV_SIM_COMMIT:?missing build arg, see deploy/images/upstream_pins.env}" && \
    git init -q && \
    git remote add origin "$ASV_SIM_REPO" && \
    git fetch -q --depth 1 origin "$ASV_SIM_COMMIT" && \
    git checkout -q FETCH_HEAD && \
    test "$(git rev-parse HEAD)" = "$ASV_SIM_COMMIT" && \
    cd asv_sim_gazebo_plugins && \
    GZ_VERSION=harmonic cmake -S . -B build \
      -DCMAKE_BUILD_TYPE=RelWithDebInfo \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
      -DBUILD_TESTING=OFF && \
    cmake --build build -j"$(nproc)" && \
    cmake --install build && \
    rm -rf /opt/asv_sim/.git

# 6. Environment Configuration
ENV GZ_VERSION=harmonic
ENV GZ_PARTITION=scenegems
ENV GZ_SIM_SYSTEM_PLUGIN_PATH=/usr/local/lib:/usr/local/lib/ardupilot_gazebo
ENV GZ_SIM_RESOURCE_PATH=/worlds:/opt/asv_wave_sim/gz-waves-models/models
ENV LC_NUMERIC=C

COPY deploy/images/gazebo/gazebo_entrypoint_prod.sh /scripts/entrypoint.sh
RUN chmod +x /scripts/entrypoint.sh

# 7. apt and Python packages are not pinned: record the installed versions so a node can report them.
RUN mkdir -p /etc/scenegems/package_versions && \
    dpkg-query -W -f='${Package}=${Version}\n' | LC_ALL=C sort > /etc/scenegems/package_versions/dpkg.txt && \
    python3 -c "import importlib.metadata as m; print(*sorted({'%s==%s' % (d.metadata.get('Name'), d.version) for d in m.distributions() if d.metadata.get('Name')}), sep=chr(10))" \
      > /etc/scenegems/package_versions/python.txt

ARG UBUNTU_BASE_IMAGE
LABEL org.scenegems.base_image="${UBUNTU_BASE_IMAGE}" \
      org.scenegems.upstream.ardupilot_gazebo="${ARDUPILOT_GAZEBO_COMMIT}" \
      org.scenegems.upstream.ardupilot_gazebo.base="${ARDUPILOT_GAZEBO_BASE_COMMIT}" \
      org.scenegems.upstream.asv_sim="${ASV_SIM_COMMIT}" \
      org.scenegems.package_versions="/etc/scenegems/package_versions"

WORKDIR /worlds
CMD ["bash"]
