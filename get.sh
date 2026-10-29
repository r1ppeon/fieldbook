#!/bin/bash
# Fieldbook one-line installer. Paste this into Terminal:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/r1ppeon/fieldbook/main/get.sh)"
# Downloads Fieldbook to ~/fieldbook, sets everything up, and starts it.
# No git, no Homebrew, no admin password needed. Safe to re-run to update.
set -e

DEST="$HOME/fieldbook"
echo "🔥 Fieldbook — installing to $DEST"
mkdir -p "$DEST"
curl -fsSL https://github.com/r1ppeon/fieldbook/archive/refs/heads/main.tar.gz \
  | tar xz -C "$DEST" --strip-components 1

cd "$DEST"
./setup.sh
./fieldbook start

echo
echo "🔥 Fieldbook is running. Your browser just opened the dashboard."
echo "   Click 'Knowledge Packs' there to download your offline library."
echo "   Next time: double-click 'Fieldbook Start.command' in the fieldbook folder."
