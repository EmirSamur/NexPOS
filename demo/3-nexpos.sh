#!/usr/bin/env bash
# NexPOS'u emülatöre bağlı açar (nexpos_demo.db; gerçek kasa verisine dokunmaz).
set -e
cd "$(dirname "$0")/.."
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
NEXPOS_EMULATOR=1 .venv/bin/python main.py
