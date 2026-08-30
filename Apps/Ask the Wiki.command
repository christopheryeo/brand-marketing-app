#!/bin/bash
# Double-click to launch the Influential Brands "Ask the Wiki" AI chat.
# Starts the local server (which reads your OpenAI key from .env.local) and
# opens the wiki in your browser. Close this Terminal window to stop it.
cd "$(dirname "$0")/.." || exit 1
echo "Launching Ask-the-Wiki…"
exec python3 "scripts/wiki-browser/ask_server.py"
