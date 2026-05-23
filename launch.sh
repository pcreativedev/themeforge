#!/usr/bin/env bash
# Wrapper para lanzar ThemeForge GUI.
cd "$(dirname "$(readlink -f "$0")")"
exec python3 themeforge.py "$@"
