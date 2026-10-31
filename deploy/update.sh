#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${NEEDLEDROP_REPO_DIR:-/opt/needle-drop}"
SERVICE_NAME="${NEEDLEDROP_SERVICE_NAME:-needle-drop.service}"
REMOTE_NAME="${NEEDLEDROP_REMOTE_NAME:-origin}"
BRANCH_NAME="${NEEDLEDROP_BRANCH_NAME:-main}"
HEALTH_DELAY_S="${NEEDLEDROP_HEALTH_DELAY_S:-8}"
BACKUP_REF="${NEEDLEDROP_BACKUP_REF:-refs/needle-drop-backup/latest}"
REQUIREMENTS_FILE="${NEEDLEDROP_REQUIREMENTS_FILE:-requirements.txt}"

log() {
    printf '[needle-drop-deploy] %s\n' "$*"
}

run_systemctl() {
    if [ -n "${NEEDLEDROP_SYSTEMCTL_BIN:-}" ]; then
        "${NEEDLEDROP_SYSTEMCTL_BIN}" "$@"
        return
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo -n systemctl "$@"
        return
    fi

    systemctl "$@"
}

is_safe_to_update() {
    # Placeholder until the real gate/status check is implemented.
    return 0
}

install_dependencies() {
    if [ ! -f "$REQUIREMENTS_FILE" ]; then
        log "No $REQUIREMENTS_FILE found; skipping dependency install."
        return 0
    fi

    if [ -n "${NEEDLEDROP_PIP_BIN:-}" ]; then
        "${NEEDLEDROP_PIP_BIN}" install -r "$REQUIREMENTS_FILE"
        return 0
    fi

    if [ -x ".venv/bin/pip" ]; then
        .venv/bin/pip install -r "$REQUIREMENTS_FILE"
        return 0
    fi

    python3 -m pip install -r "$REQUIREMENTS_FILE"
}

wait_for_service_health() {
    sleep "$HEALTH_DELAY_S"
    run_systemctl is-active --quiet "$SERVICE_NAME"
}

rollback() {
    local backup_commit="$1"

    log "Rolling back to commit: $backup_commit"
    git reset --hard "$backup_commit"
    install_dependencies
    run_systemctl restart "$SERVICE_NAME"

    if wait_for_service_health; then
        log "Rollback succeeded; service is healthy."
        return 0
    fi

    log "Rollback failed; service is still unhealthy."
    return 1
}

main() {
    cd "$REPO_DIR"

    log "Fetching latest $REMOTE_NAME/$BRANCH_NAME..."
    git fetch --quiet "$REMOTE_NAME" "$BRANCH_NAME"

    local local_commit
    local remote_commit

    local_commit="$(git rev-parse HEAD)"
    remote_commit="$(git rev-parse "$REMOTE_NAME/$BRANCH_NAME")"

    if [ "$local_commit" = "$remote_commit" ]; then
        log "No update available."
        return 0
    fi

    if ! is_safe_to_update; then
        log "Not a safe time to update; skipping."
        return 0
    fi

    log "Update detected: $local_commit -> $remote_commit"
    git update-ref "$BACKUP_REF" "$local_commit"
    log "Backup ref updated: $BACKUP_REF -> $local_commit"

    if git reset --hard "$remote_commit" \
        && install_dependencies \
        && run_systemctl restart "$SERVICE_NAME" \
        && wait_for_service_health; then
        log "Update applied successfully; service is healthy."
        return 0
    fi

    log "Update failed; attempting rollback."
    rollback "$local_commit"
}

main "$@"
