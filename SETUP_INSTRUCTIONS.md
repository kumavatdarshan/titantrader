# Quick Start for 24/7 Deployment

## ⚠️ SECURITY FIRST: Rotate Your API Keys

Your Alpaca keys are now exposed in the repository. Do this NOW:

1. Go to https://app.alpaca.markets → Settings → API Keys
2. Delete the old keys
3. Generate new keys
4. Save them somewhere safe (not in git)

## 🚀 Deploy in 5 Minutes

### On Your Local Machine
```bash
# 1. Make sure your repo is on GitHub
git push origin main

# 2. Keep deploy.sh ready (it's in the repo root)
```

### On Oracle Cloud VM (after you create it)
```bash
# Copy-paste this ONE command:
bash <(curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/titantrader/main/deploy.sh)
```

Then set your API keys:
```bash
# SSH into the VM, then:
nano /etc/environment

# Add these lines (use your NEW Alpaca keys):
ALPACA_API_KEY=your_new_key_here
ALPACA_SECRET_KEY=your_new_secret_here

# Save & exit (Ctrl+X, Y, Enter)

# Restart service to pick up new variables:
sudo systemctl restart titantrader

# Check it's running:
sudo systemctl status titantrader
```

## 📊 Monitor Your Bot

### From anywhere, SSH in:
```bash
ssh -i your_private_key ubuntu@<ORACLE_VM_PUBLIC_IP>
sudo journalctl -u titantrader -f
```

### Or open the dashboard:
```
http://<ORACLE_VM_PUBLIC_IP>:8000
```

## 💰 Cost
**$0.00** — Forever. No credit card. No limits.

---

## Troubleshooting

**Bot won't start?**
```bash
sudo systemctl status titantrader
sudo journalctl -u titantrader -n 50
```

**Can't reach dashboard?**
```bash
# Check firewall
sudo ufw status

# Allow port 8000
sudo ufw allow 8000/tcp
```

**Want to update the bot?**
```bash
cd /home/ubuntu/titantrader
git pull origin main
sudo systemctl restart titantrader
```

---

That's it. Your bot trades 24/7 on a free server. No PC required. No cost. Forever.
