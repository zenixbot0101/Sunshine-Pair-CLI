#!/usr/bin/env bash
#
# vps-stack.sh — ALL-IN-ONE
# code-server (VS Code Web) + TigerVNC + noVNC + Cloudflare Tunnel
# Chon Desktop Environment: XFCE hoac KDE Plasma
# Tu phat hien goi da cai -> skip, chua cai -> cai
# Ghi log hoat dong noVNC session (kieu task-manager: active window, uptime...)
#
# CHI DANH CHO VPS/MAY CHU BAN SO HUU VA CO QUYEN QUAN TRI (Debian/Ubuntu).
#
# Cach dung:
#   chmod +x vps-stack.sh
#   ./vps-stack.sh                # mo menu tuong tac
#   ./vps-stack.sh install        # cai dat toan bo (khong tuong tac, dung DE mac dinh/da luu)
#   ./vps-stack.sh start          # khoi dong tat ca dich vu da cai
#   ./vps-stack.sh stop           # dung tat ca
#   ./vps-stack.sh status         # xem trang thai + URL
#   ./vps-stack.sh logs           # xem log hoat dong gan nhat
#   ./vps-stack.sh uninstall      # go cai dat
#
set -uo pipefail

# ========================= CONFIG =========================
CODE_PORT="${CODE_PORT:-8080}"
DISPLAY_NUM="${DISPLAY_NUM:-1}"
VNC_PORT="$((5900 + DISPLAY_NUM))"
NOVNC_PORT="${NOVNC_PORT:-6080}"
ACTIVITY_INTERVAL="${ACTIVITY_INTERVAL:-5}"   # giay giua moi lan ghi log hoat dong

STATE_DIR="${HOME}/.config/vps-stack"
DE_STATE_FILE="${STATE_DIR}/desktop_env"        # chua "xfce" hoac "kde"
CS_CONFIG_DIR="${HOME}/.config/code-server"
CS_CONFIG_FILE="${CS_CONFIG_DIR}/config.yaml"
NOVNC_DIR="${HOME}/noVNC"

RUN_DIR="${HOME}/.local/run/vps-stack"
LOG_DIR="${RUN_DIR}/logs"
mkdir -p "$STATE_DIR" "$RUN_DIR" "$LOG_DIR"

PID_CS="${RUN_DIR}/code-server.pid"
PID_CF_CS="${RUN_DIR}/cloudflared-code.pid"
PID_NOVNC="${RUN_DIR}/novnc.pid"
PID_CF_VNC="${RUN_DIR}/cloudflared-vnc.pid"
PID_ACTLOG="${RUN_DIR}/activity.pid"

LOG_CS="${LOG_DIR}/code-server.log"
LOG_CF_CS="${LOG_DIR}/cloudflared-code.log"
LOG_NOVNC="${LOG_DIR}/novnc.log"
LOG_CF_VNC="${LOG_DIR}/cloudflared-vnc.log"
LOG_ACTIVITY="${LOG_DIR}/activity.log"

URL_CODE_FILE="${RUN_DIR}/url-code.txt"
URL_VNC_FILE="${RUN_DIR}/url-vnc.txt"

CODE_PASSWORD_FILE="${STATE_DIR}/code-password"
VNC_PASSWORD_FILE="${HOME}/.vnc/passwd"

# ========================= HELPERS =========================
c_reset="\033[0m"; c_green="\033[32m"; c_yellow="\033[33m"; c_red="\033[31m"; c_cyan="\033[36m"
log()  { echo -e "${c_cyan}[*]${c_reset} $*"; }
ok()   { echo -e "${c_green}[OK]${c_reset} $*"; }
warn() { echo -e "${c_yellow}[!]${c_reset} $*"; }
err()  { echo -e "${c_red}[X]${c_reset} $*" >&2; }
exists_cmd() { command -v "$1" >/dev/null 2>&1; }
pkg_installed() { dpkg -s "$1" >/dev/null 2>&1; }
is_running() { [ -f "$1" ] && kill -0 "$(cat "$1" 2>/dev/null)" 2>/dev/null; }

# Cai 1 goi apt neu chua co, in ra trang thai skip/cai
ensure_apt_pkg() {
    local pkg="$1"
    if pkg_installed "$pkg"; then
        ok "Goi '${pkg}' da cai -> bo qua"
    else
        log "Dang cai goi '${pkg}'..."
        sudo apt-get install -y "$pkg" >/dev/null 2>&1 \
            && ok "Da cai '${pkg}'" \
            || warn "Khong cai duoc '${pkg}' (kiem tra ten goi tren distro cua ban)"
    fi
}

