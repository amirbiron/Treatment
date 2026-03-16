#!/bin/bash
# Setup script for Clalit Pharmacy Search skill
# This installs the agent-skill-clalit-pharm-search into the skills directory

set -e

SKILL_DIR="skills/clalit-pharm-search"

if [ -d "$SKILL_DIR" ]; then
    echo "Skill already installed at $SKILL_DIR"
    echo "Updating..."
    cd "$SKILL_DIR"
    # Revert any local patches before pulling to avoid merge conflicts
    git checkout -- .
    git pull origin feat/clalit-pharm-search
    npm install
else
    echo "Cloning agent-skill-clalit-pharm-search..."
    git clone -b feat/clalit-pharm-search https://github.com/tomron/agent-skill-clalit-pharm-search "$SKILL_DIR"
    cd "$SKILL_DIR"
    echo "Installing dependencies..."
    npm install
fi

cd - > /dev/null

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
