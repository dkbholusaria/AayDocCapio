#!/usr/bin/env bash
# release.sh — AayDocCapio release automation
#
# Run after bumping version.py:
#   bash scripts/release.sh
#
# What it does:
#   1. Reads the new version from version.py
#   2. Updates docs/index.html (version strings + release badge date)
#   3. Commits all pending changes (version.py + index.html + anything else staged)
#   4. Creates and pushes an annotated git tag  →  triggers macOS & Windows CI
#   5. Creates a GitHub Release (draft=false, latest=true)
#   6. Manually triggers the macOS workflow via gh workflow run (belt-and-suspenders)
#
# Requirements:  git, gh (GitHub CLI, authenticated), python3, sed

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── 1. Read version ──────────────────────────────────────────────────────────

NEW_VER="$(python3 -c "from version import __version__; print(__version__)")"
TAG="v${NEW_VER}"
TODAY="$(date '+%-d %b %Y')"   # e.g. "14 Jun 2026"  (no leading zero on day)

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "  AayDocCapio release  ${TAG}  ·  ${TODAY}"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Guard: don't re-release an already-tagged version
if git tag | grep -qx "${TAG}"; then
    echo "✗  Tag ${TAG} already exists. Bump version.py first, then re-run."
    exit 1
fi

# ── 2. Update landing page ───────────────────────────────────────────────────

echo "▶  Updating docs/index.html …"

INDEX="docs/index.html"

# Detect the previous version by looking for the existing release badge line
PREV_VER="$(grep -oP '(?<=Latest Release · v)[0-9]+\.[0-9]+\.[0-9]+' "$INDEX" | head -1)"

if [[ -z "$PREV_VER" ]]; then
    echo "✗  Could not detect previous version in $INDEX. Aborting."
    exit 1
fi

echo "   ${PREV_VER}  →  ${NEW_VER}"

# Replace every occurrence of the old version string
sed -i "s/v${PREV_VER}/v${NEW_VER}/g" "$INDEX"
sed -i "s/AayDocCapio_Setup_v${PREV_VER}/AayDocCapio_Setup_v${NEW_VER}/g" "$INDEX"
sed -i "s/AayDocCapio-macos-arm64-v${PREV_VER}/AayDocCapio-macos-arm64-v${NEW_VER}/g" "$INDEX"

# Update the release badge date  (format: "Latest Release · vX.Y.Z · D Mon YYYY")
sed -i "s/Latest Release · v${NEW_VER} · [0-9]* [A-Za-z]* [0-9]*/Latest Release · v${NEW_VER} · ${TODAY}/" "$INDEX"

echo "   docs/index.html updated."

# ── 3. Commit ────────────────────────────────────────────────────────────────

echo ""
echo "▶  Committing …"

# Stage everything that's been modified (version.py, index.html, anything else
# the developer already staged before running this script)
git add version.py "$INDEX"

# Absorb any other already-staged files without overriding developer intent
git diff --cached --quiet || true

git commit -m "chore: release ${TAG}

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

echo "   Committed."

# ── 4. Tag & push ────────────────────────────────────────────────────────────

echo ""
echo "▶  Tagging ${TAG} and pushing …"

git tag -a "${TAG}" -m "Release ${TAG}"
git push origin main
git push origin "${TAG}"

echo "   Tag ${TAG} pushed  →  CI workflows triggered."

# ── 5. Create GitHub Release ─────────────────────────────────────────────────

echo ""
echo "▶  Creating GitHub Release …"

# Build release notes from CHANGELOG.md — extract the block for this version
NOTES="$(awk "/^## \[${NEW_VER}\]/{found=1; next} found && /^## \[/{exit} found{print}" CHANGELOG.md)"

if [[ -z "$NOTES" ]]; then
    NOTES="See [CHANGELOG.md](https://github.com/dkbholusaria/AayDocCapio/blob/main/CHANGELOG.md) for details."
fi

gh release create "${TAG}" \
    --title "AayDocCapio ${TAG}" \
    --notes "${NOTES}" \
    --latest

echo "   GitHub Release ${TAG} created."

# ── 6. Trigger macOS workflow explicitly (belt-and-suspenders) ───────────────
# The tag push already triggers both workflows via the push.tags trigger.
# This explicit dispatch is useful if you want to re-run just macOS without
# a new tag (e.g. after a runner flake).  It's a no-op cost when CI is healthy.

echo ""
echo "▶  Dispatching macOS build workflow …"

gh workflow run build-macos.yml --ref "${TAG}" || {
    echo "   (workflow dispatch skipped — tag-triggered run is already queued)"
}

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "✓  Release ${TAG} complete!"
echo ""
echo "   GitHub Release  →  https://github.com/dkbholusaria/AayDocCapio/releases/tag/${TAG}"
echo "   CI runs         →  https://github.com/dkbholusaria/AayDocCapio/actions"
echo ""
echo "   Next step (Windows):"
echo "   Build the installers on Windows, then upload them:"
echo "     powershell -ExecutionPolicy Bypass -File scripts\\upload_windows_installers.ps1"
echo ""
