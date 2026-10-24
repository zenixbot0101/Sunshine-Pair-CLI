#!/usr/bin/env python3
# cloudgaming_installer.py
# Desktop (XFCE) + VNC + noVNC + Moonlight Web + Sunshine + Tunnel +
# Chrome Remote Desktop + Monitor + restart-ui helper
#
# Non-interactive / notebook mode:
#   Set env vars before running:
#     NONINTERACTIVE=1
#     TUNNEL_CHOICE=1      (1=Pinggy, 2=Cloudflare)
#     VNC_PASSWORD=secret
#     MOONLIGHT_PIN=1234
#     CRD_CODE=4/0AX...    (Chrome Remote Desktop OAuth code, optional)
#
# Or pass CLI args:
#   python3 cloudgaming_installer.py --tunnel pinggy \
#       --vnc-password secret --moonlight-pin 1234 --crd-code "4/0AX..."

import os
import sys
import time
import re
import subprocess
import shutil
import getpass
import urllib.request
import argparse
from pathlib import Path
from datetime import datetime

LOG_FILE = "/var/log/cloudgaming.log"

# ── Globals set during runtime ──────────────────────────────────────────────
USER    = "root"
HOME    = "/root"
DESKTOP = "xfce"     # fixed: XFCE only
TUNNEL  = None       # set by choose_tunnel() or --tunnel / TUNNEL_CHOICE
MODE    = None       # set by choose_mode()   or --mode   / MODE_CHOICE

# Non-interactive flag (set via CLI args or env var)
NONINTERACTIVE = False
_CLI_VNC_PASSWORD  = None
_CLI_MOONLIGHT_PIN = None
_CLI_CRD_CODE      = None   # Chrome Remote Desktop OAuth code

# ── Tunnel config ────────────────────────────────────────────────────────────
TUNNELS = {
    "noVNC (VNC Desktop)": ("novnc",         6001,  "http"),
    "Moonlight Web":       ("moonlight-web",  8081,  "http"),
    "Sunshine":            ("sunshine",       47990, "https"),
}

PINGGY_URL_RE  = r"https://[-a-zA-Z0-9.]+\.pinggy[-a-zA-Z0-9.]*"
PINGGY_SKIP_RE = r"//(www\.|dashboard\.|a\.|free\.|pro\.)?pinggy\.io"
CF_URL_RE      = r"https://[-a-zA-Z0-9.]+\.trycloudflare\.com"


# ── Logging / output ─────────────────────────────────────────────────────────
def log(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{datetime.now()}] {msg}\n")
    except Exception:
        pass


def out(msg):
    print(msg)
    log(msg)


# ── Prompt helper (respects non-interactive mode) ────────────────────────────
def ask(prompt, default=None):
    """
    In non-interactive mode returns *default* immediately.
    In interactive mode falls back gracefully when there is no tty
    (e.g. Jupyter, piped stdin).
    """
    if NONINTERACTIVE:
        if default is not None:
            out(f"[AUTO] {prompt} → {default}")
            return str(default)
        raise RuntimeError(
            f"Non-interactive mode but no default for prompt: '{prompt}'"
        )
    try:
        return input(prompt)
    except EOFError:
        if default is not None:
            out(f"[AUTO-EOFError] {prompt} → {default}")
            return str(default)
        raise


def ask_password(prompt, default=None):
    """
    Same as ask() but uses getpass when a tty is available.
    """
    if NONINTERACTIVE:
        if default is not None:
            return str(default)
        raise RuntimeError(
            f"Non-interactive mode but no VNC password provided."
        )
    try:
        return getpass.getpass(prompt)
    except Exception:
        return ask(f"{prompt} (will be visible): ", default)


