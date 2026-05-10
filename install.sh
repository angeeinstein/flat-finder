#!/usr/bin/env bash
# flat-finder bare-metal installer / management script.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/angeeinstein/flat-finder/main/install.sh | sudo bash
#   sudo ./install.sh

set -Eeuo pipefail

# ---------- configuration ----------
APP_NAME="flat-finder"
APP_USER="flatfinder"
INSTALL_DIR="/opt/${APP_NAME}"
CONFIG_DIR="/etc/${APP_NAME}"
ENV_FILE="${CONFIG_DIR}/${APP_NAME}.env"
DATA_DIR="/var/lib/${APP_NAME}"
LOG_DIR="/var/log/${APP_NAME}"
REPO_URL="https://github.com/angeeinstein/flat-finder.git"
REPO_RAW_URL="https://raw.githubusercontent.com/angeeinstein/flat-finder/main"
WEB_SERVICE="${APP_NAME}-web.service"
WORKER_SERVICE="${APP_NAME}-worker.service"
NGINX_SITE="/etc/nginx/sites-available/${APP_NAME}.conf"
NGINX_LINK="/etc/nginx/sites-enabled/${APP_NAME}.conf"

# ---------- colors ----------
if [[ -t 1 ]]; then
  C_RED=$'\e[31m'; C_GRN=$'\e[32m'; C_YLW=$'\e[33m'; C_BLU=$'\e[34m'; C_BLD=$'\e[1m'; C_RST=$'\e[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_BLD=""; C_RST=""
fi

log_info()  { echo -e "${C_BLU}[INFO]${C_RST}  $*"; }
log_ok()    { echo -e "${C_GRN}[ OK ]${C_RST}  $*"; }
log_warn()  { echo -e "${C_YLW}[WARN]${C_RST}  $*" >&2; }
log_error() { echo -e "${C_RED}[ERR ]${C_RST}  $*" >&2; }
log_step()  { echo -e "\n${C_BLD}== $* ==${C_RST}"; }

confirm() {
    local prompt="${1:-Continue?}"
    local default="${2:-N}"
    local yn
    if [[ "$default" == "Y" ]]; then
        read -rp "$prompt [Y/n] " yn || true
        yn="${yn:-Y}"
    else
        read -rp "$prompt [y/N] " yn || true
        yn="${yn:-N}"
    fi
    [[ "${yn,,}" == "y" || "${yn,,}" == "yes" ]]
}

trap 'log_error "Installer aborted on line $LINENO."; exit 1' ERR

# ---------- preflight ----------
require_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Run this script as root (e.g. with sudo)."
        exit 1
    fi
}

OS_ID="" ; OS_VERSION_ID=""
detect_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_ID="${ID:-}"
        OS_VERSION_ID="${VERSION_ID:-}"
    fi
    log_info "Detected OS: ${OS_ID:-unknown} ${OS_VERSION_ID:-?}"
    case "$OS_ID" in
        debian|ubuntu) ;;
        *)
            log_warn "Unsupported OS: $OS_ID. The installer targets Debian 12 / Ubuntu 22.04+."
            confirm "Continue anyway?" "N" || exit 1
        ;;
    esac
    if ! command -v apt-get >/dev/null 2>&1; then
        log_error "apt-get not found. This installer requires a Debian/Ubuntu system."
        exit 1
    fi
}

# ---------- packages ----------
install_packages() {
    log_step "Installing system packages"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends \
        git curl ca-certificates gnupg lsb-release openssl \
        python3 python3-venv python3-pip python3-dev \
        build-essential pkg-config libpq-dev \
        postgresql postgresql-contrib \
        redis-server \
        nginx
    log_ok "Base packages installed."
}

install_certbot() {
    apt-get install -y --no-install-recommends certbot python3-certbot-nginx
}

# ---------- ollama ----------
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:3b}"