require_apt_update_once() {
    if [ ! -f "${RUN_DIR}/.apt_updated" ]; then
        log "Cap nhat danh sach goi (apt-get update)..."
        sudo apt-get update -y >/dev/null 2>&1
        touch "${RUN_DIR}/.apt_updated"
    fi
}

# ========================= INSTALL: BASE =========================
install_base_deps() {
    require_apt_update_once
    local base_pkgs=(curl wget git unzip tar dbus-x11 net-tools xdotool wmctrl)
    for p in "${base_pkgs[@]}"; do ensure_apt_pkg "$p"; done
}

install_code_server() {
    if exists_cmd code-server; then
        ok "code-server da cai -> bo qua"
    else
        log "Dang cai code-server..."
        curl -fsSL https://code-server.dev/install.sh | sh >/dev/null 2>&1
        exists_cmd code-server && ok "Da cai code-server" || { err "Cai code-server that bai"; return 1; }
    fi
}

install_cloudflared() {
    if exists_cmd cloudflared; then
        ok "cloudflared da cai -> bo qua"
        return
    fi
    log "Dang cai cloudflared..."
    local arch cf_arch
    arch="$(uname -m)"
    case "$arch" in
        x86_64) cf_arch="amd64" ;;
        aarch64|arm64) cf_arch="arm64" ;;
        *) err "Kien truc khong ho tro: $arch"; return 1 ;;
    esac
    local tmp_deb
    tmp_deb="$(mktemp --suffix=.deb)"
    curl -fsSL -o "$tmp_deb" \
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${cf_arch}.deb"
    sudo dpkg -i "$tmp_deb" >/dev/null 2>&1 || sudo apt-get -f install -y >/dev/null 2>&1
    rm -f "$tmp_deb"
    exists_cmd cloudflared && ok "Da cai cloudflared" || { err "Cai cloudflared that bai"; return 1; }
}

install_tigervnc() {
    require_apt_update_once
    for p in tigervnc-standalone-server tigervnc-common; do ensure_apt_pkg "$p"; done
}

install_novnc() {
    if [ -d "$NOVNC_DIR" ] && [ -f "${NOVNC_DIR}/vnc.html" ]; then
        ok "noVNC da co tai ${NOVNC_DIR} -> bo qua"
    else
        log "Dang tai noVNC..."
        git clone --depth 1 https://github.com/novnc/noVNC.git "$NOVNC_DIR" >/dev/null 2>&1
        ok "Da tai noVNC"
    fi
}

# ========================= DESKTOP ENVIRONMENT =========================
install_xfce() {
    require_apt_update_once
    for p in xfce4 xfce4-goodies; do ensure_apt_pkg "$p"; done
    echo "xfce" > "$DE_STATE_FILE"
}

install_kde() {
    require_apt_update_once
    log "Cai KDE Plasma co the mat vai phut (goi nang hon XFCE)..."
    for p in kde-plasma-desktop; do ensure_apt_pkg "$p"; done
    echo "kde" > "$DE_STATE_FILE"
}

current_de() {
    [ -f "$DE_STATE_FILE" ] && cat "$DE_STATE_FILE" || echo "xfce"
}

write_xstartup() {
    local de
    de="$(current_de)"
    mkdir -p "${HOME}/.vnc"
    if [ "$de" = "kde" ]; then
        cat > "${HOME}/.vnc/xstartup" <<'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startplasma-x11
EOF
        ok "xstartup da cau hinh cho KDE Plasma"
    else
        cat > "${HOME}/.vnc/xstartup" <<'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
EOF
        ok "xstartup da cau hinh cho XFCE"
    fi
    chmod +x "${HOME}/.vnc/xstartup"
}

switch_de() {
    echo "Chon Desktop Environment:"
    echo "  1) XFCE (nhe, nhanh)"
    echo "  2) KDE Plasma (day du, nang hon)"
    read -rp "Lua chon [1-2]: " sel
    case "$sel" in
        1) install_xfce ;;
        2) install_kde ;;
        *) warn "Lua chon khong hop le"; return ;;
    esac
    write_xstartup
    if vncserver -list 2>/dev/null | grep -q ":${DISPLAY_NUM}"; then
        warn "VNC dang chay, can restart de doi giao dien"
        read -rp "Restart VNC ngay? (y/N): " r
        if [[ "$r" =~ ^[Yy]$ ]]; then
            vncserver -kill ":${DISPLAY_NUM}" >/dev/null 2>&1
            start_vnc_server
        fi
    fi
}

