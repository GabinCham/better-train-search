#!/bin/bash
cd "$(dirname "$0")"
echo "Laisse cette fenêtre ouverte tant que tes amis peuvent lancer des recherches."
exec ./venv/bin/python worker.py
