#!/bin/bash
# Double-click me in Finder to stop Fieldbook.
cd "$(dirname "$0")"
./fieldbook stop
echo
echo "Fieldbook is stopped. You can close this window."
