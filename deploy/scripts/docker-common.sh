#!/usr/bin/env bash
# Shared Docker image fingerprinting and build helpers for build.sh / start.sh.

docker_common_init() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    cd "$SCRIPT_DIR"
    export REPO_ROOT="$SCRIPT_DIR"
    COMPOSE_FILE="$SCRIPT_DIR/deploy/master/docker-compose.yml"
    COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-scenegems}"
    UPSTREAM_PINS_FILE="$SCRIPT_DIR/deploy/images/upstream_pins.env"
}

compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT_NAME" "$@"
    else
        docker-compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT_NAME" "$@"
    fi
}

stamp_path_for_tag() {
    local tag="$1"
    local safe_tag="${tag//[:]/_}"
    echo "$SCRIPT_DIR/.docker-stamps/${safe_tag}.sha256"
}

fingerprint_find_excluded_files() {
    local root="$1"
    find "$root" -type f \
        ! -path '*/node_modules/*' \
        ! -path '*/.git/*' \
        ! -path '*/__pycache__/*' \
        ! -path '*/env/*' \
        ! -path '*/venv/*' \
        ! -path '*/.docker-stamps/*' \
        ! -path '*/dist/*' \
        ! -path '*/dist-ssr/*' \
        ! -path '*/.mypy_cache/*' \
        ! -path '*/.pytest_cache/*' \
        ! -path '*/website/build/*' \
        ! -path '*/public/docs/*' \
        ! -path '*/.egg-info/*' \
        ! -path '*/assets/gen_data/*' \
        ! -path '*/assets/images/exported_plots/*' \
        ! -path '*/runtime_assets/*/gen_tmp/*'
}

# Upstream source pins: every KEY=VALUE line of deploy/images/upstream_pins.env whose KEY a
# Dockerfile declares with ARG is passed to that image's docker build, and the pins file is
# then part of the image fingerprint.

# Prints the --build-arg flags, one word per line, for the pins the Dockerfile declares.
upstream_pin_build_args() {
    local dockerfile="$1"
    local line key
    [ -f "$UPSTREAM_PINS_FILE" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        case "$line" in
            '' | '#'*) continue ;;
        esac
        key="${line%%=*}"
        if grep -Eq "^[[:space:]]*ARG[[:space:]]+${key}([[:space:]=]|\$)" "$dockerfile"; then
            printf '%s\n' --build-arg "$line"
        fi
    done <"$UPSTREAM_PINS_FILE"
}

dockerfile_uses_upstream_pins() {
    [ -n "$(upstream_pin_build_args "$1")" ]
}

docker_build_image() {
    local tag="$1"
    local dockerfile="$2"
    local context_dir="$3"
    local build_args=()
    local arg
    while IFS= read -r arg; do
        build_args+=("$arg")
    done < <(upstream_pin_build_args "$dockerfile")
    docker build ${build_args[@]+"${build_args[@]}"} -f "$dockerfile" -t "$tag" "$context_dir"
}

fingerprint_docker_context() {
    local dockerfile="$1"
    local context_dir="$2"
    {
        sha256sum "$dockerfile"
        if dockerfile_uses_upstream_pins "$dockerfile"; then
            sha256sum "$UPSTREAM_PINS_FILE"
        fi
        fingerprint_find_excluded_files "$context_dir" | LC_ALL=C sort | while IFS= read -r file; do
            sha256sum "$file"
        done
    } | sha256sum | awk '{print $1}'
}

fingerprint_paths() {
    local path
    {
        for path in "$@"; do
            if [ -f "$path" ]; then
                sha256sum "$path"
            elif [ -d "$path" ]; then
                fingerprint_find_excluded_files "$path" | LC_ALL=C sort | while IFS= read -r file; do
                    sha256sum "$file"
                done
            fi
        done
    } | sha256sum | awk '{print $1}'
}

