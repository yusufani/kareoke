#!/bin/bash
# Encore — Karaoke Studio · macOS / Linux launcher
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

exec .venv/bin/python -m karaoke_app.main "$@"
