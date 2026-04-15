#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENGINE="${SHADOWBROKER_CONTAINER_ENGINE:-auto}"
COMPOSE_ARGS=()
COMPOSE_PROVIDER=""

find_docker_compose() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
        COMPOSE_PROVIDER="docker compose"
        return 0
    fi

    if command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD=(docker-compose)
        COMPOSE_PROVIDER="docker-compose"
        return 0
    fi

    return 1
}

find_podman_compose() {
    if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(podman compose)
        COMPOSE_PROVIDER="podman compose"
        return 0
    fi

    if command -v podman-compose >/dev/null 2>&1; then
        COMPOSE_CMD=(podman-compose)
        COMPOSE_PROVIDER="podman-compose"
        return 0
    fi

    return 1
}

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "[!] ERROR: Missing compose file: $COMPOSE_FILE"
    exit 1
fi

# Detect stale compose file from pre-migration clones (before March 2026).
# The current compose file uses "image:" to pull pre-built images from GHCR.
# Old versions had "build:" directives that compile from local source — much
# slower and will NOT pick up new releases.
if grep -q '^\s*build:' "$COMPOSE_FILE" 2>/dev/null; then
    echo ""
    echo "================================================================"
    echo "  [!] WARNING: Your docker-compose.yml is outdated."
    echo ""
    echo "  It contains 'build:' directives, which means Docker is"
    echo "  compiling from local source instead of pulling pre-built"
    echo "  images. You will NOT receive updates this way."
    echo ""
    echo "  Fix: re-clone the repository:"
    echo "    cd .. && rm -rf $(basename "$SCRIPT_DIR")"
    echo "    git clone https://github.com/BigBodyCobain/Shadowbroker.git"
    echo "    cd Shadowbroker && docker compose pull && docker compose up -d"
    echo "================================================================"
    echo ""
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        --engine)
            if [ "$#" -lt 2 ]; then
                echo "[!] ERROR: --engine requires a value: docker, podman, or auto."
                exit 1
            fi
            ENGINE="$2"
            shift 2
            ;;
        --engine=*)
            ENGINE="${1#*=}"
            shift
            ;;
        *)
            COMPOSE_ARGS+=("$1")
            shift
            ;;
    esac
done

if [ "${#COMPOSE_ARGS[@]}" -eq 0 ]; then
    COMPOSE_ARGS=(up -d)
fi

if [ "${#COMPOSE_ARGS[@]}" -gt 0 ]; then
    last_index=$((${#COMPOSE_ARGS[@]} - 1))
    if [ "${COMPOSE_ARGS[$last_index]}" = "." ]; then
        echo "[*] Ignoring trailing '.' argument."
        unset "COMPOSE_ARGS[$last_index]"
    fi
fi

if [ "${#COMPOSE_ARGS[@]}" -eq 0 ]; then
    COMPOSE_ARGS=(up -d)
fi

COMPOSE_CMD=()

case "$ENGINE" in
    auto)
        find_docker_compose || find_podman_compose
        ;;
    docker)
        find_docker_compose
        ;;
    podman)
        find_podman_compose
        ;;
    *)
        echo "[!] ERROR: Unsupported engine '$ENGINE'. Use docker, podman, or auto."
        exit 1
        ;;
esac

if [ "${#COMPOSE_CMD[@]}" -eq 0 ]; then
    echo "[!] ERROR: No supported compose command found for engine '$ENGINE'."
    echo "    Install one of: docker compose, docker-compose, podman compose, or podman-compose."
    exit 1
fi

if [ "$ENGINE" = "podman" ] && [ "$COMPOSE_PROVIDER" = "podman compose" ]; then
    echo "[*] Using (podman): ${COMPOSE_CMD[*]}"
    echo "[*] Note: 'podman compose' is Podman's wrapper command and may delegate to docker-compose based on your local Podman configuration."
else
    echo "[*] Using ($ENGINE): ${COMPOSE_CMD[*]}"
fi

"${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" "${COMPOSE_ARGS[@]}"
