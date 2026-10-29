#!/bin/bash
# Double-click me in Finder to stop NOMAD.
cd "$(dirname "$0")"
./nomad stop
echo
echo "NOMAD is stopped. You can close this window."
