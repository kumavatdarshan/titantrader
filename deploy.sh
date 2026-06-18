#!/bin/bash
# One-command deploy script for Oracle Cloud (run on the VM)

set -e

echo "🚀 TitanTrader Deployment to Oracle Cloud"
echo "=========================================="

# Step 1: System updates
echo "[1/6] Updating system..."
sudo apt update && sudo apt upgrade -y

# Step 2: Install dependencies
echo "[2/6] Installing Python & dependencies..."
sudo apt install -y python3 python3-pip git ufw

# Step 3: Clone repo
echo "[3/6] Cloning TitanTrader..."
cd /home/ubuntu
rm -rf titantrader 2>/dev/null || true
git clone https://github.com/YOUR_USERNAME/titantrader.git
cd titantrader

# Step 4: Install Python packages
echo "[4/6] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# Step 5: Create systemd service
echo "[5/6] Setting up auto-restart service..."
sudo bash -c 'cat > /etc/systemd/system/titantrader.service << '\''EOF'\''
[Unit]
Description=TitanTrader 24/7 Trading Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/titantrader
ExecStart=/usr/bin/python3 /home/ubuntu/titantrader/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF'

sudo systemctl daemon-reload
sudo systemctl enable titantrader
sudo systemctl start titantrader

# Step 6: Firewall
echo "[6/6] Opening firewall port 8000..."
sudo ufw allow 8000/tcp
sudo ufw --force enable

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Your bot is now running at: http://$(hostname -I | awk '{print $1}'):8000"
echo ""
echo "Check status:"
echo "  sudo systemctl status titantrader"
echo ""
echo "View logs:"
echo "  sudo journalctl -u titantrader -f"
echo ""
echo "Stop bot:"
echo "  sudo systemctl stop titantrader"
echo ""
