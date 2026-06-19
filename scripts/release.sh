#!/usr/bin/env bash
# release.sh — AayDocCapio release automation
#
# Normal release:
#   bash scripts/release.sh
#
# Dry run (no commit, no tag, no push — just shows what would happen):
#   bash scripts/release.sh --dry-run
#
# Re-run (tag already exists — re-uploads installers, re-triggers CI,
#         and generates + commits changelog if missing for this version):
#   bash scripts/release.sh --rerun
#
# What it does:
#   1. Reads the new version from version.py
#   2. Checks Windows installers exist in installer_output/ (copies from C: drive if needed)
#   3. Generates a CHANGELOG.md entry via Claude CLI (skipped if CLI unavailable)
#   4. Updates docs/index.html (version strings + release badge date)
#   5. Commits all pending changes (version.py + index.html + CHANGELOG.md + anything else staged)
#   6. Creates and pushes an annotated git tag  →  triggers macOS CI
#   7. Creates a GitHub Release and uploads the Windows installers
#   8. Manually triggers the macOS workflow via gh workflow run (belt-and-suspenders)
#
# Requirements:  git, gh (GitHub CLI, authenticated), python3, sed

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=0
RERUN=0
for arg in "${@:-}"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --rerun)   RERUN=1 ;;
    esac
done

# Wrapper: in dry-run mode, print the command instead of running it
run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "   [dry-run] $*"
    else
        "$@"
    fi
}

# ── 1. Read version ──────────────────────────────────────────────────────────

NEW_VER="$(python3 -c "from version import __version__; print(__version__)")"
TAG="v${NEW_VER}"
TODAY="$(date '+%-d %b %Y')"   # e.g. "14 Jun 2026"  (no leading zero on day)
TODAY_ISO="$(date '+%Y-%m-%d')"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "  AayDocCapio release  ${TAG}  ·  ${TODAY}"
echo "╚══════════════════════════════════════════════════╝"
echo ""

[[ $DRY_RUN -eq 1 ]] && echo "  *** DRY RUN — no commits, tags, or pushes will be made ***" && echo ""
[[ $RERUN -eq 1 ]]   && echo "  *** RERUN — skipping commit/tag/push, re-uploading installers ***" && echo ""

# Guard: don't re-release an already-tagged version (skip in dry-run and rerun)
if [[ $DRY_RUN -eq 0 && $RERUN -eq 0 ]] && git tag | grep -qx "${TAG}"; then
    echo "✗  Tag ${TAG} already exists."
    echo "   Use --rerun to re-upload installers / re-trigger CI without a new tag."
    exit 1
fi

# In rerun mode, tag must already exist
if [[ $RERUN -eq 1 ]] && ! git tag | grep -qx "${TAG}"; then
    echo "✗  Tag ${TAG} does not exist yet — use a normal run (no flags) to create the release."
    exit 1
fi

# ── 2. Check Windows installers are built ────────────────────────────────────

WIN_EXE="installer_output/AayDocCapio_Setup_v${NEW_VER}.exe"
WIN_MSI="installer_output/AayDocCapio_Setup_v${NEW_VER}.msi"

# If not present locally, try to pull from the Windows build folder on C: drive
WIN_BUILD_DIR="/mnt/c/AayDocCapio-build/installer_output"

echo "▶  Checking Windows installers …"
for f in "AayDocCapio_Setup_v${NEW_VER}.exe" "AayDocCapio_Setup_v${NEW_VER}.msi"; do
    LOCAL="installer_output/${f}"
    WIN_SRC="${WIN_BUILD_DIR}/${f}"
    if [[ ! -f "$LOCAL" ]]; then
        if [[ -f "$WIN_SRC" ]]; then
            echo "   ↓  Copying from C: drive: ${f}"
            mkdir -p installer_output
            cp "$WIN_SRC" "$LOCAL"
        fi
    fi
done

MISSING=0
for f in "$WIN_EXE" "$WIN_MSI"; do
    if [[ ! -f "$f" ]]; then
        echo "   ✗  Missing: $f"
        MISSING=1
    else
        SIZE=$(du -sh "$f" | cut -f1)
        echo "   ✓  $f  (${SIZE})"
    fi
