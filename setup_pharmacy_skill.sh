#!/bin/bash
# Setup script for Clalit Pharmacy Search skill
# This installs the agent-skill-clalit-pharm-search into the skills directory

set -e

SKILL_DIR="skills/clalit-pharm-search"

if [ -d "$SKILL_DIR" ]; then
    echo "Skill already installed at $SKILL_DIR"
    echo "Updating..."
    cd "$SKILL_DIR"
    git pull origin feat/clalit-pharm-search
    npm install
else
    echo "Cloning agent-skill-clalit-pharm-search..."
    git clone -b feat/clalit-pharm-search https://github.com/tomron/agent-skill-clalit-pharm-search "$SKILL_DIR"
    cd "$SKILL_DIR"
    echo "Installing dependencies..."
    npm install
fi

echo ""
echo "Pharmacy search skill installed successfully!"
echo "Make sure to set GEMINI_API_KEY and OWNER_USER_ID in your .env file."