# ========================= CONFIG WRITERS =========================
write_code_server_config() {
    mkdir -p "$CS_CONFIG_DIR"
    local pw
    if [ -f "$CODE_PASSWORD_FILE" ]; then
        pw="$(cat "$CODE_PASSWORD_FILE")"
    else
        pw="$(openssl rand -hex 8 2>/dev/null || date +%s%N | sha256sum | head -c16)"
        echo "$pw" > "$CODE_PASSWORD_FILE"
        chmod 600 "$CODE_PASSWORD_FILE"
    fi
    cat > "$CS_CONFIG_FILE" <<EOF
bind-addr: 127.0.0.1:${CODE_PORT}
auth: password
password: ${pw}
cert: false
EOF
    ok "Da ghi cau hinh code-server"
}

setup_vnc_password() {
    mkdir -p "${HOME}/.vnc"
    if [ -f "$VNC_PASSWORD_FILE" ]; then
        ok "Mat khau VNC da ton tai -> bo qua"
    else
        local pw
        pw="$(openssl rand -hex 6 2>/dev/null || date +%s%N | sha256sum | head -c12)"
        echo "$pw" | vncpasswd -f > "$VNC_PASSWORD_FILE"
        chmod 600 "$VNC_PASSWORD_FILE"
        echo "$pw" > "${STATE_DIR}/vnc-password-plain"
        chmod 600 "${STATE_DIR}/vnc-password-plain"
        ok "Da tao mat khau VNC moi"
    fi
}

# ========================= ACTIVITY LOGGER (taskmanager-style) =========================
# Ghi lai: thoi gian, cua so dang active, so tien trinh, tai CPU/RAM tong quat
start_activity_logger() {
    if is_running "$PID_ACTLOG"; then
        ok "Activity logger dang chay (PID $(cat "$PID_ACTLOG"))"
        return
    fi
    log "Bat dau ghi log hoat dong noVNC session..."
    (
        export DISPLAY=":${DISPLAY_NUM}"
        while true; do
            ts="$(date '+%Y-%m-%d %H:%M:%S')"
            win="unknown"
            if exists_cmd xdotool; then
                win="$(xdotool getactivewindow getwindowname 2>/dev/null || echo 'khong xac dinh')"
            fi
            nproc_user="$(pgrep -u "$USER" -c 2>/dev/null || echo 0)"
            load="$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo 'n/a')"
            mem="$(free -h 2>/dev/null | awk '/Mem:/ {print $3"/"$2}')"
            echo "[${ts}] active_window=\"${win}\" processes=${nproc_user} load_avg=${load} mem=${mem}" >> "$LOG_ACTIVITY"
            sleep "$ACTIVITY_INTERVAL"
        done
    ) >/dev/null 2>&1 &
    echo $! > "$PID_ACTLOG"
    ok "Activity logger da chay (PID $(cat "$PID_ACTLOG")), ghi vao ${LOG_ACTIVITY}"
}

stop_activity_logger() {
    if is_running "$PID_ACTLOG"; then
        kill "$(cat "$PID_ACTLOG")" 2>/dev/null
        ok "Da dung activity logger"
    fi
    rm -f "$PID_ACTLOG"
}

# ========================= START SERVICES =========================
start_code_server() {
    if is_running "$PID_CS"; then
        ok "code-server dang chay (PID $(cat "$PID_CS"))"
    else
        log "Khoi dong code-server..."
        nohup code-server --config "$CS_CONFIG_FILE" > "$LOG_CS" 2>&1 &
        echo $! > "$PID_CS"
        sleep 3
        ok "code-server da chay (PID $(cat "$PID_CS"))"
    fi

    if is_running "$PID_CF_CS"; then
        ok "Cloudflare Tunnel (code-server) dang chay"
    else
        log "Khoi dong Cloudflare Tunnel cho code-server..."
        : > "$LOG_CF_CS"
        nohup cloudflared tunnel --url "http://127.0.0.1:${CODE_PORT}" > "$LOG_CF_CS" 2>&1 &
        echo $! > "$PID_CF_CS"
    fi
    wait_for_url "$LOG_CF_CS" "$URL_CODE_FILE"
}