done
if [[ $MISSING -eq 1 ]]; then
    echo ""
    echo "   Build the Windows installers first (run build_win.bat on Windows),"
    echo "   then ensure they exist in C:\\AayDocCapio-build\\installer_output\\ and re-run."
    exit 1
fi

# ── 3. Generate changelog entry via Claude CLI ───────────────────────────────

echo ""
echo "▶  Generating changelog entry with Claude …"

# Locate Claude CLI (not always in PATH when run from bash)
CLAUDE_BIN="$(which claude 2>/dev/null || \
    find /home/deepak/.antigravity-ide-server /home/deepak/.antigravity-server \
         /home/deepak/.vscode-server \
         -name "claude" -path "*/native-binary/claude" -type f 2>/dev/null \
         | sort -t- -k2 -V | tail -1 || echo "")"

# Check if this version already has a changelog entry
CHANGELOG_EXISTS=0
if grep -q "^## \[${NEW_VER}\]" CHANGELOG.md 2>/dev/null; then
    CHANGELOG_EXISTS=1
fi

if [[ $CHANGELOG_EXISTS -eq 1 ]]; then
    echo "   Changelog entry for ${NEW_VER} already exists — skipping."
    CHANGELOG_ENTRY=""
elif [[ -z "$CLAUDE_BIN" ]]; then
    echo "   (Claude CLI binary not found — skipping changelog auto-generation)"
    CHANGELOG_ENTRY=""
else
    # Collect commits since previous tag, excluding chore/release commits
    PREV_TAG="$(git describe --tags --abbrev=0 "${TAG}" 2>/dev/null || \
                git describe --tags --abbrev=0 2>/dev/null || echo "")"

    # In rerun mode PREV_TAG will resolve to TAG itself — step back one more
    if [[ "$PREV_TAG" == "$TAG" ]]; then
        PREV_TAG="$(git describe --tags --abbrev=0 "${TAG}^" 2>/dev/null || echo "")"
    fi

    if [[ -n "$PREV_TAG" ]]; then
        GIT_LOG="$(git log "${PREV_TAG}..${TAG}" --oneline --no-merges \
            | grep -v '^[0-9a-f]* chore: release' || true)"
    else
        GIT_LOG="$(git log "${TAG}" --oneline --no-merges -30 \
            | grep -v '^[0-9a-f]* chore: release' || true)"
    fi

    CHANGELOG_ENTRY="$("$CLAUDE_BIN" -p --no-session-persistence \
        "You are writing a changelog for AayDocCapio, a PyQt6 desktop app for downloading Indian tax documents (AIS, TIS, 26AS) from the ITD portal.

Generate a changelog entry for version ${NEW_VER} (released ${TODAY_ISO}) based on these git commits:

${GIT_LOG}

Format it exactly like this example (use the same markdown structure):

## [X.Y.Z] — YYYY-MM-DD

### New Features
- **Feature name** — brief description

### Improvements
- **Improvement name** — brief description

### Bug Fixes
- **Fix name** — brief description

Rules:
- Only include sections that have relevant entries; omit empty sections
- Each bullet: bold the subject, dash, plain-text description
- Keep descriptions concise (one line each)
- Ignore chore/release/docs commits
- Output ONLY the changelog block, no preamble or explanation" || echo "")"

    if [[ -z "$CHANGELOG_ENTRY" ]]; then
        echo "   (Claude returned empty response — skipping changelog auto-generation)"
    fi
fi

