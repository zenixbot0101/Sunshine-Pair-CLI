import marimo

__generated_with = "0.23.9"

app = marimo.App(
    width="medium"
)


@app.cell
def _():

    import os
    import time
    import subprocess
    import getpass
    import traceback


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
            stderr=subprocess.STDOUT
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
            stderr=subprocess.DEVNULL
        ).returncode == 0



    # ==========================
    # 1. USER
    # ==========================

    def create_user():

        print("=== CREATE USER ===")


        result = subprocess.run(
            f"id {USERNAME}",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )


        if result.returncode != 0:

            run(
                f"useradd -m -s /bin/bash {USERNAME}"
            )


        run(
            f"echo '{USERNAME}:{PASSWORD}' | chpasswd"
        )


        run(
            f"usermod -aG sudo {USERNAME}",
            ignore=True
        )



    # ==========================
    # 2. XRDP KDE
    # ==========================

    def install_xrdp():

        print("=== INSTALL XRDP KDE ===")


        run("apt update")


        run("""
DEBIAN_FRONTEND=noninteractive apt install -y \
kde-plasma-desktop \
xrdp \
xorgxrdp \
dbus-x11
""")


        run(
            "echo startplasma-x11 > /etc/xrdp/startwm.sh"
        )


        run(
            "chmod +x /etc/xrdp/startwm.sh"
        )


        run(
            "adduser xrdp ssl-cert",
            ignore=True
        )


        run(
            "service xrdp restart",
            ignore=True
        )



    # ==========================
    # 3. TAILSCALE
    # ==========================

    def install_tailscale():

        print("=== INSTALL TAILSCALE ===")


        if not command_exists("tailscale"):

            run(
                "curl -fsSL https://tailscale.com/install.sh | sh"
            )


    def start_tailscaled():

        print("=== START TAILSCALED ===")


        os.makedirs(
            "/var/run/tailscale",
            exist_ok=True
        )


        os.makedirs(
            "/tmp/tailscale",
            exist_ok=True
        )


        check = subprocess.run(
            "pgrep tailscaled",
            shell=True
        )


        if check.returncode == 0:

            return


        run(f"""
nohup tailscaled \
--tun=userspace-networking \
--state={TAILSCALE_STATE} \
--socket={TAILSCALE_SOCKET} \
>/tmp/tailscale.log 2>&1 &
""")


        for i in range(30):

            if os.path.exists(
                TAILSCALE_SOCKET
            ):

                return

            time.sleep(1)



    def login_tailscale():

        print("=== TAILSCALE LOGIN ===")


        key = getpass.getpass(
            "Auth Key: "
        )


        run(f"""
tailscale \
--socket={TAILSCALE_SOCKET} \
up \
--auth-key={key}
""")


        run(f"""
tailscale \
--socket={TAILSCALE_SOCKET} \
status
""")



    # ==========================
    # 4. CLOUDFLARE
    # ==========================

    def install_cloudflare():

        print("=== INSTALL CLOUDFLARE ===")


        if command_exists("cloudflared"):

            return


        run("""
wget -O cloudflared.deb \
https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
""")


        run(
            "dpkg -i cloudflared.deb || apt --fix-broken install -y"
        )



    # ==========================
    # 5. FIREWALL
    # ==========================

    def firewall():

        print("=== FIREWALL ===")


        run(
            "ufw deny 3389/tcp",
            ignore=True
        )


        run(
            "ufw allow in on tailscale0 to any port 3389 proto tcp",
            ignore=True
        )


        run(
            "ufw reload",
            ignore=True
        )



    # ==========================
    # INFO
    # ==========================

    def info():

        ip = subprocess.getoutput(
            f"""
tailscale \
--socket={TAILSCALE_SOCKET} \
ip -4
"""
        )


        print(f"""

==============================

READY

RDP:
{ip}:3389


USER:
{USERNAME}


PASSWORD:
{PASSWORD}


Cloudflare VSCode:
cloudflared tunnel --url http://localhost:8080


==============================

""")



    # ==========================
    # LOOP
    # ==========================

    def forever_loop():

        print(
            "LOOP START"
        )


        while True:

            try:

                # thêm task tự động ở đây

                time.sleep(60)


            except Exception:

                traceback.print_exc()

                time.sleep(5)



    # ==========================
    # MAIN
    # ==========================

    def main():

        if os.geteuid() != 0:

            print(
                "Run: sudo marimo edit"
            )

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


    return


if __name__ == "__main__":
    app.run()
