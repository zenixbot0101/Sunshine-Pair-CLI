import os
    import time
    import subprocess
    import traceback

    # ==========================
    # CAU HINH - sua o day
    # ==========================
    os.environ["TAILSCALE_AUTH_KEY"] = "tskey-auth-ky9b9XQxbN11CNTRL-ieRyRTYcZhfpMsmmR9jpgf6qjqzDtErj9"

    USERNAME = "dung"
    PASSWORD = "Pzkxvu123@"

    TAILSCALE_SOCKET = "/var/run/tailscale/tailscaled.sock"
    TAILSCALE_STATE = "/tmp/tailscale/state"

    def run(cmd, ignore=False):
        print("\n>>>", cmd)
        result = subprocess.run(
            cmd,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        print(result.stdout)
        if result.returncode != 0 and not ignore:
            raise Exception(result.stdout)
        return result.stdout

    def command_exists(cmd):
        return subprocess.run(
            f"command -v {cmd}",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0

    # ==========================
    # 1. USER
    # ==========================
    def create_user():
        print("=== CREATE USER ===")
        exists = subprocess.run(
            f"id {USERNAME}",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        if not exists:
            run(f"useradd -m -s /bin/bash {USERNAME}")
        run(f"echo '{USERNAME}:{PASSWORD}' | chpasswd")
        run(f"usermod -aG sudo {USERNAME}", ignore=True)

    # ==========================
    # 2. XRDP KDE
    # ==========================
    def install_xrdp():
        print("=== INSTALL XRDP KDE ===")
        run("apt update")
        run(
            "DEBIAN_FRONTEND=noninteractive apt install -y "
            "kde-plasma-desktop xrdp xorgxrdp dbus-x11"
        )
        run("echo startplasma-x11 > /etc/xrdp/startwm.sh")
        run("chmod +x /etc/xrdp/startwm.sh")
        run("adduser xrdp ssl-cert", ignore=True)
        run("service xrdp restart", ignore=True)

    # ==========================
    # 3. TAILSCALE
    # ==========================
    def install_tailscale():
        print("=== INSTALL TAILSCALE ===")
        if not command_exists("tailscale"):
            run("curl -fsSL https://tailscale.com/install.sh | sh")

    def start_tailscaled():
        print("=== START TAILSCALED ===")
        os.makedirs("/var/run/tailscale", exist_ok=True)
        os.makedirs("/tmp/tailscale", exist_ok=True)
        already_running = subprocess.run("pgrep tailscaled", shell=True).returncode == 0
        if already_running:
            return
        run(
            "nohup tailscaled "
            "--tun=userspace-networking "
            f"--state={TAILSCALE_STATE} "
            f"--socket={TAILSCALE_SOCKET} "
            ">/tmp/tailscale.log 2>&1 &"
        )
        for _ in range(30):
            if os.path.exists(TAILSCALE_SOCKET):
                return
            time.sleep(1)

    def login_tailscale():
        print("=== TAILSCALE LOGIN ===")
        key = os.environ.get("TAILSCALE_AUTH_KEY")
        if not key:
            raise RuntimeError(
                "Thieu Tailscale auth key. Dat os.environ['TAILSCALE_AUTH_KEY'] "
                "o dau cell truoc khi chay."
            )
        run(f"tailscale --socket={TAILSCALE_SOCKET} up --auth-key={key}")
        run(f"tailscale --socket={TAILSCALE_SOCKET} status")

    # ==========================
    # 4. CLOUDFLARE
    # ==========================
    def install_cloudflare():
        print("=== INSTALL CLOUDFLARE ===")
        if command_exists("cloudflared"):
            return
        run(
            "wget -O /tmp/cloudflared.deb "
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
        )
        run("dpkg -i /tmp/cloudflared.deb || apt --fix-broken install -y")

    # ==========================
    # 5. FIREWALL
    # ==========================
    def firewall():
        print("=== FIREWALL ===")
        run("ufw deny 3389/tcp", ignore=True)
        run("ufw allow in on tailscale0 to any port 3389 proto tcp", ignore=True)
        run("ufw reload", ignore=True)

    # ==========================
    # INFO
    # ==========================
    def info():
        ip = subprocess.getoutput(f"tailscale --socket={TAILSCALE_SOCKET} ip -4")
        print(
            f"""
==============================
READY

RDP:      {ip}:3389
USER:     {USERNAME}
PASSWORD: {PASSWORD}

Cloudflare tunnel:
  cloudflared tunnel --url http://localhost:8080
==============================
"""
        )

    # ==========================
    # LOOP
    # ==========================
    def forever_loop():
        print("LOOP START")
        while True:
            try:
                time.sleep(60)
            except Exception:
                traceback.print_exc()
                time.sleep(5)

    # ==========================
    # MAIN
    # ==========================
    def main():
        if os.geteuid() != 0:
            print("Can chay bang quyen root: sudo marimo edit notebook.py")
            return

        create_user()
        install_xrdp()
        install_tailscale()
        start_tailscaled()
        login_tailscale()
        install_cloudflare()
        firewall()
        info()
        forever_loop()

    main()