if [[ -n "$CHANGELOG_ENTRY" ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "   [dry-run] Would prepend to CHANGELOG.md:"
        echo ""
        echo "${CHANGELOG_ENTRY}" | sed 's/^/      /'
        echo ""
    else
        TMPFILE="$(mktemp)"
        head -5 CHANGELOG.md > "$TMPFILE"
        echo "" >> "$TMPFILE"
        echo "${CHANGELOG_ENTRY}" >> "$TMPFILE"
        echo "" >> "$TMPFILE"
        tail -n +6 CHANGELOG.md >> "$TMPFILE"
        mv "$TMPFILE" CHANGELOG.md
        echo "   CHANGELOG.md updated."

        # In rerun mode commit just the changelog (tag/push already done)
        if [[ $RERUN -eq 1 ]]; then
            git add CHANGELOG.md
            git commit -m "docs: add changelog for ${TAG}

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
            git push origin main
            echo "   Changelog committed and pushed."
        fi
    fi
fi

# ── 4. Update landing page (skipped on rerun — already done) ─────────────────

if [[ $RERUN -eq 0 ]]; then
    echo ""
    echo "▶  Updating docs/index.html …"

    INDEX="docs/index.html"

    PREV_VER="$(grep -oP '(?<=Latest Release · v)[0-9]+\.[0-9]+\.[0-9]+' "$INDEX" | head -1)"

    if [[ -z "$PREV_VER" ]]; then
        echo "✗  Could not detect previous version in $INDEX. Aborting."
        exit 1
    fi

    echo "   ${PREV_VER}  →  ${NEW_VER}"

    run sed -i "s/v${PREV_VER}/v${NEW_VER}/g" "$INDEX"
    run sed -i "s/AayDocCapio_Setup_v${PREV_VER}/AayDocCapio_Setup_v${NEW_VER}/g" "$INDEX"
    run sed -i "s/AayDocCapio-macos-arm64-v${PREV_VER}/AayDocCapio-macos-arm64-v${NEW_VER}/g" "$INDEX"
    run sed -i "s/Latest Release · v${NEW_VER} · [0-9]* [A-Za-z]* [0-9]*/Latest Release · v${NEW_VER} · ${TODAY}/" "$INDEX"

    echo "   docs/index.html updated."

    # ── 5. Commit ─────────────────────────────────────────────────────────────

    echo ""
    echo "▶  Committing …"

    run git add version.py "$INDEX" CHANGELOG.md
    if git diff --cached --quiet; then
        echo "   (nothing new to commit — release files already staged or clean)"
    else
        run git commit -m "chore: release ${TAG}

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        echo "   Committed."
    fi

    # ── 6. Tag & push ─────────────────────────────────────────────────────────

    echo ""
    echo "▶  Tagging ${TAG} and pushing …"

    run git tag -a "${TAG}" -m "Release ${TAG}"
    run git push origin main
    run git push origin "${TAG}"

    echo "   Tag ${TAG} pushed  →  CI workflows triggered."
fi

# ── 7. Create GitHub Release ─────────────────────────────────────────────────

echo ""
echo "▶  Creating / updating GitHub Release …"

NOTES="$(awk "/^## \[${NEW_VER}\]/{found=1; next} found && /^## \[/{exit} found{print}" CHANGELOG.md)"

if [[ -z "$NOTES" ]]; then
    NOTES="See [CHANGELOG.md](https://github.com/dkbholusaria/AayDocCapio/blob/main/CHANGELOG.md) for details."
fi

if [[ $RERUN -eq 1 ]]; then
    # Release already exists — just update notes
    run gh release edit "${TAG}" --notes "${NOTES}" || true
    echo "   GitHub Release notes updated."
else
    run gh release create "${TAG}" \
        --title "AayDocCapio ${TAG}" \
        --notes "${NOTES}" \
        --latest
    echo "   GitHub Release ${TAG} created."
fi

# ── 8. Upload Windows installers ─────────────────────────────────────────────

echo ""
echo "▶  Uploading Windows installers …"

run gh release upload "${TAG}" "$WIN_EXE" "$WIN_MSI" --clobber

echo "   Windows installers uploaded."

# ── 9. Trigger macOS workflow ────────────────────────────────────────────────

echo ""
echo "▶  Dispatching macOS build workflow …"

run gh workflow run build-macos.yml --ref "${TAG}" || {
    echo "   (workflow dispatch skipped — tag-triggered run is already queued)"
}

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "✓  Release ${TAG} complete!"
echo ""
echo "   GitHub Release  →  https://github.com/dkbholusaria/AayDocCapio/releases/tag/${TAG}"
echo "   CI runs         →  https://github.com/dkbholusaria/AayDocCapio/actions"
echo ""