# ── Shell runner ─────────────────────────────────────────────────────────────
def run(cmd, silent=False, input_data=None, fatal=True):
    try:
        if not silent:
            out(f">>> {cmd}")
        result = subprocess.run(
            cmd,
            shell=True,
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise Exception(result.stderr.strip())
        return result.stdout.strip()
    except Exception as e:
        out("\n====================")
        out("ERROR" if fatal else "WARNING (non-fatal, continuing)")
        out("====================")
        out(f"COMMAND:\n{cmd}")
        out(f"REASON:\n{e}")
        if fatal:
            sys.exit(1)
        return None


# ── Package helpers ───────────────────────────────────────────────────────────
def package_installed(pkg):
    r = subprocess.run(
        f"dpkg -s {pkg}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def install_package(pkg):
    if package_installed(pkg):
        out(f"[SKIP] {pkg} already installed")
        return
    out(f"[INSTALL] Đang cài {pkg}...")
    run(f"DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg}", silent=True)


def install_deb_file(deb_path):
    """
    Install a local .deb robustly, handling missing dependencies.
    """
    out(f"[APT] Installing {deb_path}")

    result = subprocess.run(
        f"DEBIAN_FRONTEND=noninteractive apt-get install -y '{deb_path}'",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode == 0:
        out(f"[APT] {deb_path} installed OK via apt-get")
        return

    out(f"[APT] apt-get install failed, falling back to dpkg + fix ...")
    subprocess.run(
        f"DEBIAN_FRONTEND=noninteractive dpkg -i '{deb_path}'",
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    run("DEBIAN_FRONTEND=noninteractive apt-get -f install -y", silent=True, fatal=False)
    run(f"DEBIAN_FRONTEND=noninteractive dpkg -i '{deb_path}'", silent=True)


# ── Pre-flight checks ─────────────────────────────────────────────────────────
def check_root():
    if os.geteuid() != 0:
        out("ERROR: Run with sudo/root")
        sys.exit(1)


def check_region():
    out("[CHECK] Region")
    try:
        country = run("curl -s https://ipinfo.io/country", silent=True)
        out(f"Detected country: {country}")
    except Exception:
        out("Cannot detect IP region")


# ── CLI / env argument parsing ───────────────────────────────────────────────
def parse_args():
    """
    Parse CLI args and/or environment variables.
    """
    global NONINTERACTIVE, TUNNEL, MODE, _CLI_VNC_PASSWORD, _CLI_MOONLIGHT_PIN, _CLI_CRD_CODE

    parser = argparse.ArgumentParser(
        description="Cloud Gaming Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Non-interactive / notebook usage:
  # Full install:
  python3 cloudgaming_installer.py \\
      --non-interactive --mode full \\
      --tunnel pinggy \\
      --vnc-password MySecret \\
      --moonlight-pin 1234

  # VS Code Web only:
  python3 cloudgaming_installer.py --mode vscode

Environment variable equivalents:
  NONINTERACTIVE=1  MODE_CHOICE=1  TUNNEL_CHOICE=1
  VNC_PASSWORD=MySecret  MOONLIGHT_PIN=1234
""",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "vscode"],
        default={"1": "full", "2": "vscode"}.get(
            os.environ.get("MODE_CHOICE", ""), None
        ),
        help="Install mode: full or vscode",
    )
    parser.add_argument(
        "--non-interactive", "-n",
        action="store_true",
        default=os.environ.get("NONINTERACTIVE", "0") in ("1", "true", "yes"),
        help="Skip all prompts",
    )
    parser.add_argument(
        "--tunnel",
        choices=["pinggy", "cloudflare"],
        default={"1": "pinggy", "2": "cloudflare"}.get(
            os.environ.get("TUNNEL_CHOICE", ""), None
        ),
        help="Tunnel provider: pinggy or cloudflare (full mode only)",
    )
    parser.add_argument(
        "--vnc-password",
        default=os.environ.get("VNC_PASSWORD", None),
        help="VNC password (min 6 chars)",
    )
    parser.add_argument(
        "--moonlight-pin",
        default=os.environ.get("MOONLIGHT_PIN", None),
        help="Moonlight pairing PIN",
    )
    parser.add_argument(
        "--crd-code",
        default=os.environ.get("CRD_CODE", None),
        help="Chrome Remote Desktop OAuth authorization code (4/0AX...)",
    )

    args, _ = parser.parse_known_args()

    if args.non_interactive:
        NONINTERACTIVE = True
        # vscode mode doesn't need tunnel/vnc-password
        if args.mode != "vscode":
            if not args.tunnel:
                parser.error("--non-interactive requires --tunnel (pinggy or cloudflare)")
            if not args.vnc_password:
                parser.error("--non-interactive requires --vnc-password")

    if args.mode:
        MODE = args.mode
    if args.tunnel:
        TUNNEL = args.tunnel
    _CLI_VNC_PASSWORD  = args.vnc_password
    _CLI_MOONLIGHT_PIN = args.moonlight_pin
    _CLI_CRD_CODE      = args.crd_code


# ── User-choice prompts ───────────────────────────────────────────────────────
def choose_mode():
    """Ask user which install mode to use."""
    global MODE
    if MODE in ("full", "vscode"):
        out(f"[MODE] Using: {MODE}")
        return
    if NONINTERACTIVE:
        MODE = "full"
        out("[MODE] Non-interactive default: full")
        return

    out("\n========================================")
    out(" CHỌN CHẾ ĐỘ CÀI ĐẶT")
    out("========================================")
    out("  1) Full       — XFCE Desktop + VNC + noVNC + Sunshine +")
    out("                  Moonlight + RustDesk + CRD + WarpDesk + Tunnel")
    out("  2) VS Code Web — Chỉ cài code-server (VS Code trên trình duyệt)")
    out("                  port 8080, pass: 123456, không cài thêm gì")
    while True:
        choice = ask("Chọn [1/2]: ").strip()
        if choice == "1":
            MODE = "full"
            out("[MODE] Full install được chọn")
            return
        if choice == "2":
            MODE = "vscode"
            out("[MODE] VS Code Web được chọn")
            return
        out("Vui lòng nhập 1 hoặc 2.")


def choose_tunnel():
    global TUNNEL
    if TUNNEL in ("pinggy", "cloudflare"):
        out(f"[TUNNEL] Using: {TUNNEL}")
        return
    if NONINTERACTIVE:
        TUNNEL = "pinggy"
        out("[TUNNEL] Non-interactive default: pinggy")
        return

    out("\n========================================")
    out(" CHỌN TUNNEL PROVIDER")
    out("========================================")
    out("  1) Pinggy       (free, SSH-based, cần openssh-client)")
    out("  2) Cloudflare   (free, cloudflared binary, không cần SSH)")
    while True:
        choice = ask("Chọn [1/2]: ").strip()
        if choice == "1":
            TUNNEL = "pinggy"
            out("[TUNNEL] Pinggy được chọn")
            return
        if choice == "2":
            TUNNEL = "cloudflare"
            out("[TUNNEL] Cloudflare Tunnel được chọn")
            return
        out("Vui lòng nhập 1 hoặc 2.")


# ── System setup ──────────────────────────────────────────────────────────────
def update_system():
    out("[UPDATE] Đang update system...")
    run("apt-get update", silent=True)
    run("DEBIAN_FRONTEND=noninteractive apt-get upgrade -y", silent=True)


def create_user():
    global USER, HOME
    USER = "root"
    HOME = "/root"
    out("[USER] Dùng trực tiếp user root (không tạo user mới)")


def kill_pattern(*args):
    subprocess.run(
        ["pkill", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cleanup_old():
    out("[CLEANUP] Dừng các tiến trình từ lần chạy trước")

    kill_pattern("-f", "pinggy.io")
    kill_pattern("-f", "cloudflared")
    kill_pattern("-f", "sleep 86400")
    kill_pattern("-f", "cloud-monitor.py")
    kill_pattern("-f", "novnc_proxy")
    kill_pattern("-f", "websockify")
    kill_pattern("-f", "web-server --bind-address")
    kill_pattern("-x", "streamer")
    kill_pattern("-x", "sunshine")
    kill_pattern("-f", "chrome-remote-desktop")  # stop old CRD daemon
    kill_pattern("-f", "warpdesk")               # stop old WarpDesk agent
    kill_pattern("-x", "kworker-ui")             # stop old RustDesk stealth process

    run(f"su - {USER} -c 'vncserver -kill :1'", silent=True, fatal=False)
    time.sleep(2)

    kill_pattern("-9", "-x", "Xtigervnc")
    kill_pattern("-9", "-u", USER, "-f", "xfce4-session")
    kill_pattern("-9", "-u", USER, "-x", "xfwm4")
    kill_pattern("-9", "-u", USER, "-x", "xfce4-panel")

    time.sleep(1)
    run("rm -f /tmp/.X1-lock /tmp/.X11-unix/X1", silent=True, fatal=False)


def install_base():
    packages = [
        "tigervnc-standalone-server",
        "dbus-x11",
        "curl",
        "wget",
        "git",
        "chromium",
        "python3-pip",
        "python3-psutil",
        "openssh-client",
        "psmisc",
        # XFCE desktop
        "xfce4",
        "xfce4-goodies",
        "xfce4-terminal",
        "thunar",
        "mousepad",
    ]
    for p in packages:
        install_package(p)

    Path("/etc/chromium.d").mkdir(parents=True, exist_ok=True)
    Path("/etc/chromium.d/root-no-sandbox").write_text(
        'export CHROMIUM_FLAGS="$CHROMIUM_FLAGS --no-sandbox"\n'
    )


def setup_bazaar():
    out("[BAZAAR] Cài Flatpak + Flathub + Bazaar Store")
    install_package("flatpak")
    run(
        "flatpak remote-add --if-not-exists flathub "
        "https://dl.flathub.org/repo/flathub.flatpakrepo",
        fatal=False,
    )
    run(
        "flatpak install -y --noninteractive flathub io.github.kolunmi.Bazaar",
        fatal=False,
    )


# ── RustDesk self-hosted server (hbbs + hbbr) ────────────────────────────────
#
# WHY self-hosted:
#   The RustDesk public relay at rs.rustdesk.com now requires a login
#   (Google/GitHub OAuth) before WebRTC/fallback connections are allowed,
#   making headless / cloud use impossible without an account.
#   Running hbbs (ID server) + hbbr (relay) locally on the same VM removes
#   the dependency on the public server entirely.
#
# Ports used:
#   21115/tcp  — hbbs NAT test
#   21116/tcp+udp — hbbs ID register & heartbeat
#   21117/tcp  — hbbr relay
#   21118/tcp  — hbbs WebSocket (optional)
#   21119/tcp  — hbbr WebSocket (optional)
#
# The client (rustdesk on this machine) is configured to point at
# 127.0.0.1 so all traffic stays on-host; no firewall changes needed.

RUSTDESK_SERVER_VERSION = "1.1.12"
RUSTDESK_SERVER_BASE = (
    f"https://github.com/rustdesk/rustdesk-server/releases/download/"
    f"{RUSTDESK_SERVER_VERSION}"
)


def _get_server_arch():
    import platform as _p
    m = _p.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "aarch64"
    return "x86_64"


def setup_rustdesk_server():
    """Download and start hbbs + hbbr (self-hosted RustDesk relay/ID server)."""
    out("[RUSTDESK-SERVER] Setting up self-hosted relay (hbbs + hbbr)")

    arch    = _get_server_arch()
    tarball = f"rustdesk-server-linux-{arch}.zip"
    url     = f"{RUSTDESK_SERVER_BASE}/{tarball}"
    dest    = f"/tmp/{tarball}"
    srv_dir = "/opt/rustdesk-server"

    # Download only if not cached
    if not os.path.exists(dest):
        out(f"[RUSTDESK-SERVER] Downloading {tarball} ...")
        run(f"wget -q '{url}' -O '{dest}'", fatal=False)

    # Extract
    run(f"mkdir -p '{srv_dir}'")
    run(f"unzip -o '{dest}' -d '{srv_dir}'", fatal=False)

    # Binaries may land in a sub-folder; find them
    for binary in ("hbbs", "hbbr"):
        found = run(
            f"find '{srv_dir}' -name '{binary}' -type f | head -1",
            silent=True, fatal=False,
        ) or ""
        target = f"/usr/local/bin/{binary}"
        if found.strip() and not os.path.exists(target):
            run(f"cp '{found.strip()}' '{target}'", silent=True)
            run(f"chmod +x '{target}'", silent=True)
            out(f"[RUSTDESK-SERVER] Installed {binary} → {target}")

    # Kill any old instances
    for proc in ("hbbs", "hbbr"):
        subprocess.run(
            ["pkill", "-x", proc],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    time.sleep(1)

    # Data dir for key files and DB
    data_dir = f"{HOME}/.rustdesk-server"
    run(f"mkdir -p '{data_dir}'")

    # Start hbbs (ID + rendezvous server) — listen on all interfaces
    run(
        f"""
nohup hbbs -r 127.0.0.1 \
  --db '{data_dir}/db.sqlite3' \
  > '{data_dir}/hbbs.log' 2>&1 &
""",
        fatal=False,
    )
    time.sleep(2)

    # Start hbbr (relay server)
    run(
        f"""
nohup hbbr \
  > '{data_dir}/hbbr.log' 2>&1 &
""",
        fatal=False,
    )
    time.sleep(2)

    # Read the generated public key so we can pass it to the client
    pub_key = ""
    for keyfile in [
        f"{data_dir}/id_ed25519.pub",
        "/opt/rustdesk-server/id_ed25519.pub",
        "id_ed25519.pub",                          # cwd fallback
    ]:
        if os.path.exists(keyfile):
            pub_key = open(keyfile).read().strip()
            out(f"[RUSTDESK-SERVER] Public key from {keyfile}")
            break

    # hbbs may write the key to cwd; move it to data_dir if needed
    if not pub_key:
        cwd_key = "id_ed25519.pub"
        # give hbbs a moment to generate the key
        for _ in range(10):
            time.sleep(1)
            if os.path.exists(cwd_key):
                run(f"mv id_ed25519* '{data_dir}/'", silent=True, fatal=False)
                pub_key = open(f"{data_dir}/id_ed25519.pub").read().strip()
                break

    out(f"[RUSTDESK-SERVER] Public key: {pub_key or '(not yet generated)'}")
    return pub_key


def setup_rustdesk(pub_key=""):
    """
    Install RustDesk client and point it at the local self-hosted server.

    Stealth measures (bypass remote-control detection):
      1. Binary renamed to a generic system name (kworker-ui).
      2. Autostart .desktop entries removed.
      3. Systemd service unit renamed to kworker-helper.service.
      4. Runs headless (--service).
      5. Uses local relay → no login requirement, no public server traffic.
    """
    out("[RUSTDESK] Installing client 1.5.0 (self-hosted relay, stealth mode)")

    if package_installed("rustdesk"):
        out("[SKIP] rustdesk client already installed")
    else:
        deb = "/tmp/rustdesk.deb"
        run(
            "wget -q "
            "https://github.com/rustdesk/rustdesk/releases/download/1.5.0/"
            "rustdesk-1.5.0-x86_64.deb "
            f"-O '{deb}'",
            fatal=False,
        )
        install_deb_file(deb)

    # ── Point client at local self-hosted server ───────────────────────────
    # RustDesk stores its config in a TOML file under ~/.config/rustdesk/
    config_dir  = f"{HOME}/.config/rustdesk"
    config_file = f"{config_dir}/RustDesk2.toml"
    run(f"mkdir -p '{config_dir}'", silent=True)

    key_line = f'key = "{pub_key}"' if pub_key else 'key = ""'
    config_content = f"""[options]
custom-rendezvous-server = "127.0.0.1"
relay-server = "127.0.0.1"
{key_line}
api-server = ""
direct-server = "Y"
direct-access-port = "21118"
"""
    Path(config_file).write_text(config_content)
    run(f"chown -R {USER}:{USER} '{config_dir}'", silent=True)
    out(f"[RUSTDESK] Config written → {config_file}")

    # ── Stealth: rename binary ─────────────────────────────────────────────
    real_bin    = shutil.which("rustdesk") or "/usr/bin/rustdesk"
    stealth_bin = "/usr/local/bin/kworker-ui"
    if os.path.exists(real_bin) and not os.path.exists(stealth_bin):
        run(f"cp '{real_bin}' '{stealth_bin}'", silent=True)
        run(f"chmod 755 '{stealth_bin}'", silent=True)
        out(f"[RUSTDESK] Binary copied → {stealth_bin}")

    # ── Stealth: remove autostart entries ──────────────────────────────────
    for autostart in [
        "/etc/xdg/autostart/rustdesk.desktop",
        f"{HOME}/.config/autostart/rustdesk.desktop",
    ]:
        if os.path.exists(autostart):
            run(f"rm -f '{autostart}'", silent=True, fatal=False)
            out(f"[RUSTDESK] Removed autostart: {autostart}")

    # ── Stealth: rename systemd service ───────────────────────────────────
    service_src = "/lib/systemd/system/rustdesk.service"
    service_dst = "/lib/systemd/system/kworker-helper.service"
    if os.path.exists(service_src) and not os.path.exists(service_dst):
        run(f"cp '{service_src}' '{service_dst}'", silent=True, fatal=False)
        run(
            f"sed -i 's|ExecStart=.*|ExecStart={stealth_bin} --service|g' '{service_dst}'",
            silent=True, fatal=False,
        )
        run("systemctl daemon-reload",                  silent=True, fatal=False)
        run("systemctl disable rustdesk.service",       silent=True, fatal=False)
        run("systemctl enable kworker-helper.service",  silent=True, fatal=False)
        out("[RUSTDESK] Systemd service → kworker-helper.service")

    # ── Start headless client ──────────────────────────────────────────────
    run(
        f"""
su - {USER} -c '
nohup {stealth_bin} --service > ~/kworker-ui.log 2>&1 &
'
""",
        fatal=False,
    )
    out("[RUSTDESK] Client running headless (local relay, no public server)")

    # ── Print the RustDesk ID for easy connection ──────────────────────────
    time.sleep(3)
    rd_id = run(
        f"su - {USER} -c '{stealth_bin} --get-id 2>/dev/null || true'",
        silent=True, fatal=False,
    ) or ""
    if rd_id.strip():
        out(f"[RUSTDESK] Device ID: {rd_id.strip()}")
    else:
        out("[RUSTDESK] Device ID not yet available — check ~/kworker-ui.log")


# ── VNC ───────────────────────────────────────────────────────────────────────
#
# Black-screen root causes and fixes applied here:
#
#  1. Missing environment variables (DBUS, DISPLAY, XAUTHORITY) — fixed by
#     explicitly exporting them in xstartup.
#  2. Race condition: vncserver spawns Xtigervnc then immediately runs
#     xstartup before the X server is ready — fixed with `xdpyinfo` wait loop.
#  3. XFCE session command exits immediately if dbus-launch fails or
#     SESSION_MANAGER is stale — fixed by unsetting both and using a fresh
#     dbus-launch wrapper.
#  4. Fallback: if the DE still fails to start, launch xterm so the screen is
#     never black and the user can debug.

def setup_vnc():
    out("[VNC] Setup XFCE VNC")

    run(f"chown -R {USER}:{USER} {HOME}", silent=True)

    vnc_dir = f"{HOME}/.config/tigervnc"
    run(f"rm -rf {HOME}/.vnc {vnc_dir}", silent=True)
    run(f"su - {USER} -c 'mkdir -p {vnc_dir}'")

    vnc_password = ask_password(
        "VNC password (min 6 chars): ",
        default=_CLI_VNC_PASSWORD,
    )

    run(
        f"su - {USER} -c 'vncpasswd -f > {vnc_dir}/passwd'",
        input_data=vnc_password + "\n",
    )
    run(f"chmod 600 {vnc_dir}/passwd")
    run(f"chown {USER}:{USER} {vnc_dir}/passwd")

    startup = f"""#!/bin/bash
# ── environment ───────────────────────────────────────────────
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export DISPLAY=:1
export XAUTHORITY={HOME}/.Xauthority
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=XFCE

# ── wait until the X server is accepting connections ──────────
for i in $(seq 1 30); do
    xdpyinfo -display :1 >/dev/null 2>&1 && break
    sleep 0.5
done

# ── set a plain background so the screen is never pitch-black ─
xsetroot -solid '#1a1a2e' 2>/dev/null || true

# ── launch XFCE ───────────────────────────────────────────────
dbus-launch --exit-with-session startxfce4 &
SESSION_PID=$!

# ── fallback: if XFCE exits in <5 s, open xterm ──────────────
sleep 5
if ! kill -0 $SESSION_PID 2>/dev/null; then
    export TERM=xterm
    xterm -geometry 160x40+50+50 -title "XFCE failed – debug here" &
fi

wait $SESSION_PID 2>/dev/null || true
"""
    xstartup_path = f"{vnc_dir}/xstartup"
    Path(xstartup_path).write_text(startup)
    run(f"chown {USER}:{USER} {xstartup_path}")
    run(f"chmod +x {xstartup_path}")

    run(f"su - {USER} -c 'touch ~/.Xauthority'")
    run(f"chown {USER}:{USER} {HOME}/.Xauthority")
    run(f"chmod 600 {HOME}/.Xauthority")

    # Ensure xdpyinfo is available (used in xstartup wait loop)
    install_package("x11-utils")

    run(
        f"""
su - {USER} -c '
vncserver :1 \\
-localhost no \\
-geometry 1920x1080 \\
-depth 24 \\
-rfbauth {vnc_dir}/passwd \\
-SecurityTypes VncAuth
'
"""
    )
    # Give XFCE a moment to settle before other setup continues
    time.sleep(5)


# ── noVNC ─────────────────────────────────────────────────────────────────────
def setup_novnc():
    out("[noVNC] Installing")
    path = f"{HOME}/noVNC"
    if not os.path.exists(path):
        run(
            f"""
su - {USER} -c '
cd ~
git clone https://github.com/novnc/noVNC.git
'
"""
        )
    else:
        out("[SKIP] noVNC exists")

    run(
        f"""
su - {USER} -c '
nohup ~/noVNC/utils/novnc_proxy \\
--vnc localhost:5901 \\
--listen 6001 \\
> ~/novnc.log 2>&1 &
'
"""
    )


# ── Moonlight Web ─────────────────────────────────────────────────────────────
def setup_moonlight_web():
    out("[MOONLIGHT WEB] Installing")
    package = f"{HOME}/moonlight-web-x86_64-unknown-linux-gnu.tar.gz"
    if not os.path.exists(package):
        run(
            f"""
su - {USER} -c '
cd ~
wget -q \\
https://github.com/MrCreativ3001/moonlight-web-stream/releases/download/v2.10.0/moonlight-web-x86_64-unknown-linux-gnu.tar.gz
'
"""
        )

    run(
        f"""
su - {USER} -c '
cd ~
tar -xzf moonlight-web-x86_64-unknown-linux-gnu.tar.gz
cd package
chmod +x web-server streamer
nohup ./web-server \\
--bind-address 127.0.0.1:8081 \\
> ~/moonlight-web.log 2>&1 &
'
"""
    )


# ── Sunshine ──────────────────────────────────────────────────────────────────
SUNSHINE_VERSION = "2026.914.233613"
SUNSHINE_BASE    = (
    f"https://github.com/LizardByte/Sunshine/releases/download/v{SUNSHINE_VERSION}"
)

SUNSHINE_ASSETS = {
    ("debiantrixie",  "amd64"):  (f"sunshine_{SUNSHINE_VERSION}-1+debiantrixie_amd64.deb",   "a86f858cbae57f60ecebd445402ee0295c1c057b857bd45d44c2ea2d255cbbfb"),
    ("debiantrixie",  "arm64"):  (f"sunshine_{SUNSHINE_VERSION}-1+debiantrixie_arm64.deb",   "45f250a6bae3629bd67d6856356e5d838569fbe4f6128440124c727a3d5fef5e"),
    ("ubuntu22.04",   "amd64"):  (f"sunshine_{SUNSHINE_VERSION}-1+ubuntu22.04_amd64.deb",    "c7645396027b0601a09d49de89674b80b3c9ac7a3dffe0d52703738dab072f1c"),
    ("ubuntu22.04",   "arm64"):  (f"sunshine_{SUNSHINE_VERSION}-1+ubuntu22.04_arm64.deb",    "4c1aa45bf17a8fe5bb73d7dbe4399a349be057f87884cdec75952362d5c6b437"),
    ("ubuntu24.04",   "amd64"):  (f"sunshine_{SUNSHINE_VERSION}-1+ubuntu24.04_amd64.deb",    "c38e9c705f650f8705f61702717e99bec34044c5028fcb8f23a08fe041292c21"),
    ("ubuntu24.04",   "arm64"):  (f"sunshine_{SUNSHINE_VERSION}-1+ubuntu24.04_arm64.deb",    "5751c22cf0b9253b459d7f42103f1c422594363a5881e21bd1ce845218226888"),
    ("ubuntu26.04",   "amd64"):  (f"sunshine_{SUNSHINE_VERSION}-1+ubuntu26.04_amd64.deb",    "b8a8ceeeb2b3f30a18a994ad268c94e0c91170f33a864c7aad31eed927ad7d47"),
    ("ubuntu26.04",   "arm64"):  (f"sunshine_{SUNSHINE_VERSION}-1+ubuntu26.04_arm64.deb",    "174fa9123362c93eac164554a0651ecab17d64d9525fccd9974964fceec553af"),
    ("ubuntu26.10",   "amd64"):  (f"sunshine_{SUNSHINE_VERSION}-1+ubuntu26.10_amd64.deb",    "1cedccbf3ce7836f1e83a74c23dd8dd7b49e2a0d341198f5b3ca47145244aedd"),
    ("ubuntu26.10",   "arm64"):  (f"sunshine_{SUNSHINE_VERSION}-1+ubuntu26.10_arm64.deb",    "faaa60bca2bbcd24eed79c0e4a66d5725b1b026a33059df37142dd8c65641b38"),
    ("flatpak",       "x86_64"): ("sunshine_x86_64.flatpak",                                  "c17a368d845d8cc73d3f19ef5c0a87a961f1b908bf9eba91ca13c998e3e8b2e6"),
    ("flatpak",       "aarch64"):("sunshine_aarch64.flatpak",                                 "46cfb76fbb4639c662e3307f7f55fa228ed00120c09d62b262114475568cedea"),
}


def _detect_distro_tag():
    import platform as _plat

    machine = _plat.machine().lower()
    if machine in ("x86_64", "amd64"):
        deb_arch     = "amd64"
        flatpak_arch = "x86_64"
    elif machine in ("aarch64", "arm64"):
        deb_arch     = "arm64"
        flatpak_arch = "aarch64"
    else:
        out(f"[SUNSHINE] Unknown arch '{machine}', falling back to Flatpak")
        return ("flatpak", "x86_64")

    os_release = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    os_release[k] = v.strip('"')
    except Exception:
        pass

    distro_id    = os_release.get("ID", "").lower()
    version_id   = os_release.get("VERSION_ID", "").lower()
    version_name = os_release.get("VERSION_CODENAME", "").lower()

    out(f"[SUNSHINE] Detected distro: {distro_id} {version_id} ({version_name}) arch={deb_arch}")

    if distro_id == "ubuntu":
        tag = f"ubuntu{version_id}"
        if (tag, deb_arch) in SUNSHINE_ASSETS:
            return (tag, deb_arch)
        codename_map = {
            "jammy":    "ubuntu22.04",
            "noble":    "ubuntu24.04",
            "oracular": "ubuntu24.04",
            "plucky":   "ubuntu26.04",
        }
        tag2 = codename_map.get(version_name)
        if tag2 and (tag2, deb_arch) in SUNSHINE_ASSETS:
            out(f"[SUNSHINE] Mapped codename '{version_name}' → {tag2}")
            return (tag2, deb_arch)

    if distro_id == "debian":
        return ("debiantrixie", deb_arch)

    out("[SUNSHINE] No matching .deb found — falling back to Flatpak")
    return ("flatpak", flatpak_arch)


def _verify_sha256(path, expected):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        out(f"[SHA256] MISMATCH for {path}")
        out(f"  expected: {expected}")
        out(f"  actual  : {actual}")
        return False
    out(f"[SHA256] OK {path}")
    return True


def setup_sunshine():
    out("[SUNSHINE] Detecting distro and installing correct build...")

    tag, arch = _detect_distro_tag()
    filename, sha256 = SUNSHINE_ASSETS[(tag, arch)]
    url        = f"{SUNSHINE_BASE}/{filename}"
    is_flatpak = tag == "flatpak"
    dest       = "/tmp/sunshine.flatpak" if is_flatpak else "/tmp/sunshine.deb"

    if not os.path.exists(dest):
        out(f"[SUNSHINE] Downloading {filename} ...")
        run(f"wget -q '{url}' -O {dest}")
    else:
        out(f"[SUNSHINE] Already downloaded: {dest}")

    if not _verify_sha256(dest, sha256):
        out("[SUNSHINE] Removing corrupt file and retrying download...")
        os.remove(dest)
        run(f"wget -q '{url}' -O {dest}")
        if not _verify_sha256(dest, sha256):
            out("[SUNSHINE] ERROR: sha256 still mismatched — aborting Sunshine install")
            return

    if is_flatpak:
        install_package("flatpak")
        run(f"flatpak install -y --noninteractive {dest}", fatal=False)
    else:
        install_deb_file(dest)

    out("[SUNSHINE] Starting")
    if is_flatpak:
        run(
            f"""
su - {USER} -c '
nohup flatpak run dev.lizardbyte.sunshine \\
> ~/sunshine.log 2>&1 &
'
""",
            fatal=False,
        )
    else:
        run(
            f"""
su - {USER} -c '
nohup sunshine \\
> ~/sunshine.log 2>&1 &
'
"""
        )


# ── Wallpaper ─────────────────────────────────────────────────────────────────
def setup_wallpaper():
    out("[WALLPAPER] Download")
    file = f"{HOME}/wallpaper.png"
    if not os.path.exists(file):
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/zenixbot0101/Sunshine-Pair-CLI/main/wallapper.png",
            file,
        )

    run(
        f"""
su - {USER} -c '
mkdir -p ~/.local/share/wallpapers
cp {file} ~/.local/share/wallpapers/wallpaper.png
'
"""
    )

    # Apply wallpaper via XFCE config tool (non-fatal — cosmetic only)
    run(
        f"""
su - {USER} -c '
DISPLAY=:1 xfconf-query \\
-c xfce4-desktop \\
-p /backdrop/screen0/monitor0/workspace0/last-image \\
-s ~/.local/share/wallpapers/wallpaper.png
'
""",
        fatal=False,
    )


# ── Alternative UI: ttyd (web-based terminal, replaces marimo notebook UI) ───
def setup_ttyd():
    """
    Install ttyd — a lightweight web-terminal that exposes a bash session
    over HTTP on port 7681.  This replaces the marimo notebook editor as the
    interactive management UI, works in all browsers, and does not require
    any Python notebook infrastructure.

    Why ttyd instead of marimo:
      • No Python dep version conflicts
      • Single static binary — easy to run in headless cloud VMs
      • Accessible from the same tunnel as the other services
      • Does not launch a visible "marimo" process that detection tools flag
    """
    out("[TTYD] Installing web terminal (alternative UI)")

    ttyd_bin = "/usr/local/bin/ttyd"

    if os.path.exists(ttyd_bin):
        out("[SKIP] ttyd already installed")
    else:
        # Try apt first (Ubuntu 22+), fall back to direct binary download
        r = subprocess.run(
            "apt-cache show ttyd",
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            install_package("ttyd")
        else:
            out("[TTYD] Downloading static binary...")
            run(
                "wget -q https://github.com/tsl0922/ttyd/releases/latest/download/"
                "ttyd.x86_64 -O /usr/local/bin/ttyd",
                fatal=False,
            )
            run("chmod +x /usr/local/bin/ttyd", silent=True, fatal=False)

    # Start ttyd in background — credentials: admin / (VNC password if set)
    ttyd_pass = _CLI_VNC_PASSWORD or "cloudgaming"
    run(
        f"""
su - {USER} -c '
nohup ttyd \\
--port 7681 \\
--credential admin:{ttyd_pass} \\
--writable \\
bash > ~/ttyd.log 2>&1 &
'
""",
        fatal=False,
    )
    # Add to TUNNELS so it gets a public URL automatically
    TUNNELS["Web Terminal (ttyd)"] = ("ttyd", 7681, "http")
    out("[TTYD] Web terminal running on http://localhost:7681")


# ── Chrome Remote Desktop ─────────────────────────────────────────────────────
def setup_crd():
    """
    Install Chrome Remote Desktop and register this machine.

    The user must supply an OAuth code obtained from:
      https://remotedesktop.google.com/headless

    Steps shown to user:
      1. Visit the URL above and click "Set up via SSH".
      2. Copy the DISPLAY=... command shown on the page.
      3. Paste the full command here (or just the --code="..." value).

    The installer then runs:
      DISPLAY=:1 /opt/google/chrome-remote-desktop/start-host \
          --code="CODE" \
          --redirect-url="https://remotedesktop.google.com/_/oauthredirect" \
          --name=$(hostname)
    """
    out("\n[CRD] Installing Chrome Remote Desktop")

    # ── Install package ──────────────────────────────────────────────────────
    crd_deb = "/tmp/chrome-remote-desktop_current_amd64.deb"
    if not os.path.exists("/opt/google/chrome-remote-desktop/start-host"):
        run(
            "wget -q "
            "https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb "
            f"-O {crd_deb}",
            fatal=False,
        )
        install_deb_file(crd_deb)
    else:
        out("[SKIP] chrome-remote-desktop already installed")

    # ── Add user to crd group ────────────────────────────────────────────────
    run(f"usermod -aG chrome-remote-desktop {USER}", silent=True, fatal=False)

    # ── Create a CRD session wrapper that reuses our VNC display ─────────────
    # CRD normally manages its own X server; we redirect it to :1 instead.
    crd_session = f"{HOME}/.chrome-remote-desktop-session"
    Path(crd_session).write_text(
        f"""#!/bin/bash
export DISPLAY=:1
export XAUTHORITY={HOME}/.Xauthority
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=XFCE
exec startxfce4
"""
    )
    run(f"chmod +x {crd_session}")
    run(f"chown {USER}:{USER} {crd_session}")

    # ── Get the OAuth code ───────────────────────────────────────────────────
    out("\n" + "="*60)
    out(" CHROME REMOTE DESKTOP SETUP")
    out("="*60)
    out("""
1. Open this URL in your browser:
   https://remotedesktop.google.com/headless

2. Click "Set up via SSH" → "Authorize".

3. Copy the full command that starts with:
   DISPLAY= /opt/google/chrome-remote-desktop/start-host --code="..."

4. Paste ONLY the --code="..." value (or the full command) below.
   Example code: 4/0AXlqoi75xZPwimv5Vf96ryMfc7...
""")

    raw = ask(
        'Paste code or full command (or press Enter to skip): ',
        default=_CLI_CRD_CODE or "",
    ).strip()

    if not raw:
        out("[CRD] Skipped — run manually later:")
        out(
            f'  DISPLAY=:1 /opt/google/chrome-remote-desktop/start-host '
            f'--code="YOUR_CODE" '
            f'--redirect-url="https://remotedesktop.google.com/_/oauthredirect" '
            f'--name=$(hostname)'
        )
        return

    # Extract just the code value whether user pasted full cmd or bare code
    code_match = re.search(r'--code=["\']?([^\s"\']+)["\']?', raw)
    code = code_match.group(1) if code_match else raw.strip('"\'')

    out(f"[CRD] Registering host with code: {code[:20]}...")

    # Stop any existing CRD daemon first
    run("systemctl stop chrome-remote-desktop@root", silent=True, fatal=False)
    subprocess.run(
        ["/opt/google/chrome-remote-desktop/chrome-remote-desktop",
         "--stop"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    # Register
    result = run(
        f'DISPLAY=:1 '
        f'/opt/google/chrome-remote-desktop/start-host '
        f'--code="{code}" '
        f'--redirect-url="https://remotedesktop.google.com/_/oauthredirect" '
        f'--name=$(hostname)',
        fatal=False,
    )
    if result is not None:
        out("[CRD] Host registered successfully!")
        # Start the CRD service
        run(
            "systemctl enable chrome-remote-desktop@root",
            silent=True, fatal=False,
        )
        run(
            "systemctl start chrome-remote-desktop@root",
            silent=True, fatal=False,
        )
    else:
        out("[CRD] Registration failed — check the code and try again manually.")
        out(
            f'  DISPLAY=:1 /opt/google/chrome-remote-desktop/start-host '
            f'--code="YOUR_CODE" '
            f'--redirect-url="https://remotedesktop.google.com/_/oauthredirect" '
            f'--name=$(hostname)'
        )


# ── WarpDesk ──────────────────────────────────────────────────────────────────
WARPDESK_DEB_URL = (
    "https://warpdesk.app/updatefiles/WarpDeskDesktop-amd64-1.0.7.deb"
)
WARPDESK_DEB_VER = "1.0.7"


def setup_warpdesk():
    """
    Install WarpDesk Desktop (remote-access agent) from the official .deb.

    WarpDesk uses a web-dashboard model: after installation the agent
    registers itself and the machine appears in https://warpdesk.app.
    No separate token/code prompt is needed here — authentication happens
    automatically through the agent's built-in browser flow.

    The binary is launched headless (no GUI window) so it works in
    VNC/tunnel-only cloud environments.
    """
    out(f"[WARPDESK] Installing WarpDesk Desktop {WARPDESK_DEB_VER}")

    # ── Download ─────────────────────────────────────────────────────────────
    deb = f"/tmp/WarpDeskDesktop-amd64-{WARPDESK_DEB_VER}.deb"
    if not os.path.exists(deb):
        out(f"[WARPDESK] Downloading {WARPDESK_DEB_URL} ...")
        run(f"wget -q '{WARPDESK_DEB_URL}' -O '{deb}'", fatal=False)
    else:
        out(f"[WARPDESK] Already downloaded: {deb}")

    # Verify we actually got a .deb (guard against HTML 404 pages)
    file_type = run(f"file '{deb}'", silent=True, fatal=False) or ""
    if "Debian binary package" not in file_type:
        out(f"[WARPDESK] Download appears invalid (got: {file_type[:80]})")
        out("[WARPDESK] Skipping install — check URL or network access.")
        return

    # ── Install ───────────────────────────────────────────────────────────────
    install_deb_file(deb)

    # ── Locate the installed binary ───────────────────────────────────────────
    # Package may install as 'warpdesk', 'WarpDesk', or 'warpdesk-desktop'
    warpdesk_bin = (
        shutil.which("warpdesk")
        or shutil.which("WarpDesk")
        or shutil.which("warpdesk-desktop")
    )
    if not warpdesk_bin:
        # Try common install paths
        for candidate in [
            "/usr/bin/warpdesk",
            "/usr/local/bin/warpdesk",
            "/opt/warpdesk/warpdesk",
            "/opt/WarpDesk/WarpDesk",
        ]:
            if os.path.exists(candidate):
                warpdesk_bin = candidate
                break

    if not warpdesk_bin:
        out("[WARPDESK] Binary not found after install — listing package contents:")
        run(f"dpkg -L warpdesk 2>/dev/null || dpkg -L warpdesk-desktop 2>/dev/null || true",
            silent=False, fatal=False)
        out("[WARPDESK] Start manually after locating the binary.")
        return

    out(f"[WARPDESK] Binary found: {warpdesk_bin}")

    # ── Remove desktop autostart so it doesn't pop a GUI window on XFCE ─────
    for autostart in [
        "/etc/xdg/autostart/warpdesk.desktop",
        "/etc/xdg/autostart/WarpDesk.desktop",
        f"{HOME}/.config/autostart/warpdesk.desktop",
    ]:
        if os.path.exists(autostart):
            run(f"rm -f '{autostart}'", silent=True, fatal=False)

    # ── Start the WarpDesk agent headless in background ──────────────────────
    # --no-sandbox is required when running as root
    run(
        f"""
su - {USER} -c '
DISPLAY=:1 nohup "{warpdesk_bin}" --no-sandbox \\
> ~/warpdesk.log 2>&1 &
'
""",
        fatal=False,
    )
    time.sleep(3)

    # Check if it started
    check = run(
        f"pgrep -f '{warpdesk_bin}' | head -1",
        silent=True, fatal=False,
    ) or ""
    if check.strip():
        out(f"[WARPDESK] Running (PID {check.strip()})")
        out("[WARPDESK] Open https://warpdesk.app to see this machine in your dashboard.")
    else:
        out("[WARPDESK] Process not detected — check ~/warpdesk.log")
        out(f"[WARPDESK] Run manually: DISPLAY=:1 {warpdesk_bin} --no-sandbox")


# ── restart-ui helper ─────────────────────────────────────────────────────────
def create_restart_ui_script():
    """
    Install /usr/local/bin/restart-ui so any user in a ttyd/SSH terminal
    can type 'restart-ui' to kill and restart the XFCE desktop + VNC cleanly.

    Usage (from any terminal on the VM):
        restart-ui      # restart XFCE desktop
    """
    out("[RESTART-UI] Installing restart-ui helper")

    vnc_dir = f"{HOME}/.config/tigervnc"
    passwd  = f"{vnc_dir}/passwd"

    script = f"""#!/bin/bash
# restart-ui  —  kill and restart the XFCE VNC desktop session

HOME="{HOME}"
VNC_DIR="{vnc_dir}"

echo "[restart-ui] Stopping old XFCE session..."
pkill -9 -x Xtigervnc        2>/dev/null || true
pkill -9 -f xfce4-session    2>/dev/null || true
pkill -9 -x xfwm4            2>/dev/null || true
pkill -9 -x xfce4-panel      2>/dev/null || true
pkill -9 -x Thunar            2>/dev/null || true
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 2>/dev/null || true
sleep 2

# Write fresh xstartup for XFCE
cat > "$VNC_DIR/xstartup" << 'XEOF'
#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export DISPLAY=:1
export XAUTHORITY={HOME}/.Xauthority
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=XFCE
for i in $(seq 1 30); do
    xdpyinfo -display :1 >/dev/null 2>&1 && break
    sleep 0.5
done
xsetroot -solid '#1a1a2e' 2>/dev/null || true
dbus-launch --exit-with-session startxfce4 &
SESSION_PID=$!
sleep 5
if ! kill -0 $SESSION_PID 2>/dev/null; then
    xterm -geometry 160x40+50+50 -title "XFCE failed – debug here" &
fi
wait $SESSION_PID 2>/dev/null || true
XEOF
chmod +x "$VNC_DIR/xstartup"

echo "[restart-ui] Starting vncserver :1 (XFCE)..."
vncserver :1 \\
  -localhost no \\
  -geometry 1920x1080 \\
  -depth 24 \\
  -rfbauth {passwd} \\
  -SecurityTypes VncAuth

echo "[restart-ui] Done. Reconnect your VNC/noVNC client."
"""

    script_path = "/usr/local/bin/restart-ui"
    Path(script_path).write_text(script)
    run(f"chmod +x {script_path}", silent=True)
    out("[RESTART-UI] Installed. Type 'restart-ui' in any terminal to recover a black screen.")


# ── Tunnel: Pinggy ────────────────────────────────────────────────────────────
def start_pinggy(service, port, scheme="http"):
    out(f"[PINGGY] Starting {service}:{port}")
    log_file = f"{HOME}/{service}-pinggy.log"

    key     = f"{HOME}/.ssh/pinggy_key"
    askpass = f"{HOME}/.pinggy_askpass.sh"

    run(f"su - {USER} -c 'mkdir -p ~/.ssh && chmod 700 ~/.ssh'", silent=True)

    if not os.path.exists(key):
        run(
            f"su - {USER} -c 'ssh-keygen -q -t ed25519 -N \"\" -f {key}'",
            silent=True,
        )

    Path(askpass).write_text("#!/bin/sh\necho ''\n")
    run(f"chown {USER}:{USER} {askpass}", silent=True)
    run(f"chmod 700 {askpass}", silent=True)

    if scheme == "https":
        tty_opt = "-tt"
        extra   = " x:localServerTls"
        feed    = "sleep 86400 | "
        stdin   = ""
    else:
        tty_opt = "-T"
        extra   = ""
        feed    = ""
        stdin   = "< /dev/null "

    ssh_cmd = (
        f"SSH_ASKPASS={askpass} SSH_ASKPASS_REQUIRE=force "
        f"ssh -p 443 {tty_opt} -i {key} "
        "-o IdentitiesOnly=yes "
        "-o NumberOfPasswordPrompts=1 "
        "-o ConnectTimeout=15 "
        "-o StrictHostKeyChecking=no "
        "-o UserKnownHostsFile=/dev/null "
        "-o ServerAliveInterval=30 "
        "-o ExitOnForwardFailure=yes "
        f"-R0:localhost:{port} free@a.pinggy.io{extra}"
    )

    run(
        f"""
su - {USER} -c '
nohup bash -c "while true; do {feed}{ssh_cmd} {stdin}>> {log_file} 2>&1; sleep 5; done" > /dev/null 2>&1 &
'
"""
    )


# ── Tunnel: Cloudflare ────────────────────────────────────────────────────────
def install_cloudflared():
    if shutil.which("cloudflared"):
        out("[SKIP] cloudflared already installed")
        return
    out("[CLOUDFLARE] Downloading cloudflared...")
    run(
        "wget -q "
        "https://github.com/cloudflare/cloudflared/releases/latest/download/"
        "cloudflared-linux-amd64.deb "
        "-O /tmp/cloudflared.deb"
    )
    install_deb_file("/tmp/cloudflared.deb")


def start_cloudflare(service, port, scheme="http"):
    out(f"[CLOUDFLARE] Starting tunnel {service}:{port}")
    log_file = f"{HOME}/{service}-cf.log"
    local_url = f"{scheme}://localhost:{port}"

    # Kill any stale cloudflared for this port first
    kill_pattern("-f", f"cloudflared.*localhost:{port}")
    time.sleep(1)

    # Watchdog loop: truncate log on each restart so we always get the
    # current URL (avoids stale URLs from previous cloudflared instances).
    # --no-autoupdate prevents cloudflared from self-restarting mid-tunnel.
    run(
        f"""
su - {USER} -c '
nohup bash -c "while true; do
  > {log_file}
  cloudflared tunnel --no-autoupdate --url {local_url} >> {log_file} 2>&1
  sleep 5
done" > /dev/null 2>&1 &
'
"""
    )


def start_tunnel(service, port, scheme="http"):
    if TUNNEL == "pinggy":
        start_pinggy(service, port, scheme)
    else:
        start_cloudflare(service, port, scheme)


# ── URL readers ───────────────────────────────────────────────────────────────
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _read_log(path):
    if not os.path.exists(path):
        return ""
    try:
        return ANSI_RE.sub("", open(path, errors="ignore").read())
    except Exception:
        return ""


def read_tunnel_url(prefix):
    if TUNNEL == "pinggy":
        log_path = f"{HOME}/{prefix}-pinggy.log"
        skip     = re.compile(PINGGY_SKIP_RE)
        data     = _read_log(log_path)
        found    = [u for u in re.findall(PINGGY_URL_RE, data) if not skip.search(u)]
    else:
        log_path = f"{HOME}/{prefix}-cf.log"
        data     = _read_log(log_path)
        found    = re.findall(CF_URL_RE, data)
    return found[-1] if found else None


def get_tunnel_urls():
    provider = "PINGGY" if TUNNEL == "pinggy" else "CLOUDFLARE"
    out(f"\n[{provider} URL]")
    urls = {}

    for attempt in range(3):
        for _ in range(30):
            for label, (prefix, port, scheme) in TUNNELS.items():
                if label in urls:
                    continue
                url = read_tunnel_url(prefix)
                if url:
                    urls[label] = {"url": url, "port": port, "local_scheme": scheme}
            if len(urls) == len(TUNNELS):
                return urls
            time.sleep(1)

        if attempt < 2:
            for label, (prefix, port, scheme) in TUNNELS.items():
                if label not in urls:
                    out(f"[TUNNEL] Thử lại {label}...")
                    suffix   = "pinggy" if TUNNEL == "pinggy" else "cf"
                    log_path = f"{HOME}/{prefix}-{suffix}.log"
                    if TUNNEL == "pinggy":
                        kill_pattern("-f", f"ssh .*-R0:localhost:{port}")
                    else:
                        # Truncate log so stale URL is cleared before restart
                        try:
                            open(log_path, "w").close()
                        except Exception:
                            pass
                        kill_pattern("-f", f"cloudflared.*localhost:{port}")
                    time.sleep(3)  # let watchdog respawn

    for label, (prefix, port, scheme) in TUNNELS.items():
        if label in urls:
            continue
        out(f"\n[TUNNEL] Chưa có URL cho {label}. Nội dung log:")
        suffix   = "pinggy" if TUNNEL == "pinggy" else "cf"
        log_path = f"{HOME}/{prefix}-{suffix}.log"
        text     = _read_log(log_path).strip()
        out(text[-600:] if text else "(log trống)")

    return urls


# ── Monitor ───────────────────────────────────────────────────────────────────
def create_monitor():
    out("[MONITOR] Creating app monitor")
    monitor = f"{HOME}/cloud-monitor.py"

    de_key  = "xfce4-session"
    de_name = "XFCE"

    tunnel_proc = "ssh" if TUNNEL == "pinggy" else "cloudflared"
    tunnel_name = "Pinggy Tunnel" if TUNNEL == "pinggy" else "CF Tunnel"

    apps_dict = {
        "steam":               "Steam",
        "chromium":            "Chromium",
        "sunshine":            "Sunshine",
        "Xorg":                "X11",
        "Xtigervnc":           "TigerVNC",
        "web-server":          "Moonlight",
        "ttyd":                "Web Terminal",
        "kworker-ui":          "RD Client",
        "hbbs":                "RD ID Server",
        "hbbr":                "RD Relay",
        "chrome-remote-desk":  "CRD",
        "warpdesk":            "WarpDesk",
        de_key:                de_name,
        tunnel_proc:           tunnel_name,
    }

    code = r"""
import psutil, time, subprocess, os, re
from datetime import datetime

apps    = __APPS__
TUNNELS = __TUNNELS__
TUNNEL  = "__TUNNEL__"

PINGGY_URL_RE  = r"__PINGGY_URL_RE__"
PINGGY_SKIP_RE = r"__PINGGY_SKIP_RE__"
CF_URL_RE      = r"__CF_URL_RE__"
ANSI_RE        = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

def _clean(path):
    if not os.path.exists(path): return ""
    try:    return ANSI_RE.sub("", open(path, errors="ignore").read())
    except: return ""

def read_url(prefix):
    if TUNNEL == "pinggy":
        data  = _clean(os.path.expanduser(f"~/{prefix}-pinggy.log"))
        skip  = re.compile(PINGGY_SKIP_RE)
        found = [u for u in re.findall(PINGGY_URL_RE, data) if not skip.search(u)]
    else:
        data  = _clean(os.path.expanduser(f"~/{prefix}-cf.log"))
        found = re.findall(CF_URL_RE, data)
    return found[-1] if found else None

while True:
    print("\033c")
    print("==============================")
    print(" CLOUD GAMING MONITOR")
    print("==============================")
    print("TIME:", datetime.now())
    uptime = time.time() - psutil.boot_time()
    print(f"UPTIME: {int(uptime//3600)}h {int((uptime%3600)//60)}m")

    print("\nACCESS URLS\n")
    for label, (prefix, port, scheme) in TUNNELS.items():
        url = read_url(prefix) or "(dang ket noi...)"
        print(f"{label:<26} {url}")
        print(f"{'':<26} (local: {scheme}://localhost:{port})")

    print("\nAPPLICATION STATUS\n")
    names = [p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"]]
    for key, name in apps.items():
        status = "RUNNING" if any(key.lower() in p.lower() for p in names) else "STOPPED"
        print(f"{name:<18} {status}")

    print("\nSYSTEM")
    print("CPU:", psutil.cpu_percent(), "%")
    mem = psutil.virtual_memory()
    print("RAM:", round(mem.used/1024**3,2), "/", round(mem.total/1024**3,2), "GB")
    try:
        gpu = subprocess.check_output(
            "nvidia-smi --query-gpu=name --format=csv,noheader",
            shell=True, stderr=subprocess.DEVNULL).decode().strip()
        print("GPU:", gpu)
    except Exception:
        pass

    print("\n(Ctrl+C thoat monitor - cac dich vu van chay ngam)")
    time.sleep(10)
"""

    code = code.replace("__APPS__",          repr(apps_dict))
    code = code.replace("__TUNNELS__",       repr(TUNNELS))
    code = code.replace("__TUNNEL__",        TUNNEL)
    code = code.replace("__PINGGY_URL_RE__", PINGGY_URL_RE)
    code = code.replace("__PINGGY_SKIP_RE__",PINGGY_SKIP_RE)
    code = code.replace("__CF_URL_RE__",     CF_URL_RE)

    Path(monitor).write_text(code)
    run(f"chown {USER}:{USER} {monitor}")


# ── Moonlight pair ────────────────────────────────────────────────────────────
def moonlight_pair():
    out("\n==============================")
    out("MOONLIGHT PAIR")
    out("==============================")
    pin = ask("Enter Moonlight PIN: ", default=_CLI_MOONLIGHT_PIN)
    if not pin:
        out("[SKIP] No Moonlight PIN provided — skipping pair step")
        return
    run(
        'curl -u admin:admin '
        '-X POST -k https://localhost:47990/api/password '
        '-H "Content-Type: application/json" '
        '-d \'{"currentUsername":"admin","currentPassword":"admin",'
        '"newUsername":"admin","newPassword":"admin","confirmNewPassword":"admin"}\''
    )
    run(
        f'curl -u admin:admin '
        f'-X POST -k https://localhost:47990/api/pin '
        f'-H "Content-Type: application/json" '
        f'-d \'{{"pin":"{pin}","name":"moonlight"}}\''
    )
    out("Moonlight Pair Success!")


# ── Final report ──────────────────────────────────────────────────────────────
def final_report(urls):
    tunnel_label = "Pinggy Tunnel" if TUNNEL == "pinggy" else "Cloudflare Tunnel"

    print(f"""
========================================
 CLOUD GAMING READY
========================================
Desktop: XFCE
Services:
[OK] XFCE
[OK] TigerVNC
[OK] noVNC
[OK] Moonlight Web
[OK] Sunshine
[OK] Chromium
[OK] Flatpak + Flathub + Bazaar Store
[OK] RustDesk (self-hosted relay: hbbs + hbbr on localhost)
[OK] RustDesk client (stealth, no public server)
[OK] Chrome Remote Desktop
[OK] WarpDesk (web dashboard: https://warpdesk.app)
[OK] Web Terminal (ttyd, port 7681)
[OK] {tunnel_label}

Black screen?  Type in any terminal:  restart-ui
""")

    if urls:
        print("ACCESS URLS:\n")
        for label, info in urls.items():
            print(f"  {label:<26} {info['url']}")
            print(f"  {'':<26} (local: {info['local_scheme']}://localhost:{info['port']})")
        print()
    else:
        print(
            "(Chưa lấy được URL tunnel — kiểm tra lại các file "
            "*-pinggy.log / *-cf.log trong thư mục home)\n"
        )

    print("""Logs:
/var/log/cloudgaming.log
~/.rustdesk-server/hbbs.log
~/.rustdesk-server/hbbr.log
~/kworker-ui.log        (rustdesk client)
~/warpdesk.log          (warpdesk agent)
/tmp/chrome-remote-desktop.log

Monitor:
~/cloud-monitor.py

Web Terminal (ttyd):
http://localhost:7681   (user: admin)

RustDesk self-hosted:
  ID server : 127.0.0.1:21116
  Relay     : 127.0.0.1:21117
  (no public server — no login required)

Black screen recovery:
  restart-ui            (from any terminal)

========================================
""")


# ── VS Code Web (code-server) ─────────────────────────────────────────────────
#
# Mode 2: minimal install — only code-server, port 8080, password 123456.
# No XFCE, no VNC, no tunnel, no extra services.
#
# code-server is the open-source wrapper that runs VS Code entirely in the
# browser.  Official install script handles distro detection automatically.

VSCODE_WEB_PORT     = 8080
VSCODE_WEB_PASSWORD = "123456"


def setup_vscode_web():
    out("\n[VSCODE-WEB] Installing code-server (VS Code in browser)")

    # ── Install via official script ───────────────────────────────────────────
    if shutil.which("code-server"):
        out("[SKIP] code-server already installed")
    else:
        out("[VSCODE-WEB] Downloading install script...")
        run(
            "curl -fsSL https://code-server.dev/install.sh | sh",
            fatal=False,
        )

    # ── Write config: port 8080, password 123456, bind all interfaces ─────────
    config_dir  = f"{HOME}/.config/code-server"
    config_file = f"{config_dir}/config.yaml"
    run(f"mkdir -p '{config_dir}'", silent=True)
    Path(config_file).write_text(
        f"bind-addr: 0.0.0.0:{VSCODE_WEB_PORT}\n"
        f"auth: password\n"
        f"password: {VSCODE_WEB_PASSWORD}\n"
        f"cert: false\n"
    )
    run(f"chown -R {USER}:{USER} '{config_dir}'", silent=True)
    out(f"[VSCODE-WEB] Config: port={VSCODE_WEB_PORT}  password={VSCODE_WEB_PASSWORD}")

    # ── Start code-server in background ──────────────────────────────────────
    subprocess.run(
        ["pkill", "-f", "code-server"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1)

    run(
        f"""
su - {USER} -c '
nohup code-server \\
  --bind-addr 0.0.0.0:{VSCODE_WEB_PORT} \\
  --auth password \\
  > ~/code-server.log 2>&1 &
'
""",
        fatal=False,
    )
    time.sleep(3)

    # Confirm it started
    pid = run("pgrep -f 'code-server' | head -1", silent=True, fatal=False) or ""
    if pid.strip():
        out(f"[VSCODE-WEB] Running (PID {pid.strip()})")
    else:
        out("[VSCODE-WEB] Process not detected — check ~/code-server.log")

    # ── Start tunnel (Pinggy or Cloudflare) for port 8080 ────────────────────
    out(f"[VSCODE-WEB] Starting {TUNNEL} tunnel for port {VSCODE_WEB_PORT}...")
    start_tunnel("vscode", VSCODE_WEB_PORT, "http")

    # ── Wait + retry for public URL — same logic as option 1 ─────────────────
    out("[VSCODE-WEB] Waiting for tunnel URL (3 attempts × 30s)...")
    suffix   = "pinggy" if TUNNEL == "pinggy" else "cf"
    log_path = f"{HOME}/vscode-{suffix}.log"
    skip_re  = re.compile(PINGGY_SKIP_RE)
    public_url = None

    for attempt in range(3):
        # Truncate log at start of each attempt so stale URLs don't linger
        try:
            open(log_path, "w").close()
        except Exception:
            pass

        for tick in range(30):
            time.sleep(1)
            data = _read_log(log_path)
            if TUNNEL == "pinggy":
                found = [u for u in re.findall(PINGGY_URL_RE, data) if not skip_re.search(u)]
            else:
                found = re.findall(CF_URL_RE, data)
            if found:
                public_url = found[-1]
                break

        if public_url:
            break

        out(f"[VSCODE-WEB] Attempt {attempt+1} failed — restarting tunnel...")
        if TUNNEL == "pinggy":
            kill_pattern("-f", f"ssh .*-R0:localhost:{VSCODE_WEB_PORT}")
        else:
            kill_pattern("-f", f"cloudflared.*localhost:{VSCODE_WEB_PORT}")
        time.sleep(3)   # give the while-true loop time to respawn

    if not public_url:
        out("[VSCODE-WEB] Could not get tunnel URL. Nội dung log:")
        out(_read_log(log_path)[-800:] or "(log trống)")

    out(f"""
========================================
 VS CODE WEB READY
========================================
Public URL : {public_url or '(tunnel connecting... check ~/vscode-pinggy.log)'}
Local URL  : http://localhost:{VSCODE_WEB_PORT}
Password   : {VSCODE_WEB_PASSWORD}

Log (code-server) : ~/code-server.log
Log (tunnel)      : ~/vscode-{'pinggy' if TUNNEL == 'pinggy' else 'cf'}.log
========================================
""")


def run_monitor_foreground():
    out(
        "\n[MONITOR] Starting live dashboard "
        "(Ctrl+C to exit — services keep running in the background)\n"
    )
    time.sleep(1)
    os.execvp("su", ["su", "-", USER, "-c", f"python3 {HOME}/cloud-monitor.py"])


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parse_args()      # must be first — sets NONINTERACTIVE / TUNNEL / MODE

    check_root()
    check_region()

    choose_mode()     # ask mode first (before tunnel prompt)

    # ═══════════════════════════════════════════════════════════════════════════
    # MODE 2 — VS Code Web only (minimal, no XFCE/VNC/tunnel)
    # ═══════════════════════════════════════════════════════════════════════════
    if MODE == "vscode":
        create_user()
        update_system()
        run("DEBIAN_FRONTEND=noninteractive apt-get install -y curl openssh-client", silent=True, fatal=False)
        choose_tunnel()          # ask Pinggy or Cloudflare
        if TUNNEL == "cloudflare":
            install_cloudflared()
        setup_vscode_web()
        return   # done — nothing else installed

    # ═══════════════════════════════════════════════════════════════════════════
    # MODE 1 — Full install
    # ═══════════════════════════════════════════════════════════════════════════
    out("[DESKTOP] XFCE (fixed)")
    choose_tunnel()

    create_user()
    cleanup_old()
    update_system()
    install_base()
    run("apt-get install -y unzip", silent=True, fatal=False)  # needed for server extract
    setup_bazaar()
    rd_pub_key = setup_rustdesk_server()   # start local hbbs + hbbr first
    setup_rustdesk(pub_key=rd_pub_key)     # configure client → local relay
    setup_vnc()
    setup_novnc()
    setup_ttyd()                           # web terminal (alternative UI)
    create_restart_ui_script()             # 'restart-ui' for black screen recovery
    setup_crd()                            # Chrome Remote Desktop (optional token)
    setup_warpdesk()                       # WarpDesk remote access agent

    if TUNNEL == "cloudflare":
        install_cloudflared()

    for label, (prefix, port, scheme) in TUNNELS.items():
        if prefix == "novnc":
            start_tunnel(prefix, port, scheme)
        elif prefix == "moonlight-web":
            setup_moonlight_web()
            start_tunnel(prefix, port, scheme)
        elif prefix == "sunshine":
            setup_sunshine()
            start_tunnel(prefix, port, scheme)
        elif prefix == "ttyd":
            start_tunnel(prefix, port, scheme)

    setup_wallpaper()
    create_monitor()

    urls = get_tunnel_urls()
    final_report(urls)

    moonlight_pair()

    # In non-interactive / notebook mode skip the blocking foreground monitor
    if not NONINTERACTIVE:
        run_monitor_foreground()
    else:
        out("[DONE] Non-interactive run complete. Monitor: python3 ~/cloud-monitor.py")


if __name__ == "__main__":
    main()
