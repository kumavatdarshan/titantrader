#!/bin/bash
# One command to set up everything

set -e

echo "🚀 Setting up Auto-Training (1 month to real money)"
echo "=================================================="
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI not found. Installing..."
    # For Windows with bash
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        echo "Please install GitHub CLI from: https://cli.github.com"
        echo "Then run this script again."
        exit 1
    fi
fi

# Get API keys from user
echo "Enter your NEW Alpaca API key:"
read -r API_KEY
echo ""
echo "Enter your NEW Alpaca Secret key:"
read -r SECRET_KEY
echo ""

# Verify not empty
if [ -z "$API_KEY" ] || [ -z "$SECRET_KEY" ]; then
    echo "❌ Keys cannot be empty!"
    exit 1
fi

echo "✅ Keys received. Setting up..."
echo ""

# Add secrets to GitHub
echo "[1/3] Adding secrets to GitHub..."
gh secret set ALPACA_API_KEY --body "$API_KEY"
gh secret set ALPACA_SECRET_KEY --body "$SECRET_KEY"
echo "✅ Secrets saved (encrypted in GitHub)"
echo ""

# Commit workflow
echo "[2/3] Committing workflow file..."
git add .github/workflows/train-bot.yml FREE_AUTO_TRAINING.md setup-auto-training.sh
git commit -m "feat: add GitHub Actions auto-training (runs every weekday)"
echo "✅ Files committed"
echo ""

# Push to GitHub
echo "[3/3] Pushing to GitHub..."
git push origin main
echo "✅ Pushed to main"
echo ""

echo "=================================================="
echo "🎉 DONE! Your bot is now set up!"
echo "=================================================="
echo ""
echo "What happens next:"
echo "  ✅ Next Monday 9:30 AM EST: Bot runs automatically"
echo "  ✅ Every weekday: 4 hours of trading"
echo "  ✅ Every night: ML model trains"
echo "  ✅ After 30 days: Ready for real money!"
echo ""
echo "Monitor progress:"
echo "  1. Go to: https://github.com/YOUR_USERNAME/titantrader"
echo "  2. Click 'Actions' tab"
echo "  3. Watch 'TitanTrader Training' runs"
echo ""
echo "Download your trading data anytime:"
echo "  1. Actions → TitanTrader Training → Latest run"
echo "  2. Click 'Artifacts' → download titantrader.db"
echo ""
