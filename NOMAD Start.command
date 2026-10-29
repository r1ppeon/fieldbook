#!/bin/bash
# Double-click me in Finder to start NOMAD.
cd "$(dirname "$0")"
./nomad start
echo
echo "You can close this window — NOMAD keeps running."
