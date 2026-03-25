#!/bin/bash
set -e

echo "=== Facebook Group Scanner Docker ==="
echo "Starting Xvfb..."

# เปิด Xvfb (virtual display)
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!
sleep 2

# ตรวจว่า Xvfb พร้อม
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "[ERROR] Xvfb failed to start"
    exit 1
fi
echo "Xvfb ready (display :99)"

# run scanner
echo "Starting scanner..."
exec python fb_group_scanner.py
