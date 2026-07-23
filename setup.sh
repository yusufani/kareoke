#!/bin/bash
# Encore — Karaoke Studio · macOS / Linux setup (uses uv)
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "WARNING: ffmpeg not found — downloads cannot be decoded without it."
    echo "         macOS: brew install ffmpeg   ·   Debian/Ubuntu: sudo apt install ffmpeg"
fi

echo "Creating virtual environment (Python 3.11)..."
uv python install 3.11
uv venv --python 3.11

echo "Installing dependencies..."
uv pip install -r requirements.txt

echo
echo "Done. Start Encore with: ./run.sh"