start_vnc_server() {
    if vncserver -list 2>/dev/null | grep -q ":${DISPLAY_NUM}"; then
        ok "TigerVNC :${DISPLAY_NUM} da chay (port ${VNC_PORT})"
    else
        log "Khoi dong TigerVNC :${DISPLAY_NUM}..."
        vncserver ":${DISPLAY_NUM}" -localhost no -xstartup "${HOME}/.vnc/xstartup" >/dev/null 2>&1
        ok "TigerVNC da chay tren port ${VNC_PORT}"
    fi
}

start_novnc() {
    if is_running "$PID_NOVNC"; then
        ok "noVNC dang chay (PID $(cat "$PID_NOVNC"))"
    else
        log "Khoi dong noVNC proxy (port ${NOVNC_PORT})..."
        : > "$LOG_NOVNC"
        nohup "${NOVNC_DIR}/utils/novnc_proxy" \
            --vnc "localhost:${VNC_PORT}" --listen "${NOVNC_PORT}" \
            > "$LOG_NOVNC" 2>&1 &
        echo $! > "$PID_NOVNC"
        sleep 3
        ok "noVNC da chay (PID $(cat "$PID_NOVNC"))"
    fi

    if is_running "$PID_CF_VNC"; then
        ok "Cloudflare Tunnel (noVNC) dang chay"
    else
        log "Khoi dong Cloudflare Tunnel cho noVNC..."
        : > "$LOG_CF_VNC"
        nohup cloudflared tunnel --url "http://127.0.0.1:${NOVNC_PORT}" > "$LOG_CF_VNC" 2>&1 &
        echo $! > "$PID_CF_VNC"
    fi
    wait_for_url "$LOG_CF_VNC" "$URL_VNC_FILE"
    start_activity_logger
}

wait_for_url() {
    local logfile="$1" outfile="$2"
    local url=""
    for _ in $(seq 1 60); do
        sleep 1
        url="$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$logfile" 2>/dev/null | head -n1)"
        [ -n "$url" ] && break
    done
    echo "$url" > "$outfile"
}

start_all() {
    start_code_server
    start_vnc_server
    start_novnc
    print_summary
}

# ========================= STOP =========================
stop_all() {
    for pf in "$PID_CS" "$PID_CF_CS" "$PID_NOVNC" "$PID_CF_VNC"; do
        if is_running "$pf"; then
            kill "$(cat "$pf")" 2>/dev/null && ok "Da dung PID $(cat "$pf")"
        fi
        rm -f "$pf"
    done
    if vncserver -list 2>/dev/null | grep -q ":${DISPLAY_NUM}"; then
        vncserver -kill ":${DISPLAY_NUM}" >/dev/null 2>&1 && ok "Da dung TigerVNC :${DISPLAY_NUM}"
    fi
    stop_activity_logger
}

# ========================= STATUS / SUMMARY =========================
print_summary() {
    echo
    echo "=================================================="
    echo "                  STACK READY"
    echo "=================================================="
    echo "-- code-server --"
    [ -f "$URL_CODE_FILE" ] && echo "URL      : $(cat "$URL_CODE_FILE")"
    [ -f "$CODE_PASSWORD_FILE" ] && echo "Password : $(cat "$CODE_PASSWORD_FILE")"
    echo "Port     : ${CODE_PORT} (localhost)"
    echo
    echo "-- noVNC (Desktop: $(current_de)) --"
    [ -f "$URL_VNC_FILE" ] && echo "URL      : $(cat "$URL_VNC_FILE")/vnc.html"
    [ -f "${STATE_DIR}/vnc-password-plain" ] && echo "Password : $(cat "${STATE_DIR}/vnc-password-plain")"
    echo "VNC port : ${VNC_PORT} | noVNC port : ${NOVNC_PORT}"
    echo
    echo "Log hoat dong noVNC : ${LOG_ACTIVITY}"
    echo "=================================================="
}

