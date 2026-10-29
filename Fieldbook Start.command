#!/bin/bash
# Double-click me in Finder to start Fieldbook.
cd "$(dirname "$0")"
./fieldbook start
echo
echo "You can close this window — Fieldbook keeps running."
