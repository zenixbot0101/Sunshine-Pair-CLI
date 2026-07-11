#!/usr/bin/env python3

import subprocess
import pathlib
import shutil
import time
import re
import os
import sys


# ==========================
# CONFIG
# ==========================

PORT = 8081
PASSWORD = "123456"

CONFIG_DIR = pathlib.Path.home() / ".config" / "code-server"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


# ==========================
# FUNCTIONS
# ==========================

def silent_run(cmd):
    subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def exists(cmd):
    return shutil.which(cmd) is not None


# ==========================
# INSTALL CHECK
# ==========================

print("==============================")
print(" VS CODE WEB + CLOUDFLARE ")
print("==============================")


# code-server

if exists("code-server"):
    print("[✓] code-server installed")
else:
    print("[+] Installing code-server...")
    silent_run(
        "curl -fsSL https://code-server.dev/install.sh | sh"
    )

    if exists("code-server"):
        print("[✓] code-server installed")
    else:
        print("[X] code-server install failed")
        sys.exit(1)



# cloudflared

if exists("cloudflared"):
    print("[✓] cloudflared installed")

else:
    print("[+] Installing cloudflared...")

    silent_run(
        "wget -q -O cloudflared.deb "
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
    )

    silent_run(
        "sudo dpkg -i cloudflared.deb"
    )

    silent_run(
        "sudo apt --fix-broken install -y"
    )


    if exists("cloudflared"):
        print("[✓] cloudflared installed")
    else:
        print("[X] cloudflared install failed")
        sys.exit(1)



# ==========================
# CONFIG CODE SERVER
# ==========================

CONFIG_DIR.mkdir(
    parents=True,
    exist_ok=True
)


CONFIG_FILE.write_text(
f"""bind-addr: 127.0.0.1:{PORT}
auth: password
password: {PASSWORD}
cert: false
"""
)

print("[✓] Config ready")



# ==========================
# START CODE SERVER
# ==========================

print("[+] Starting VS Code Web...")


code = subprocess.Popen(
    [
        "code-server",
        "--config",
        str(CONFIG_FILE)
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True
)


time.sleep(5)


# ==========================
# START CLOUDFLARE
# ==========================

print("[+] Starting Cloudflare Tunnel...")


log_file = open(
    "cloudflared.log",
    "w+"
)


cloud = subprocess.Popen(
    [
        "cloudflared",
        "tunnel",
        "--url",
        f"http://127.0.0.1:{PORT}"
    ],
    stdout=log_file,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    text=True
)


# ==========================
# GET URL
# ==========================

url = None


for i in range(60):

    time.sleep(1)

    log_file.flush()
    log_file.seek(0)

    logs = log_file.read()


    match = re.search(
        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com",
        logs
    )

    if match:
        url = match.group(0)
        break



# ==========================
# OUTPUT
# ==========================

print("\n==============================")
print("        READY")
print("==============================")


if url:

    with open(
        "url.txt",
        "w"
    ) as f:
        f.write(url)


    print(f"URL      : {url}")

else:
    print("URL      : FAILED")


print(f"Password : {PASSWORD}")
print(f"Port     : {PORT}")

print("")
print("code-server PID :", code.pid)
print("cloudflared PID :", cloud.pid)

print("\n✓ Running in background")
