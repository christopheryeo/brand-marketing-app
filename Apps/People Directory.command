#!/bin/bash
# Double-click to open the People Directory with editable "To Enhance" checkboxes.
# Starts the local server (which writes changes back to the vault) and opens it in
# your browser. Close this Terminal window to stop.
cd "$(dirname "$0")/.." || exit 1
echo "Launching People Directory (editable)…"
exec python3 "scripts/people-directory/directory_server.py"
