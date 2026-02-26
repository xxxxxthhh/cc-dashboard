#!/bin/bash
# run_pipeline.sh — 每日全流程：screener → IV采集 → 决策引擎 → dashboard 生成
set -e

WORKSPACE="$HOME/.openclaw/workspace"
LOG_DIR="$WORKSPACE/iv-scanner/logs"
mkdir -p "$LOG_DIR"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Pipeline Start ==="

# 1. Sync portfolio from build.js
echo "→ Step 1: Sync Portfolio..."
cd "$WORKSPACE/cc-dashboard"
python3 sync_portfolio.py 2>&1 | tail -3

# 2. Screener（yfinance 宽筛）
echo "→ Step 2: Screener..."
cd "$WORKSPACE/iv-scanner"
python3 screener.py --update-config 2>&1 | tail -5

# 3. IV Scanner（Futu 精筛，需要 OpenD 在线）
echo "→ Step 3: IV Scanner (Futu)..."
if nc -z 127.0.0.1 11111 2>/dev/null; then
    python3 run_daily.py 2>&1 | tail -5
else
    echo "   ⚠️  Futu OpenD not running, skipping Layer 2"
fi

# 4. Decision Engine
echo "→ Step 4: Decision Engine..."
cd "$WORKSPACE/cc-dashboard"
python3 decision_engine.py 2>&1 | tail -8

# 5. Dashboard Build
echo "→ Step 5: Build Dashboard..."
node build.js

# 6. Git push
echo "→ Step 6: Push to GitHub Pages..."
git add -A
if ! git diff --cached --quiet; then
    git commit -m "daily update: $(date '+%Y-%m-%d')"
    git push
    echo "   ✅ Pushed"
else
    echo "   No changes"
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Pipeline Done ==="
