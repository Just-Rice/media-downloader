#!/usr/bin/env bash
# Activates the project's virtual environment and starts the app.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# Make sure Homebrew's ffmpeg is found even when launched from a minimal environment.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ ! -f venv/bin/activate ]; then
    echo "venv not found. Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt" >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Warning: ffmpeg not found. MP3 and merged MP4 downloads will fail. Install with: brew install ffmpeg" >&2
fi

# shellcheck disable=SC1091
source venv/bin/activate
exec python app.py
