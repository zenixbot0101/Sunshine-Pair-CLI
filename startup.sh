#!/bin/bash

cat > /etc/ssh/sshd_config.d/99-vps-root.conf <<'EOF'
PermitRootLogin yes
PasswordAuthentication yes
KbdInteractiveAuthentication yes
EOF

if sshd -t; then
    systemctl restart ssh
    echo "SSH root/password enabled successfully"
else
    echo "SSH configuration error"
    exit 1
fi
