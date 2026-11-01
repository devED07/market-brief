#!/bin/bash
# Double-click to start Market Brief on a Mac.
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python isn't installed yet. Get it from https://www.python.org/downloads/ and run this again."
  read -n 1 -s -r -p "Press any key to close"
  exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
  echo "First run: setting things up. This takes a minute or two..."
  python3 -m venv .venv || exit 1
  .venv/bin/python -m pip install --upgrade pip --quiet
  if ! .venv/bin/python -m pip install -r requirements.txt; then
    echo "Setup couldn't download what it needs. Check your internet and run this again."
    rm -rf .venv
    read -n 1 -s -r -p "Press any key to close"
    exit 1
  fi
fi
.venv/bin/python main.py "$@"