install_ollama() {
    log_step "Ollama (LLM for listing text extraction)"
    log_info "Ollama lets flat-finder extract extra fields (pets, internet included, landlord type)"
    log_info "from the listing description text. Model: ${OLLAMA_MODEL} (~2 GB download)."
    log_info "Minimum RAM recommended: 4 GB. Can be skipped and added later."

    if ! confirm "Install Ollama and pull the model?" "Y"; then
        log_info "Skipping Ollama. Import will work fine without it."
        return 0
    fi

    # Install Ollama binary + systemd unit (idempotent)
    if command -v ollama >/dev/null 2>&1; then
        log_info "Ollama already installed ($(ollama --version 2>/dev/null || echo unknown version))."
    else
        log_info "Downloading Ollama installer..."
        curl -fsSL https://ollama.com/install.sh | sh
        log_ok "Ollama installed."
    fi

    systemctl enable --now ollama

    # Wait up to 30 s for the API to become ready
    log_info "Waiting for Ollama API..."
    local ready=0
    for _ in $(seq 1 15); do
        if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
            ready=1; break
        fi
        sleep 2
    done
    if [[ $ready -eq 0 ]]; then
        log_warn "Ollama API did not respond in time. Try pulling the model manually later:"
        log_warn "  ollama pull ${OLLAMA_MODEL}"
        return 0
    fi

    # Pull model (skip if already present)
    if ollama list 2>/dev/null | grep -q "^${OLLAMA_MODEL}"; then
        log_info "Model ${OLLAMA_MODEL} already present."
    else
        log_info "Pulling ${OLLAMA_MODEL} — this may take a few minutes..."
        ollama pull "${OLLAMA_MODEL}"
        log_ok "Model ${OLLAMA_MODEL} ready."
    fi
}

ensure_ollama_model() {
    # Called during updates: if Ollama is installed make sure the model is present.
    if ! command -v ollama >/dev/null 2>&1; then return 0; fi
    if ! systemctl is-active --quiet ollama; then
        systemctl start ollama 2>/dev/null || true
        sleep 3
    fi
    if ! ollama list 2>/dev/null | grep -q "^${OLLAMA_MODEL}"; then
        log_info "Pulling Ollama model ${OLLAMA_MODEL}..."
        ollama pull "${OLLAMA_MODEL}" || log_warn "Model pull failed — run 'ollama pull ${OLLAMA_MODEL}' manually."
    fi
}

# ---------- user, dirs ----------
create_user() {
    log_step "Creating system user '${APP_USER}'"
    if id "$APP_USER" >/dev/null 2>&1; then
        log_info "User already exists."
    else
        adduser --system --group --home "$INSTALL_DIR" --no-create-home --shell /usr/sbin/nologin "$APP_USER"
        log_ok "Created user."
    fi
}

create_dirs() {
    log_step "Creating directories"
    mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$DATA_DIR" "$DATA_DIR/images" \
             "$DATA_DIR/snapshots" "$DATA_DIR/backups" "$LOG_DIR"
    chown -R "$APP_USER":"$APP_USER" "$INSTALL_DIR" "$DATA_DIR" "$LOG_DIR"
    chown root:"$APP_USER" "$CONFIG_DIR"
    chmod 750 "$CONFIG_DIR"
    log_ok "Directories ready."
}

