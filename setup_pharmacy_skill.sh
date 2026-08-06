#!/bin/bash
# Setup script for Clalit Pharmacy Search skill
# This installs the agent-skill-clalit-pharm-search into the skills directory

# Deliberately not `set -e`. This installs an optional component, and the bot
# runs without it - the agent reports a missing skill rather than crashing. When
# this runs from a hosting Build Command, a non-zero exit fails the whole deploy,
# which is far worse than not having pharmacy search. Failures are reported and
# the script still exits 0; see the summary at the end.

SKILL_DIR="skills/clalit-pharm-search"
REPO="https://github.com/tomron/agent-skill-clalit-pharm-search"
BRANCH="feat/clalit-pharm-search"

warn() { echo "WARNING: $*" >&2; }

# Set PHARMACY_SETUP_STRICT=1 to get a real exit code. Off by default so a
# hosting Build Command cannot be taken down by an optional component; on when
# you run this yourself and want to know whether it worked.
STRICT="${PHARMACY_SETUP_STRICT:-0}"

looks_like_the_clone() {
    # Two questions, because either alone is misleading. Is this the root of its
    # own work tree - `--git-dir` would say yes for any directory inside this
    # repository, by finding Treatment's .git on the way up. And does it hold
    # what a clone holds - a killed clone can leave .git behind with an
    # incomplete checkout, which would otherwise pass as healthy.
    [ -d "$SKILL_DIR" ] && [ -f "$SKILL_DIR/package.json" ] || return 1
    (
        cd "$SKILL_DIR" || exit 1
        [ "$(git rev-parse --show-toplevel 2>/dev/null)" = "$(pwd -P)" ]
    )
}

install_skill() {
    # `[ -d ]` alone was what broke the build: a directory left by an
    # interrupted install has no .git of its own, so `git checkout -- .` inside
    # it resolved against *Treatment's* repository, where nothing under skills/
    # is tracked, and `set -e` turned that into a failed deploy.
    if [ -d "$SKILL_DIR" ] && ! looks_like_the_clone; then
        warn "$SKILL_DIR is not a usable clone; removing it and starting over"
        rm -rf "$SKILL_DIR" || return 1
    fi

    if [ -d "$SKILL_DIR" ]; then
        echo "Skill already installed at $SKILL_DIR"
        echo "Updating..."
        # Revert any local patches before pulling to avoid merge conflicts.
        git -C "$SKILL_DIR" checkout -- . || warn "could not revert local changes"
        git -C "$SKILL_DIR" pull origin "$BRANCH" || {
            warn "could not update the skill; keeping the copy already on disk"
        }
    else
        echo "Cloning agent-skill-clalit-pharm-search..."
        git clone -b "$BRANCH" "$REPO" "$SKILL_DIR" || return 1
    fi

    echo "Installing dependencies..."
    ( cd "$SKILL_DIR" && PUPPETEER_SKIP_DOWNLOAD=true npm install ) || return 1
}

if ! install_skill; then
    warn "pharmacy search skill was not installed. The bot starts without it;"
    warn "the pharmacy agent reports the tool as unavailable rather than failing."
    [ "$STRICT" = "1" ] && exit 1
    exit 0
fi

# Try to download Chrome for Puppeteer (needed for stock checks only).
# Search/cities/pharmacies work without it.
echo "Attempting to download Chrome for stock checks..."
if npx puppeteer browsers install chrome-headless-shell 2>/dev/null; then
    echo "Chrome installed for Puppeteer."
else
    echo "WARNING: Could not download Chrome. Stock checks will not work,"
    echo "but medication search, city lookup, and pharmacy search will still function."
fi

# Patch searchPost to include browser-like headers (fixes 403 from Clalit WAF)
SEARCH_JS="$SKILL_DIR/scripts/pharmacy-search.js"
if grep -q "headers: { 'Content-Type': 'application/json' }," "$SEARCH_JS" 2>/dev/null; then
    echo "Patching pharmacy-search.js with browser headers..."
    # Use a temp file for portability (BSD sed -i requires a backup extension)
    python3 -c "
import pathlib, sys
p = pathlib.Path(sys.argv[1])
old = \"headers: { 'Content-Type': 'application/json' },\"
new = \"headers: { 'Content-Type': 'application/json', 'Origin': 'https://e-services.clalit.co.il', 'Referer': 'https://e-services.clalit.co.il/PharmacyStock/', 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36' },\"
p.write_text(p.read_text().replace(old, new))
" "$SEARCH_JS"
    echo "Patch applied."
fi

echo ""
echo "Pharmacy search skill installed successfully!"
echo "Make sure to set GEMINI_API_KEY and OWNER_USER_ID in your .env file."