fingerprint_image_inputs() {
    local dockerfile="$1"
    shift
    if dockerfile_uses_upstream_pins "$dockerfile"; then
        fingerprint_paths "$dockerfile" "$@" "$UPSTREAM_PINS_FILE"
    else
        fingerprint_paths "$dockerfile" "$@"
    fi
}

image_exists() {
    docker image inspect "$1" >/dev/null 2>&1
}

write_build_stamp() {
    local tag="$1"
    local fingerprint="$2"
    local stamp_path
    stamp_path=$(stamp_path_for_tag "$tag")
    mkdir -p "$(dirname "$stamp_path")"
    printf '%s\n' "$fingerprint" >"$stamp_path"
}

build_if_stale() {
    local tag="$1"
    local dockerfile="$2"
    local context_dir="$3"
    local fingerprint stamp_path stored

    if [ "${DOCKER_BUILD_SKIP_CHECK:-0}" = "1" ]; then
        echo "Building $tag (--no-check)..."
        docker_build_image "$tag" "$dockerfile" "$context_dir"
        fingerprint=$(fingerprint_docker_context "$dockerfile" "$context_dir")
        write_build_stamp "$tag" "$fingerprint"
        return
    fi

    echo "Checking image $tag..."
    fingerprint=$(fingerprint_docker_context "$dockerfile" "$context_dir")
    stamp_path=$(stamp_path_for_tag "$tag")
    stored=""
    if [ -f "$stamp_path" ]; then
        stored=$(tr -d '\r\n' <"$stamp_path")
    fi

    if [ "$fingerprint" = "$stored" ] && image_exists "$tag"; then
        echo "Image $tag is up to date."
        return
    fi

    echo "Building $tag..."
    docker_build_image "$tag" "$dockerfile" "$context_dir"
    write_build_stamp "$tag" "$fingerprint"
}

build_subsystem_if_stale() {
    local tag="$1"
    local dockerfile="$2"
    shift 2
    local fingerprint stamp_path stored

    if [ "${DOCKER_BUILD_SKIP_CHECK:-0}" = "1" ]; then
        echo "Building $tag (--no-check)..."
        docker_build_image "$tag" "$dockerfile" "$SCRIPT_DIR"
        fingerprint=$(fingerprint_image_inputs "$dockerfile" "$@")
        write_build_stamp "$tag" "$fingerprint"
        return
    fi

    echo "Checking image $tag..."
    fingerprint=$(fingerprint_image_inputs "$dockerfile" "$@")
    stamp_path=$(stamp_path_for_tag "$tag")
    stored=""
    if [ -f "$stamp_path" ]; then
        stored=$(tr -d '\r\n' <"$stamp_path")
    fi

    if [ "$fingerprint" = "$stored" ] && image_exists "$tag"; then
        echo "Image $tag is up to date."
        return
    fi

    echo "Building $tag..."
    docker_build_image "$tag" "$dockerfile" "$SCRIPT_DIR"
    write_build_stamp "$tag" "$fingerprint"
}

require_image() {
    local tag="$1"
    if ! image_exists "$tag"; then
        echo "Missing image $tag. Run ./build.sh first." >&2
        exit 1
    fi
}

ensure_compose_volumes() {
    docker volume inspect scenegems_runtime_assets >/dev/null 2>&1 \
        || docker volume create scenegems_runtime_assets >/dev/null
    docker volume inspect scenegems_broker_data >/dev/null 2>&1 \
        || docker volume create scenegems_broker_data >/dev/null
}

shutdown_stack() {
    echo "Shutting down SceneGEMS stack..."
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "scenegems_backend"; then
        docker exec scenegems_backend python - <<'PY' 2>/dev/null || true
from scenegems_tool.cluster.node.docker_subsystem_shutdown import shutdown_all_docker_subsystems
shutdown_all_docker_subsystems()
PY
    fi
    compose_cmd down --remove-orphans 2>/dev/null || true
}