# ---------- repo ----------
clone_repo() {
    log_step "Fetching application source"
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        log_info "Repository already present."
    else
        if [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
            log_warn "$INSTALL_DIR is not empty but not a git repo; refusing to overwrite."
            exit 1
        fi
        sudo -u "$APP_USER" git clone "$REPO_URL" "$INSTALL_DIR"
        log_ok "Cloned repository."
    fi
}

# ---------- python venv ----------
setup_python() {
    log_step "Setting up Python virtualenv"
    if [[ ! -d "$INSTALL_DIR/venv" ]]; then
        sudo -u "$APP_USER" python3 -m venv "$INSTALL_DIR/venv"
    fi
    sudo -u "$APP_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip wheel
    sudo -u "$APP_USER" "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
    log_ok "Python dependencies installed."
}

# ---------- env file ----------
generate_secret() { openssl rand -hex 32; }

setup_env() {
    log_step "Configuring environment file"
    if [[ -f "$ENV_FILE" ]]; then
        log_info "Existing env file kept: $ENV_FILE"
        return 0
    fi
    local secret db_pass domain="" https="n" email=""

    if [[ -t 0 ]]; then
        read -rp "Domain or hostname (default: \$(hostname -f)): " domain || true
        if confirm "Configure HTTPS with Let's Encrypt now?" "N"; then
            https="y"
            read -rp "Email for Let's Encrypt: " email || true
        fi
    fi
    domain="${domain:-$(hostname -f 2>/dev/null || hostname)}"

    secret="$(generate_secret)"
    db_pass="$(generate_secret)"

    install -m 0640 -o root -g "$APP_USER" /dev/null "$ENV_FILE"
    cat > "$ENV_FILE" <<EOF
PYTHONUTF8=1
FLASK_ENV=production
FLASK_SECRET_KEY=${secret}
DATABASE_URL=postgresql://${APP_USER}:${db_pass}@localhost:5432/${APP_USER}
REDIS_URL=redis://localhost:6379/0
APP_BASE_URL=http://${domain}
DATA_DIR=${DATA_DIR}
IMAGE_DIR=${DATA_DIR}/images
SNAPSHOT_DIR=${DATA_DIR}/snapshots
MAX_IMPORT_DOWNLOAD_SIZE_MB=20
MAX_IMAGE_DOWNLOAD_SIZE_MB=10
ROUTING_PROVIDER=mock
GEOCODING_PROVIDER=nominatim
NOMINATIM_USER_AGENT="flat-finder/1.0 (admin@${domain})"
LOGIN_RATE_LIMIT="10 per minute"
LOG_LEVEL=INFO
DEFAULT_SCORE_DISPLAY=both
EOF
    chmod 0640 "$ENV_FILE"
    chown root:"$APP_USER" "$ENV_FILE"

    # remember domain/https for later steps
    echo "$domain" > "$CONFIG_DIR/.domain"
    echo "$https"  > "$CONFIG_DIR/.https"
    echo "$email"  > "$CONFIG_DIR/.email"

    log_ok "Wrote $ENV_FILE (mode 0640, group=$APP_USER)."
}

# ---------- postgres ----------
setup_postgres() {
    log_step "Configuring PostgreSQL"
    systemctl enable --now postgresql

    local db_url db_pass
    db_url="$(grep '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)"
    # extract password from postgresql://user:pass@host:port/db
    db_pass="$(echo "$db_url" | sed -E 's#postgresql://[^:]+:([^@]+)@.*#\1#')"

    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${APP_USER}'" | grep -q 1; then
        sudo -u postgres psql -c "CREATE USER ${APP_USER} WITH PASSWORD '${db_pass}';" >/dev/null
        log_ok "Created PostgreSQL role ${APP_USER}."
    else
        sudo -u postgres psql -c "ALTER USER ${APP_USER} WITH PASSWORD '${db_pass}';" >/dev/null
        log_info "PostgreSQL role ${APP_USER} already exists; password synced."
    fi

    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${APP_USER}'" | grep -q 1; then
        sudo -u postgres createdb -O "$APP_USER" --encoding=UTF8 --lc-collate=C.UTF-8 --lc-ctype=C.UTF-8 --template=template0 "$APP_USER"
        log_ok "Created database ${APP_USER}."
    else
        log_info "Database ${APP_USER} already exists."
    fi
}

# ---------- redis ----------
setup_redis() {
    log_step "Enabling Redis"
    systemctl enable --now redis-server || systemctl enable --now redis
    log_ok "Redis enabled."
}

# ---------- migrations ----------
run_migrations() {
    log_step "Running database migrations"
    if [[ ! -d "$INSTALL_DIR/migrations" ]]; then
        sudo -u "$APP_USER" bash -c "cd '$INSTALL_DIR' && \
            FLASK_APP=wsgi:app set -a && . '$ENV_FILE' && set +a && \
            '$INSTALL_DIR/venv/bin/flask' db init"
    fi
    sudo -u "$APP_USER" bash -c "cd '$INSTALL_DIR' && \
        FLASK_APP=wsgi:app set -a && . '$ENV_FILE' && set +a && \
        '$INSTALL_DIR/venv/bin/flask' db migrate -m 'auto' 2>/dev/null || true && \
        '$INSTALL_DIR/venv/bin/flask' db upgrade"
    log_ok "Migrations applied."
}

# ---------- systemd ----------
setup_systemd() {
    log_step "Installing systemd units"
    local web_tpl="$INSTALL_DIR/deploy/systemd/flat-finder-web.service.template"
    local worker_tpl="$INSTALL_DIR/deploy/systemd/flat-finder-worker.service.template"

    sed -e "s|__USER__|$APP_USER|g" \
        -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        -e "s|__ENV_FILE__|$ENV_FILE|g" \
        -e "s|__DATA_DIR__|$DATA_DIR|g" \
        "$web_tpl" > "/etc/systemd/system/${WEB_SERVICE}"

    sed -e "s|__USER__|$APP_USER|g" \
        -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        -e "s|__ENV_FILE__|$ENV_FILE|g" \
        -e "s|__DATA_DIR__|$DATA_DIR|g" \
        "$worker_tpl" > "/etc/systemd/system/${WORKER_SERVICE}"

    chmod 0644 "/etc/systemd/system/${WEB_SERVICE}" "/etc/systemd/system/${WORKER_SERVICE}"
    systemctl daemon-reload
    systemctl enable "$WEB_SERVICE" "$WORKER_SERVICE"
    log_ok "systemd units installed."
}

start_services() {
    log_step "Starting services"
    systemctl restart "$WEB_SERVICE"
    systemctl restart "$WORKER_SERVICE"
    sleep 1
    systemctl is-active --quiet "$WEB_SERVICE" && log_ok "$WEB_SERVICE active."     || log_warn "$WEB_SERVICE failed to start; check 'journalctl -u $WEB_SERVICE'."
    systemctl is-active --quiet "$WORKER_SERVICE" && log_ok "$WORKER_SERVICE active." || log_warn "$WORKER_SERVICE failed to start; check 'journalctl -u $WORKER_SERVICE'."
}

# ---------- nginx ----------
setup_nginx() {
    log_step "Configuring Nginx"
    local domain
    domain="$(cat "$CONFIG_DIR/.domain" 2>/dev/null || hostname -f)"
    local tpl="$INSTALL_DIR/deploy/nginx/flat-finder.conf.template"
    sed -e "s|__DOMAIN__|$domain|g" \
        -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        "$tpl" > "$NGINX_SITE"

    if [[ ! -L "$NGINX_LINK" ]]; then
        ln -s "$NGINX_SITE" "$NGINX_LINK"
    fi

    if [[ -L /etc/nginx/sites-enabled/default ]]; then
        log_warn "Disabling /etc/nginx/sites-enabled/default to avoid conflict."
        rm -f /etc/nginx/sites-enabled/default
    fi

    if nginx -t; then
        systemctl reload nginx
        log_ok "Nginx configured."
    else
        log_error "Nginx config test failed; not reloading."
        return 1
    fi
}

setup_https() {
    local https domain email
    https="$(cat "$CONFIG_DIR/.https" 2>/dev/null || echo n)"
    domain="$(cat "$CONFIG_DIR/.domain" 2>/dev/null || hostname -f)"
    email="$(cat "$CONFIG_DIR/.email" 2>/dev/null || echo "")"
    [[ "$https" != "y" ]] && return 0

    log_step "Configuring HTTPS with Let's Encrypt"
    install_certbot
    if certbot --nginx --non-interactive --agree-tos -m "$email" -d "$domain"; then
        log_ok "HTTPS certificate obtained."
    else
        log_warn "Certbot failed; HTTP is still available."
    fi
}

# ---------- summary ----------
print_summary() {
    local domain
    domain="$(cat "$CONFIG_DIR/.domain" 2>/dev/null || hostname -f)"
    cat <<EOF

${C_BLD}flat-finder is installed.${C_RST}

  URL:           http://${domain}
  Install dir:   ${INSTALL_DIR}
  Config:        ${ENV_FILE}
  Data:          ${DATA_DIR}
  Logs:          ${LOG_DIR}

Useful commands:
  systemctl status ${WEB_SERVICE}
  systemctl status ${WORKER_SERVICE}
  journalctl -u ${WEB_SERVICE} -f
  sudo -u ${APP_USER} ${INSTALL_DIR}/venv/bin/flask check-config
  sudo -u ${APP_USER} ${INSTALL_DIR}/venv/bin/flask create-admin

Open the URL in your browser; it will guide you through the first-admin setup.
EOF
}

# ---------- new install ----------
new_install() {
    log_step "Performing new install of ${APP_NAME}"
    install_packages
    create_user
    create_dirs
    clone_repo
    setup_python
    setup_env
    setup_postgres
    setup_redis
    run_migrations
    install_ollama
    setup_systemd
    start_services
    setup_nginx
    setup_https
    print_summary
}

# ---------- update self ----------
update_self() {
    log_step "Self-updating installer"
    local tmp
    tmp="$(mktemp)"
    if curl -fsSL "${REPO_RAW_URL}/install.sh" -o "$tmp" && [[ -s "$tmp" ]]; then
        install -m 0755 "$tmp" "$INSTALL_DIR/install.sh"
        rm -f "$tmp"
        log_ok "Replaced $INSTALL_DIR/install.sh with newest version."
        log_info "Re-executing latest installer..."
        exec bash "$INSTALL_DIR/install.sh" --updated
    fi
    rm -f "$tmp"
    log_warn "Could not download fresh install.sh; continuing with local version."
}

# ---------- update app ----------
update_app() {
    log_step "Updating application"
    local git="sudo -u $APP_USER git -C $INSTALL_DIR"

    # install.sh was just replaced by update_self(); restore it so git doesn't
    # see it as a local modification before git pull brings the real version.
    $git checkout -- install.sh 2>/dev/null || true

    if ! $git diff --quiet || ! $git diff --cached --quiet; then
        log_warn "Local repo has uncommitted changes."
        confirm "Stash and continue? (changes will be saved)" "N" && \
            $git stash push -u -m "auto-stash-before-update-$(date +%s)" || \
            { log_warn "Aborting update."; return 1; }
    fi
    $git fetch --all --tags
    $git pull --ff-only

    setup_python
    run_migrations
    # Backfill owner_id for apartments and targets created before the teams feature.
    sudo -u "$APP_USER" bash -c "cd '$INSTALL_DIR' && \
        FLASK_APP=wsgi:app set -a && . '$ENV_FILE' && set +a && \
        '$INSTALL_DIR/venv/bin/flask' backfill-owner-id 2>/dev/null || true && \
        '$INSTALL_DIR/venv/bin/flask' backfill-targets 2>/dev/null || true"
    ensure_ollama_model
    setup_systemd
    setup_nginx
    start_services
    log_ok "Update complete."
}

# ---------- repair ----------
repair_install() {
    log_step "Checking installation"
    local issues=0
    for cmd in psql redis-cli nginx git python3; do
        if ! command -v "$cmd" >/dev/null; then
            log_warn "Missing command: $cmd"; issues=$((issues+1))
        fi
    done
    [[ -f "$ENV_FILE" ]] || { log_warn "Missing env file: $ENV_FILE"; issues=$((issues+1)); }
    [[ -d "$INSTALL_DIR/venv" ]] || { log_warn "Missing venv"; issues=$((issues+1)); }
    [[ -d "$DATA_DIR/images" ]] || { log_warn "Missing IMAGE_DIR"; issues=$((issues+1)); }
    systemctl is-active --quiet postgresql || { log_warn "postgresql is not running"; issues=$((issues+1)); }
    systemctl is-active --quiet redis-server 2>/dev/null || systemctl is-active --quiet redis 2>/dev/null \
        || { log_warn "redis is not running"; issues=$((issues+1)); }
    systemctl is-active --quiet "$WEB_SERVICE"     || { log_warn "${WEB_SERVICE} is not running"; issues=$((issues+1)); }
    systemctl is-active --quiet "$WORKER_SERVICE"  || { log_warn "${WORKER_SERVICE} is not running"; issues=$((issues+1)); }

    # Ollama is optional — just report its state, don't count as issue
    if command -v ollama >/dev/null 2>&1; then
        if systemctl is-active --quiet ollama; then
            log_ok "Ollama service running."
            if ollama list 2>/dev/null | grep -q "^${OLLAMA_MODEL}"; then
                log_ok "Ollama model ${OLLAMA_MODEL} present."
            else
                log_warn "Ollama model ${OLLAMA_MODEL} not found. Run: ollama pull ${OLLAMA_MODEL}"
            fi
        else
            log_warn "Ollama installed but service is not running."
        fi
    else
        log_info "Ollama not installed (optional — enables AI field extraction)."
    fi

    if [[ $issues -eq 0 ]]; then
        log_ok "All checks passed."
    else
        log_warn "$issues issue(s) detected."
        if confirm "Try to fix automatically?" "Y"; then
            install_packages
            create_dirs
            setup_python
            setup_postgres
            setup_redis
            run_migrations
            sudo -u "$APP_USER" bash -c "cd '$INSTALL_DIR' && \
                FLASK_APP=wsgi:app set -a && . '$ENV_FILE' && set +a && \
                '$INSTALL_DIR/venv/bin/flask' backfill-owner-id 2>/dev/null || true && \
                '$INSTALL_DIR/venv/bin/flask' backfill-targets 2>/dev/null || true"
            ensure_ollama_model
            setup_systemd
            start_services
            setup_nginx
            log_ok "Repair attempt complete."
        fi
    fi
}

# ---------- backup ----------
backup_data() {
    log_step "Creating backup"
    local ts target db_url db_user db_pass db_host db_port db_name
    ts="$(date +%Y%m%d_%H%M%S)"
    target="$DATA_DIR/backups/$ts"
    mkdir -p "$target"

    db_url="$(grep '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)"
    # parse postgresql://user:pass@host:port/dbname
    db_user="$(echo "$db_url" | sed -E 's#postgresql://([^:]+):.*#\1#')"
    db_pass="$(echo "$db_url" | sed -E 's#postgresql://[^:]+:([^@]+)@.*#\1#')"
    db_host="$(echo "$db_url" | sed -E 's#postgresql://[^@]+@([^:/]+).*#\1#')"
    db_port="$(echo "$db_url" | sed -E 's#.*:([0-9]+)/.*#\1#'); [[ "$db_port" == "$db_url" ]] && db_port=5432"
    db_name="$(echo "$db_url" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')"

    PGPASSWORD="$db_pass" pg_dump -h "$db_host" -p "${db_port:-5432}" -U "$db_user" "$db_name" \
        > "$target/database.sql"

    cp "$ENV_FILE" "$target/flat-finder.env"
    chmod 0600 "$target/flat-finder.env"

    if [[ -d "$DATA_DIR/images" ]]; then
        tar -C "$DATA_DIR" -czf "$target/images.tar.gz" images
    fi
    if [[ -d "$DATA_DIR/snapshots" ]]; then
        tar -C "$DATA_DIR" -czf "$target/snapshots.tar.gz" snapshots
    fi

    chown -R root:root "$target"
    chmod -R go-rwx "$target"
    log_ok "Backup written to $target"
}

restore_backup() {
    log_step "Restore backup"
    local path
    read -rp "Path to backup directory: " path
    if [[ ! -d "$path" || ! -f "$path/database.sql" ]]; then
        log_error "Invalid backup directory: $path"
        return 1
    fi
    confirm "This will OVERWRITE the database and data. Are you sure?" "N" || return 1

    systemctl stop "$WEB_SERVICE" "$WORKER_SERVICE" || true

    local db_url db_user db_pass db_host db_port db_name
    db_url="$(grep '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)"
    db_user="$(echo "$db_url" | sed -E 's#postgresql://([^:]+):.*#\1#')"
    db_pass="$(echo "$db_url" | sed -E 's#postgresql://[^:]+:([^@]+)@.*#\1#')"
    db_host="$(echo "$db_url" | sed -E 's#postgresql://[^@]+@([^:/]+).*#\1#')"
    db_name="$(echo "$db_url" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')"

    sudo -u postgres dropdb --if-exists "$db_name"
    sudo -u postgres createdb -O "$db_user" "$db_name"
    PGPASSWORD="$db_pass" psql -h "$db_host" -U "$db_user" "$db_name" < "$path/database.sql"

    [[ -f "$path/images.tar.gz" ]]    && tar -C "$DATA_DIR" -xzf "$path/images.tar.gz"
    [[ -f "$path/snapshots.tar.gz" ]] && tar -C "$DATA_DIR" -xzf "$path/snapshots.tar.gz"

    chown -R "$APP_USER":"$APP_USER" "$DATA_DIR"
    systemctl start "$WEB_SERVICE" "$WORKER_SERVICE"
    log_ok "Restore complete."
}

# ---------- show status / logs ----------
show_status() {
    systemctl status --no-pager "$WEB_SERVICE" || true
    echo
    systemctl status --no-pager "$WORKER_SERVICE" || true
}

show_logs() {
    journalctl -u "$WEB_SERVICE" -u "$WORKER_SERVICE" -n 200 --no-pager
}

# ---------- fix DB encoding ----------
fix_db_encoding() {
    log_step "Migrating database to UTF-8 encoding"
    local db_url db_user db_pass db_host db_port db_name enc
    db_url="$(grep '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)"
    db_user="$(echo "$db_url" | sed -E 's#postgresql://([^:]+):.*#\1#')"
    db_pass="$(echo "$db_url" | sed -E 's#postgresql://[^:]+:([^@]+)@.*#\1#')"
    db_host="$(echo "$db_url" | sed -E 's#postgresql://[^@]+@([^:/]+).*#\1#')"
    db_name="$(echo "$db_url" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')"

    enc="$(sudo -u postgres psql -tAc "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = '$db_name'" | tr -d ' ')"
    log_info "Current database encoding: ${enc:-unknown}"
    if [[ "$enc" == "UTF8" ]]; then
        log_ok "Already UTF-8; nothing to do."
        return 0
    fi

    confirm "Recreate '$db_name' with UTF-8 encoding? Services will be stopped briefly." "N" || return 1

    local ts dump
    ts="$(date +%Y%m%d_%H%M%S)"
    dump="$DATA_DIR/backups/encoding-fix-$ts.sql"
    mkdir -p "$DATA_DIR/backups"

    systemctl stop "$WEB_SERVICE" "$WORKER_SERVICE" || true

    log_info "Dumping current database to $dump"
    PGPASSWORD="$db_pass" pg_dump -h "$db_host" -U "$db_user" "$db_name" --encoding=UTF8 > "$dump"
    log_ok "Backup written to $dump"

    sudo -u postgres dropdb "$db_name"
    sudo -u postgres createdb -O "$db_user" --encoding=UTF8 --lc-collate=C.UTF-8 --lc-ctype=C.UTF-8 --template=template0 "$db_name"
    log_ok "Recreated $db_name with UTF-8."

    PGPASSWORD="$db_pass" psql -h "$db_host" -U "$db_user" "$db_name" < "$dump" >/dev/null
    log_ok "Restored data from $dump"

    systemctl start "$WEB_SERVICE" "$WORKER_SERVICE"
    log_ok "DB encoding migration complete."
}

# ---------- menu ----------
existing_install_menu() {
    cat <<EOF

${C_BLD}flat-finder is already installed at ${INSTALL_DIR}.${C_RST}
What would you like to do?

  1) Update application (download newest install.sh and update)
  2) Restart application
  3) Stop application
  4) Start application
  5) Show status
  6) Show recent logs
  7) Run database migrations
  8) Reinstall Python dependencies
  9) Repair installation / check dependencies
 10) Backup data
 11) Restore backup
 12) Reconfigure Nginx
 13) Configure HTTPS (Let's Encrypt)
 14) Migrate database to UTF-8 encoding
 15) Install / configure Ollama (AI field extraction)
 16) Exit

