#!/usr/bin/env bash
# Fail on pyflakes "undefined name" findings: they are NameErrors waiting to happen.
# Other pyflakes warnings (unused imports, unused locals) are reported but do not fail.
# The *_overrides.py files are exec'd inside the stock ikabot module's namespace at
# runtime, so their names are defined there and pyflakes cannot see them.
set -uo pipefail

output=$(python -m pyflakes bot ikabot_gui tests 2>&1)
echo "$output"

undefined=$(echo "$output" | grep -E "undefined name" | grep -vE "_overrides\.py:" || true)
if [ -n "$undefined" ]; then
  echo
  echo "::error::pyflakes found undefined names:"
  echo "$undefined"
  exit 1
fi
echo
echo "No undefined names."
