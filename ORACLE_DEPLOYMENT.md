# Deploy TitanTrader to Oracle Cloud (Always-Free)

## Step 1: Create Oracle Cloud Account
1. Go to https://www.oracle.com/cloud/free/
2. Click "Start for free"
3. Sign up (no credit card required)
4. Verify email & phone
5. Log into Oracle Cloud Console

## Step 2: Create a Compute VM
1. In Oracle Console, go to **Compute** → **Instances**
2. Click **Create Instance**
3. Configure:
   - **Name**: titantrader
   - **Image**: Ubuntu 22.04 (always-free eligible)
   - **Shape**: Ampere (ARM-based, always-free, 4 vCPUs, 24GB RAM)
   - **Key Pair**: Download and save private key to your local machine
   - Click **Create**

## Step 3: Connect to VM
Once instance is running, copy its public IP and SSH:

```bash
# On your local machine
ssh -i ~/path/to/private_key ubuntu@<PUBLIC_IP>
```

## Step 4: Install Python & Dependencies
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install -y python3 python3-pip git

# Clone your repo
git clone https://github.com/YOUR_USERNAME/titantrader.git
cd titantrader

# Install dependencies
pip install -r requirements.txt
```

## Step 5: Create a Systemd Service (Runs on Startup, Auto-Restart)
```bash
# Create service file
sudo nano /etc/systemd/system/titantrader.service
```

Paste this:
```ini
[Unit]
Description=TitanTrader Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/titantrader
ExecStart=/usr/bin/python3 /home/ubuntu/titantrader/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
# Enable and start
sudo systemctl enable titantrader
sudo systemctl start titantrader

# Check status
sudo systemctl status titantrader

# View logs
sudo journalctl -u titantrader -f
```

## Step 6: Open Firewall for Dashboard
```bash
# In Oracle Console:
# - Go to Compute → Instances → Your Instance
# - Click on your Subnet (under Instance Details)
# - Click Security Lists
# - Add Ingress Rule:
#   - Stateless: unchecked
#   - Source Type: CIDR
#   - Source CIDR: 0.0.0.0/0
#   - IP Protocol: TCP
#   - Destination Port Range: 8000

# OR via SSH (simpler):
sudo ufw allow 8000/tcp
sudo ufw enable
```

## Step 7: Access Dashboard
Go to: `http://<PUBLIC_IP>:8000`

## Step 8: Monitor Remotely
```bash
# SSH in anytime to check logs
ssh -i ~/path/to/private_key ubuntu@<PUBLIC_IP>
sudo journalctl -u titantrader -f
tail -100 logs/titantrader.log
```

---

## Cost: $0 Forever
- Always-Free tier: 4 vCPU, 24GB RAM VM
- No time limit, no upgrade needed
- Runs 24/7 indefinitely

Your bot will trade while you sleep, on a free server, forever.