status_all() {
    echo "code-server  : $(is_running "$PID_CS" && echo RUNNING || echo STOPPED)"
    echo "tunnel(code) : $(is_running "$PID_CF_CS" && echo RUNNING || echo STOPPED)"
    echo "TigerVNC     : $(vncserver -list 2>/dev/null | grep -q ":${DISPLAY_NUM}" && echo RUNNING || echo STOPPED)"
    echo "noVNC        : $(is_running "$PID_NOVNC" && echo RUNNING || echo STOPPED)"
    echo "tunnel(vnc)  : $(is_running "$PID_CF_VNC" && echo RUNNING || echo STOPPED)"
    echo "activity-log : $(is_running "$PID_ACTLOG" && echo RUNNING || echo STOPPED)"
    echo "Desktop env  : $(current_de)"
    [ -f "$URL_CODE_FILE" ] && echo "code-server URL : $(cat "$URL_CODE_FILE")"
    [ -f "$URL_VNC_FILE" ]  && echo "noVNC URL       : $(cat "$URL_VNC_FILE")/vnc.html"
}

show_logs() {
    echo "1) Activity log (noVNC session)"
    echo "2) code-server log"
    echo "3) noVNC log"
    echo "4) cloudflared (code-server) log"
    echo "5) cloudflared (noVNC) log"
    read -rp "Chon log de xem (tail -n 40) [1-5]: " sel
    case "$sel" in
        1) tail -n 40 "$LOG_ACTIVITY" 2>/dev/null || echo "Chua co log" ;;
        2) tail -n 40 "$LOG_CS" 2>/dev/null || echo "Chua co log" ;;
        3) tail -n 40 "$LOG_NOVNC" 2>/dev/null || echo "Chua co log" ;;
        4) tail -n 40 "$LOG_CF_CS" 2>/dev/null || echo "Chua co log" ;;
        5) tail -n 40 "$LOG_CF_VNC" 2>/dev/null || echo "Chua co log" ;;
        *) warn "Lua chon khong hop le" ;;
    esac
}

# ========================= INSTALL ALL =========================
install_all() {
    install_base_deps
    install_code_server
    install_cloudflared
    install_tigervnc
    install_novnc

    if [ ! -f "$DE_STATE_FILE" ]; then
        switch_de
    else
        ok "Desktop environment da chon truoc do: $(current_de) (dung menu 'Doi giao dien' de doi)"
        write_xstartup
    fi

    write_code_server_config
    setup_vnc_password
    ok "Cai dat hoan tat. Dung 'start' hoac menu 'Khoi dong dich vu' de chay."
}

uninstall_all() {
    stop_all
    read -rp "Go ca goi he thong (xfce4/kde-plasma-desktop/tigervnc)? (y/N): " r
    if [[ "$r" =~ ^[Yy]$ ]]; then
        sudo apt-get remove -y xfce4 xfce4-goodies kde-plasma-desktop tigervnc-standalone-server tigervnc-common >/dev/null 2>&1
    fi
    sudo rm -f /usr/local/bin/cloudflared
    curl -fsSL https://code-server.dev/install.sh | sh -s -- --uninstall >/dev/null 2>&1 || true
    rm -rf "$CS_CONFIG_DIR" "$NOVNC_DIR" "${HOME}/.vnc" "$RUN_DIR" "$STATE_DIR"
    ok "Da go cai dat toan bo"
}

# ========================= MENU =========================
menu() {
    while true; do
        echo
        echo "=================================================="
        echo "   VPS STACK: code-server + VNC/noVNC + Tunnel"
        echo "=================================================="
        echo " 1) Cai dat / Setup toan bo (tu dong bo qua goi da co)"
        echo " 2) Doi Desktop Environment (XFCE / KDE Plasma)"
        echo " 3) Khoi dong tat ca dich vu"
        echo " 4) Dung tat ca dich vu"
        echo " 5) Xem trang thai + URL"
        echo " 6) Xem log (activity / code-server / noVNC / tunnel)"
        echo " 7) Go cai dat"
        echo " 8) Thoat"
        echo "=================================================="
        read -rp "Chon [1-8]: " choice
        case "$choice" in
            1) install_all ;;
            2) switch_de ;;
            3) start_all ;;
            4) stop_all ;;
            5) status_all ;;
            6) show_logs ;;
            7) uninstall_all ;;
            8) exit 0 ;;
            *) warn "Lua chon khong hop le" ;;
        esac
    done
}

# ========================= ENTRYPOINT =========================
ACTION="${1:-menu}"
case "$ACTION" in
    menu)      menu ;;
    install)   install_all ;;
    start)     start_all ;;
    stop)      stop_all ;;
    status)    status_all ;;
    logs)      show_logs ;;
    uninstall) uninstall_all ;;
    *)
        echo "Dung: $0 {menu|install|start|stop|status|logs|uninstall}"
        exit 1
        ;;
esac
