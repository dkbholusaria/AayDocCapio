#!/usr/bin/env bash
# bump.sh — bump AayDocCapio version
#
# Usage:
#   bash scripts/bump.sh patch    →  1.4.2  →  1.4.3  (default)
#   bash scripts/bump.sh minor    →  1.4.2  →  1.5.0
#   bash scripts/bump.sh major    →  1.4.2  →  2.0.0
#   bash scripts/bump.sh 1.5.0    →  sets exact version

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PART="${1:-patch}"

CURRENT="$(python3 -c "from version import __version__; print(__version__)")"
IFS='.' read -r MAJ MIN PAT <<< "$CURRENT"

case "$PART" in
    major)  NEW_VER="$((MAJ + 1)).0.0" ;;
    minor)  NEW_VER="${MAJ}.$((MIN + 1)).0" ;;
    patch)  NEW_VER="${MAJ}.${MIN}.$((PAT + 1))" ;;
    [0-9]*) NEW_VER="$PART" ;;
    *)
        echo "Usage: bash scripts/bump.sh [major|minor|patch|X.Y.Z]"
        exit 1
        ;;
esac

sed -i "s/__version__ = \"${CURRENT}\"/__version__ = \"${NEW_VER}\"/" version.py

echo "${CURRENT}  →  ${NEW_VER}"
