#!/usr/bin/env python3
# cloudgaming_installer.py
# KDE + VNC + noVNC + Moonlight Web + Sunshine + Cloudflare + Monitor

import os
import sys
import time
import re
import subprocess
import shutil
import getpass
import platform
import urllib.request
from pathlib import Path
from datetime import datetime


LOG_FILE = "/var/log/cloudgaming.log"


def log(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(
                f"[{datetime.now()}] {msg}\n"
            )
    except:
        pass


def out(msg):
    print(msg)
    log(msg)


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
            text=True
        )

        if result.returncode != 0:
            raise Exception(
                result.stderr.strip()
            )

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


def package_installed(pkg):
    result = subprocess.run(
        f"dpkg -s {pkg}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0


def install_package(pkg):
    if package_installed(pkg):
        out(f"[SKIP] {pkg} already installed")
        return

    out(
        f"[INSTALL] Hãy đợi 5 phút, đang cài {pkg}..."
    )

    run(
        f"DEBIAN_FRONTEND=noninteractive apt install -y {pkg}",
        silent=True
    )


def check_root():
    if os.geteuid() != 0:
        out("ERROR: Run with sudo/root")
        sys.exit(1)


def check_region():

    out("[CHECK] Region")

    try:
        country = run(
            "curl -s https://ipinfo.io/country",
            silent=True
        )

        out(
            f"Detected country: {country}"
        )

    except:
        out(
            "Cannot detect IP region"
        )


def update_system():

    out(
        "[UPDATE] Hãy đợi, đang update system..."
    )

    run(
        "apt update",
        silent=True
    )

    run(
        "apt upgrade -y",
        silent=True
    )


def create_user():

    global USER, HOME

    USER = input(
        "Linux username: "
    )

    HOME = f"/home/{USER}"


    exists = subprocess.run(
        f"id {USER}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


    if exists.returncode != 0:

        out(
            f"Creating user {USER}"
        )

        run(
            f"useradd -m -s /bin/bash {USER}"
        )

        passwd = getpass.getpass(
            "Password: "
        )

        run(
            f"echo '{USER}:{passwd}' | chpasswd"
        )


    run(
        f"usermod -aG sudo {USER}"
    )



def install_base():

    packages = [
        "tigervnc-standalone-server",
        "kde-plasma-desktop",
        "plasma-workspace",
        "dbus-x11",
        "curl",
        "wget",
        "git",
        "chromium",
        "python3-pip",
        "python3-psutil",
        "psmisc"
    ]

    for p in packages:
        install_package(p)



def setup_vnc():

    out(
        "[VNC] Setup KDE VNC"
    )

    # Earlier steps in this script write files into $HOME as root
    # (Path.write_text, urlretrieve, etc). Make sure everything under
    # $HOME is actually owned by the target user before VNC/X tools
    # try to use it — several of the errors seen so far trace back to
    # root-owned files sitting in the user's home directory.
    run(
        f"chown -R {USER}:{USER} {HOME}",
        silent=True
    )

    vnc_dir = f"{HOME}/.config/tigervnc"

    # Newer TigerVNC (>=1.13) stores its config in ~/.config/tigervnc
    # instead of ~/.vnc, and auto-migrates ~/.vnc there the first time
    # vncserver runs. That migration breaks if ~/.config doesn't exist
    # yet (fresh user account) or if ~/.config/tigervnc already exists
    # partially from an earlier failed run of this script. Fix: wipe
    # any leftover state and write straight into the new location, so
    # there's nothing left for vncserver to "migrate".
    run(
        f"rm -rf {HOME}/.vnc {vnc_dir}",
        silent=True
    )

    run(
        f"su - {USER} -c 'mkdir -p {vnc_dir}'"
    )

    # Plain `vncpasswd` needs a real tty (it uses ioctl to disable echo
    # while you type). That fails with "Inappropriate ioctl for device"
    # when this script runs from a notebook/non-interactive shell.
    # Fix: read the password ourselves with getpass (works without a
    # tty) and pipe it into `vncpasswd -f`, which reads plaintext from
    # stdin and writes the obfuscated password file to stdout instead
    # of prompting.
    vnc_password = getpass.getpass(
        "VNC password (min 6 chars): "
    )

    run(
        f"su - {USER} -c 'vncpasswd -f > {vnc_dir}/passwd'",
        input_data=vnc_password + "\n"
    )

    run(
        f"chmod 600 {vnc_dir}/passwd"
    )

    run(
        f"chown {USER}:{USER} {vnc_dir}/passwd"
    )


    # Two fixes here, both needed for KDE Plasma to survive on TigerVNC:
    # 1. `exec` instead of `startplasma-x11 &` — backgrounding makes
    #    the xstartup script itself return immediately, which
    #    vncserver treats as "session exited too early" and kills it.
    #    `exec` replaces the shell process with Plasma so the script
    #    never returns while the session is alive.
    # 2. `dbus-launch --exit-with-session` — Plasma needs a D-Bus
    #    session bus to start; without one it crashes within seconds.
    startup = """#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec dbus-launch --exit-with-session startplasma-x11
"""


    xstartup_path = f"{vnc_dir}/xstartup"

    Path(xstartup_path).write_text(startup)

    run(
        f"chown {USER}:{USER} {xstartup_path}"
    )

    run(
        f"chmod +x {xstartup_path}"
    )

    # TigerVNC's vncserver wrapper calls `xauth` to set up X11 auth
    # before it can start Xvnc. When this runs via `su - USER -c` from
    # a root/notebook process, xauth sometimes can't create
    # ~/.Xauthority itself (often because earlier root-owned writes
    # into $HOME left it in a state xauth doesn't like), which makes
    # the whole session exit within seconds. Pre-creating the file
    # with the right owner sidesteps that entirely.
    run(
        f"su - {USER} -c 'touch ~/.Xauthority'"
    )

    run(
        f"chown {USER}:{USER} {HOME}/.Xauthority"
    )

    run(
        f"chmod 600 {HOME}/.Xauthority"
    )


    # NOTE: do NOT pass "-xstartup startplasma-x11" here.
    # vncserver's -xstartup flag expects a *path to a script*, not a
    # command name. Passing a bare command breaks startup and silently
    # overrides the xstartup file we just wrote above. Leaving -xstartup
    # out lets vncserver fall back to the default xstartup file, which
    # already runs startplasma-x11 correctly.
    run(
        f"""
su - {USER} -c '
vncserver :1 \
-localhost no \
-geometry 1920x1080 \
-depth 24
'
"""
    )



def setup_novnc():

    out(
        "[noVNC] Installing"
    )

    path=f"{HOME}/noVNC"


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
        out(
            "[SKIP] noVNC exists"
        )


    run(
        f"""
su - {USER} -c '
nohup ~/noVNC/utils/novnc_proxy \
--vnc localhost:5901 \
--listen 6001 \
> ~/novnc.log 2>&1 &
'
"""
    )


def install_cloudflared():

    if shutil.which(
        "cloudflared"
    ):
        out(
            "[SKIP] cloudflared exists"
        )
        return


    out(
        "[INSTALL] cloudflared"
    )

    run(
        """
wget -q \
https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
-O /tmp/cloudflared.deb
"""
    )


    run(
        "apt install -y /tmp/cloudflared.deb",
        silent=True
    )
def start_cloudflare(service, port, scheme="http", no_tls_verify=False):

    out(
        f"[CLOUDFLARE] Starting {service}:{port}"
    )

    log_file = f"{HOME}/{service}-cloudflare.log"

    tls_flag = "--no-tls-verify " if no_tls_verify else ""

    run(
        f"""
su - {USER} -c '
nohup cloudflared tunnel {tls_flag}\
--url {scheme}://localhost:{port} \
> {log_file} 2>&1 &
'
"""
    )


def setup_moonlight_web():

    out(
        "[MOONLIGHT WEB] Installing"
    )

    package = f"{HOME}/moonlight-web-x86_64-unknown-linux-gnu.tar.gz"


    if not os.path.exists(package):

        run(
            f"""
su - {USER} -c '
cd ~
wget -q \
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

nohup ./web-server \
--bind-address 127.0.0.1:8081 \
> ~/moonlight-web.log 2>&1 &
'
"""
    )



def setup_sunshine():

    out(
        "[SUNSHINE] Installing"
    )


    deb="/tmp/sunshine.deb"


    if not os.path.exists(deb):

        run(
            """
wget -q \
https://github.com/LizardByte/Sunshine/releases/download/v2026.516.143833/sunshine-debian-trixie-amd64.deb \
-O /tmp/sunshine.deb
"""
        )


    run(
        "apt install -y /tmp/sunshine.deb",
        silent=True
    )


    out(
        "[SUNSHINE] Starting"
    )


    run(
        f"""
su - {USER} -c '
nohup sunshine \
> ~/sunshine.log 2>&1 &
'
"""
    )



def setup_wallpaper():

    out(
        "[WALLPAPER] Download"
    )


    file=f"{HOME}/wallpaper.png"


    if not os.path.exists(file):

        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/zenixbot0101/Sunshine-Pair-CLI/main/wallapper.png",
            file
        )


    run(
        f"""
su - {USER} -c '
mkdir -p ~/.local/share/wallpapers

cp {file} \
~/.local/share/wallpapers/wallpaper.png
'
"""
    )

    # Applying the wallpaper live requires talking to the already
    # running Plasma session over D-Bus/X11. This is a fresh shell
    # (separate from the VNC session's environment), so it doesn't
    # automatically know DISPLAY or the right D-Bus session bus —
    # setting DISPLAY=:1 covers the common case, but this can still
    # fail depending on timing. It's purely cosmetic (the file is
    # already copied in place above and can be set manually from
    # System Settings), so a failure here shouldn't abort the whole
    # install.
    run(
        f"su - {USER} -c 'DISPLAY=:1 plasma-apply-wallpaperimage ~/.local/share/wallpapers/wallpaper.png'",
        fatal=False
    )



def create_monitor(urls):

    out(
        "[MONITOR] Creating app monitor"
    )


    monitor=f"{HOME}/cloud-monitor.py"


    code=r'''
import psutil
import time
import subprocess
import os
from datetime import datetime


apps={
"steam":"Steam",
"chromium":"Chromium",
"sunshine":"Sunshine",
"Xorg":"X11",
"Xtigervnc":"TigerVNC",
"web-server":"Moonlight"
}


URLS_FILE = os.path.expanduser("~/.cloudgaming_urls")


def load_urls():

    entries = []

    if os.path.exists(URLS_FILE):

        with open(URLS_FILE) as f:

            for line in f:

                line = line.strip()

                if not line:
                    continue

                parts = line.split("|")

                if len(parts) == 4:
                    entries.append(parts)

    return entries


while True:

    print("\033c")

    print("==============================")
    print(" CLOUD GAMING MONITOR")
    print("==============================")

    print(
        "TIME:",
        datetime.now()
    )


    uptime=time.time()-psutil.boot_time()

    h=int(uptime//3600)
    m=int((uptime%3600)//60)

    print(
        f"UPTIME: {h}h {m}m"
    )


    print("\nACCESS URLS\n")

    entries = load_urls()

    if entries:

        for label, url, port, local_scheme in entries:

            print(f"{label:<22} {url}")
            print(f"{'':<22} (local: {local_scheme}://localhost:{port})")

    else:

        print("(chua co tunnel nao san sang)")


    print("\nAPPLICATION STATUS\n")


    processes=[
        p.info
        for p in psutil.process_iter(
            ["name"]
        )
    ]


    names=[
        x["name"]
        for x in processes
        if x["name"]
    ]


    for key,name in apps.items():

        status="STOPPED"

        for p in names:

            if key.lower() in p.lower():
                status="RUNNING"


        print(
            f"{name:<15} {status}"
        )


    print("\nSYSTEM")


    print(
        "CPU:",
        psutil.cpu_percent(),
        "%"
    )


    mem=psutil.virtual_memory()

    print(
        "RAM:",
        round(mem.used/1024**3,2),
        "/",
        round(mem.total/1024**3,2),
        "GB"
    )


    try:

        gpu=subprocess.check_output(
            "nvidia-smi --query-gpu=name --format=csv,noheader",
            shell=True
        ).decode().strip()


        print(
            "GPU:",
            gpu
        )

    except:

        pass


    print("\n(Ctrl+C thoat monitor - cac dich vu van chay ngam)")


    time.sleep(10)
'''

    Path(monitor).write_text(code)

    run(
        f"chown {USER}:{USER} {monitor}"
    )

    # URLs are saved separately by get_cloudflare_urls() into
    # ~/.cloudgaming_urls, which the monitor script above reads on
    # every refresh — so it stays correct even though this function
    # doesn't launch the monitor itself (main() does that in the
    # foreground as the final step).



def get_cloudflare_urls():

    out(
        "\n[CLOUDFLARE URL]"
    )

    time.sleep(5)

    # label -> (log file prefix, local port, is displayed as https)
    services = {
        "noVNC (VNC Desktop)": ("novnc", 6001, False),
        "Moonlight Web":       ("moonlight-web", 8081, False),
        "Sunshine":            ("sunshine", 47990, True),
    }

    urls = {}

    for label, (prefix, port, is_https) in services.items():

        path = f"{HOME}/{prefix}-cloudflare.log"

        if not os.path.exists(path):
            continue

        data = open(path).read()

        match = re.search(
            r"https://[-a-zA-Z0-9]+\.trycloudflare\.com",
            data
        )

        if match:
            urls[label] = {
                "url": match.group(),
                "port": port,
                "local_scheme": "https" if is_https else "http"
            }

    # Save for the monitor script to pick up (it runs as a separate
    # process, so it can't just read this dict from memory).
    lines = [
        f"{label}|{info['url']}|{info['port']}|{info['local_scheme']}"
        for label, info in urls.items()
    ]

    urls_file = f"{HOME}/.cloudgaming_urls"

    Path(urls_file).write_text("\n".join(lines))

    run(
        f"chown {USER}:{USER} {urls_file}",
        silent=True
    )

    if not urls:
        out(
            "Chưa lấy được URL Cloudflare nào (tunnel có thể cần thêm vài giây)."
        )

    return urls



def moonlight_pair():

    out(
        "\n=============================="
    )

    out(
        "MOONLIGHT PAIR"
    )

    out(
        "=============================="
    )


    pin=input(
        "Enter Moonlight PIN: "
    )


    run(
        f"""
curl -u admin:admin \
-X POST -k https://localhost:47990/api/password \
-H "Content-Type: application/json" \
-d '{{"currentUsername":"admin","currentPassword":"admin","newUsername":"admin","newPassword":"admin","confirmNewPassword":"admin"}}'
"""
    )


    run(
        f"""
curl -u admin:admin \
-X POST -k https://localhost:47990/api/pin \
-H "Content-Type: application/json" \
-d '{{"pin":"{pin}","name":"moonlight"}}'
"""
    )


    out(
        "Moonlight Pair Success!"
    )



def final_report(urls):

    print("""

========================================

 CLOUD GAMING READY

========================================

Services:

[OK] KDE Plasma
[OK] TigerVNC
[OK] noVNC
[OK] Moonlight Web
[OK] Sunshine
[OK] Chromium
[OK] Cloudflare Tunnel

""")

    if urls:

        print("ACCESS URLS:\n")

        for label, info in urls.items():

            print(
                f"  {label:<22} {info['url']}"
            )
            print(
                f"  {'':<22} (local: {info['local_scheme']}://localhost:{info['port']})"
            )

        print()

    else:

        print(
            "(Chưa lấy được URL Cloudflare — kiểm tra lại các file "
            "*-cloudflare.log trong thư mục home)\n"
        )

    print("""Logs:

/var/log/cloudgaming.log


Monitor:

~/cloud-monitor.py


========================================

""")


def run_monitor_foreground():

    out(
        "\n[MONITOR] Starting live dashboard "
        "(Ctrl+C to exit — services keep running in the background)\n"
    )

    time.sleep(1)

    # Replaces this process with the monitor running as the target
    # user, in the foreground, attached to the current terminal — so
    # it stays open and visible instead of silently dying in a log
    # file like the old nohup version did.
    os.execvp(
        "su",
        ["su", "-", USER, "-c", f"python3 {HOME}/cloud-monitor.py"]
    )


def main():

    check_root()

    check_region()

    create_user()

    update_system()

    install_base()

    setup_vnc()

    setup_novnc()

    install_cloudflared()


    start_cloudflare(
        "novnc",
        6001
    )


    setup_moonlight_web()


    start_cloudflare(
        "moonlight-web",
        8081
    )


    setup_sunshine()


    # Sunshine's web UI is HTTPS-only (self-signed cert), so the
    # tunnel has to point at https:// with TLS verification disabled —
    # pointing cloudflared at http:// here (as before) would just fail
    # to connect.
    start_cloudflare(
        "sunshine",
        47990,
        scheme="https",
        no_tls_verify=True
    )


    setup_wallpaper()

    urls = get_cloudflare_urls()

    create_monitor(urls)


    final_report(urls)


    # MUST run before the monitor takes over the terminal below
    moonlight_pair()

    # Final step: hand the terminal over to the live dashboard. This
    # never returns (Ctrl+C to stop watching) — the actual services
    # (VNC, noVNC, Sunshine, Moonlight Web, cloudflared tunnels) were
    # all started with nohup earlier and keep running independently.
    run_monitor_foreground()



if __name__=="__main__":

    main()
