#!/bin/bash
# Survivor Auction — Launch script
# Double-click to run, or: ./launch.command

cd "$(dirname "$0")"

echo "Starting Survivor Auction..."
echo "Opening http://localhost:5001 in 3 seconds..."
echo ""

# Open browser after a short delay (runs in background)
(sleep 3 && open "http://localhost:5001" 2>/dev/null) &

python3 app.py