EOF
    local choice
    read -rp "Choice [1-16]: " choice || true
    case "$choice" in
        1)
            update_self
            update_app
            ;;
        2) systemctl restart "$WEB_SERVICE" "$WORKER_SERVICE" && log_ok "Restarted." ;;
        3) systemctl stop    "$WEB_SERVICE" "$WORKER_SERVICE" && log_ok "Stopped." ;;
        4) systemctl start   "$WEB_SERVICE" "$WORKER_SERVICE" && log_ok "Started." ;;
        5) show_status ;;
        6) show_logs ;;
        7) run_migrations ;;
        8) setup_python ;;
        9) repair_install ;;
       10) backup_data ;;
       11) restore_backup ;;
       12) setup_nginx ;;
       13)
            local domain
            read -rp "Domain: " domain
            local email
            read -rp "Email: " email
            echo "$domain" > "$CONFIG_DIR/.domain"
            echo "y"        > "$CONFIG_DIR/.https"
            echo "$email"   > "$CONFIG_DIR/.email"
            setup_https
            ;;
       14) fix_db_encoding ;;
       15) install_ollama ;;
       16|q|Q|"") log_info "Bye."; exit 0 ;;
        *) log_warn "Invalid choice." ;;
    esac
}

# ---------- main ----------
main() {
    require_root
    detect_os
    # When invoked via "curl | bash" stdin is the pipe, not the terminal.
    # Reopen it from /dev/tty so every read prompt works correctly.
    exec < /dev/tty

    if [[ -d "$INSTALL_DIR/.git" ]]; then
        # called from update_self with --updated → always run update
        if [[ "${1:-}" == "--updated" ]]; then
            update_app
            exit 0
        fi
        existing_install_menu
    else
        new_install
    fi
}

main "$@"
