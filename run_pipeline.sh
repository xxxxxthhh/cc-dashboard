#!/bin/bash
# run_pipeline.sh — 每日全流程：OpenD → screener → IV采集 → 决策引擎 → dashboard → iv-tracker
set -e

WORKSPACE="$HOME/.openclaw/workspace"
LOG_DIR="$WORKSPACE/iv-scanner/logs"
mkdir -p "$LOG_DIR"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Pipeline Start ==="

# 0. 确保 OpenD 在线
echo "→ Step 0: Check OpenD..."
if ! nc -z 127.0.0.1 11111 2>/dev/null; then
    echo "   OpenD not running, starting..."
    cd /opt/futu-opend
    nohup ./FutuOpenD > /tmp/opend.log 2>&1 &
    OPEND_PID=$!
    echo "   Waiting for OpenD to start (pid=$OPEND_PID)..."
    for i in $(seq 1 30); do
        if nc -z 127.0.0.1 11111 2>/dev/null; then
            echo "   ✅ OpenD ready (${i}s)"
            break
        fi
        sleep 1
    done
    if ! nc -z 127.0.0.1 11111 2>/dev/null; then
        echo "   ⚠️  OpenD failed to start within 30s (may need verification code)"
    fi
else
    echo "   ✅ OpenD already running"
fi

# 1. Sync portfolio from build.js
echo "→ Step 1: Sync Portfolio..."
cd "$WORKSPACE/cc-dashboard"
python3 sync_portfolio.py 2>&1 | tail -3

# 2. Screener（yfinance 宽筛）
echo "→ Step 2: Screener..."
cd "$WORKSPACE/iv-scanner"
python3 screener.py --update-config 2>&1 | tail -5

# 3. IV Scanner（Futu 精筛）
echo "→ Step 3: IV Scanner (Futu)..."
if nc -z 127.0.0.1 11111 2>/dev/null; then
    python3 run_daily.py 2>&1 | tail -5
else
    echo "   ⚠️  Futu OpenD not available, skipping IV collection"
fi

# 4. Decision Engine
echo "→ Step 4: Decision Engine..."
cd "$WORKSPACE/cc-dashboard"
python3 decision_engine.py 2>&1 | tail -8

# 5. CC Dashboard Build + Push
echo "→ Step 5: Build CC Dashboard..."
node build.js
git add -A
if ! git diff --cached --quiet; then
    git commit -m "daily update: $(date '+%Y-%m-%d')"
    git push
    echo "   ✅ CC Dashboard pushed"
else
    echo "   No changes"
fi

# 6. IV Tracker Build + Push
echo "→ Step 6: Build IV Tracker..."
cd "$WORKSPACE/iv-tracker"
python3 generate.py 2>&1 | tail -3
git add -A
if ! git diff --cached --quiet; then
    git commit -m "data: update $(date '+%Y-%m-%d')"
    git push origin main
    echo "   ✅ IV Tracker pushed"
else
    echo "   No IV Tracker changes"
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Pipeline Done ==="
