#!/bin/bash
# Tauri 1.x invokes xattr -cr; recent macOS versions removed recursive mode.
if [[ "$1" == "-cr" || "$1" == "-rc" ]]; then
  /usr/bin/find "$2" -exec /usr/bin/xattr -c {} \; 2>/dev/null
  exit 0
fi
exec /usr/bin/xattr "$@"
