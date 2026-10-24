#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/docker-common.sh"
docker_common_init

require_image "scenegems-frontend:dev"
require_image "scenegems-backend:latest"

# Host port published by the SceneGEMS compose broker (and by stacks such as OTG).
MQTT_HOST_PORT="${MQTT_HOST_PORT:-1882}"
MQTT_BROKER_CONTAINER_NAME="scenegems_local_mqtt_broker"

host_tcp_port_open() {
    local port="$1"
    if command -v python >/dev/null 2>&1; then
        python -c "import socket,sys; s=socket.socket(); s.settimeout(0.4); code=s.connect_ex(('127.0.0.1', int(sys.argv[1]))); s.close(); sys.exit(0 if code==0 else 1)" "$port"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.4); code=s.connect_ex(('127.0.0.1', int(sys.argv[1]))); s.close(); sys.exit(0 if code==0 else 1)" "$port"
        return
    fi
    (echo >/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1
}

our_mqtt_broker_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$MQTT_BROKER_CONTAINER_NAME"
}

ensure_compose_volumes

trap shutdown_stack EXIT INT TERM

echo "Starting frontend..."
compose_cmd up -d frontend

start_own_broker=1
if our_mqtt_broker_running; then
    echo "SceneGEMS MQTT broker is already running; reusing it."
elif host_tcp_port_open "$MQTT_HOST_PORT"; then
    echo "MQTT already listening on localhost:${MQTT_HOST_PORT}; not starting a SceneGEMS broker."
    start_own_broker=0
fi

if [ "$start_own_broker" -eq 1 ]; then
    require_image "scenegems-mqtt-broker:latest"
    echo "Starting MQTT broker and backend..."
    compose_cmd up -d broker backend
    mqtt_status="localhost:${MQTT_HOST_PORT} (host) / broker:1883 (compose network)"
else
    echo "Starting backend (using the existing MQTT broker)..."
    compose_cmd up -d backend
    mqtt_status="existing broker on localhost:${MQTT_HOST_PORT}"
fi

echo ""
echo "SceneGEMS stack is running:"
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://localhost:5174/health"
echo "  MQTT:      ${mqtt_status}"
echo ""
echo "Streaming backend logs (Ctrl+C stops the full stack)..."

compose_cmd logs -f backend
