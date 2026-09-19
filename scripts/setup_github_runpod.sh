#!/bin/bash
set -e
# ── transcription: RunPod + GitHub Wiring Script ──
# Run this in a regular terminal (not VS Code integrated terminal)
# after completing `gh auth login` in that same terminal.

echo "============================================================"
echo "  transcription — RunPod + GitHub Setup"
echo "============================================================"

# ── Step 1: Verify gh is authenticated ──
echo ""
echo "Step 1: Checking GitHub CLI authentication..."
if ! gh auth status 2>/dev/null; then
    echo "ERROR: gh is not authenticated. Run 'gh auth login' first."
    exit 1
fi
GH_USER=$(gh api user -q .login)
echo "  Authenticated as: $GH_USER"

# ── Step 2: Create new repo ──
REPO_NAME="transcription-transcription"
echo ""
echo "Step 2: Creating repo $GH_USER/$REPO_NAME..."
if gh repo view "$GH_USER/$REPO_NAME" >/dev/null 2>&1; then
    echo "  Repo already exists — skipping creation."
else
    gh repo create "$REPO_NAME" \
        --private \
        --description "Chilean Spanish transcription + speaker diarization — RunPod Serverless" \
        --disable-wiki \
        --clone=false
    echo "  Created: https://github.com/$GH_USER/$REPO_NAME"
fi

# ── Step 3: Wire git remotes ──
echo ""
echo "Step 3: Configuring git remotes..."
cd "$(dirname "$0")"

CURRENT_ORIGIN=$(git remote get-url origin 2>/dev/null || echo "")
if [ "$CURRENT_ORIGIN" = "https://github.com/$GH_USER/$REPO_NAME.git" ]; then
    echo "  origin already points to $GH_USER/$REPO_NAME"
elif [ -n "$CURRENT_ORIGIN" ]; then
    echo "  Renaming current origin → upstream"
    git remote rename origin upstream 2>/dev/null || true
    git remote add origin "https://github.com/$GH_USER/$REPO_NAME.git"
    echo "  origin → https://github.com/$GH_USER/$REPO_NAME.git"
    echo "  upstream → $CURRENT_ORIGIN"
else
    git remote add origin "https://github.com/$GH_USER/$REPO_NAME.git"
    echo "  origin → https://github.com/$GH_USER/$REPO_NAME.git"
fi

# ── Step 4: Set GitHub Secrets ──
echo ""
echo "Step 4: Setting GitHub Secrets for CI/CD..."

# Load .env (skip comments and blank lines)
if [ -f .env ]; then
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
        # Strip surrounding whitespace
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        export "$key=$value"
    done < .env
fi

# RunPod API Key
if [ -n "$RUNPOD_API_KEY" ]; then
    echo "$RUNPOD_API_KEY" | gh secret set RUNPOD_API_KEY --repo "$GH_USER/$REPO_NAME"
    echo "  ✓ RUNPOD_API_KEY set"
else
    echo "  ✗ RUNPOD_API_KEY missing from .env"
fi

# Docker Hub credentials
read -rp "  Enter Docker Hub username [leandrodisconzi]: " DOCKER_USER
DOCKER_USER=${DOCKER_USER:-leandrodisconzi}
echo "$DOCKER_USER" | gh secret set DOCKER_USERNAME --repo "$GH_USER/$REPO_NAME"
echo "  ✓ DOCKER_USERNAME set"

read -rsp "  Enter Docker Hub password/token: " DOCKER_PASS
echo ""
echo "$DOCKER_PASS" | gh secret set DOCKER_PASSWORD --repo "$GH_USER/$REPO_NAME"
echo "  ✓ DOCKER_PASSWORD set"

# HuggingFace token
if [ -n "$PYANNOTE_AUTH_TOKEN" ] && [ "$PYANNOTE_AUTH_TOKEN" != "<YOUR_NEW_HF_TOKEN>" ]; then
    echo "$PYANNOTE_AUTH_TOKEN" | gh secret set PYANNOTE_AUTH_TOKEN --repo "$GH_USER/$REPO_NAME"
    echo "$PYANNOTE_AUTH_TOKEN" | gh secret set HUGGINGFACE_HUB_TOKEN --repo "$GH_USER/$REPO_NAME"
    echo "  ✓ PYANNOTE_AUTH_TOKEN set"
    echo "  ✓ HUGGINGFACE_HUB_TOKEN set"
else
    echo "  ⚠ HuggingFace token is placeholder — set it later:"
    echo "    gh secret set PYANNOTE_AUTH_TOKEN --repo $GH_USER/$REPO_NAME"
    echo "    gh secret set HUGGINGFACE_HUB_TOKEN --repo $GH_USER/$REPO_NAME"
fi

# ── Step 5: Push to new repo ──
echo ""
echo "Step 5: Pushing code to $GH_USER/$REPO_NAME..."
git push -u origin refactor/clean-architecture-transformation
echo "  ✓ Pushed refactor/clean-architecture-transformation"

# ── Step 6: Copy SSH key for RunPod ──
echo ""
echo "Step 6: SSH key for RunPod"
echo "  Copy the following public key and paste it into"
echo "  https://www.runpod.io/console/user/settings → SSH Public Keys:"
echo ""
echo "────────────────────────────────────────────────"
cat ~/.ssh/runpod_stockawaredev.pub
echo ""
cat ~/.ssh/id_ed25519.pub
echo "────────────────────────────────────────────────"

echo ""
echo "============================================================"
echo "  DONE! Next steps:"
echo "============================================================"
echo ""
echo "  1. Paste the SSH keys above into RunPod console"
echo "  2. Set your HuggingFace token in .env:"
echo "     PYANNOTE_AUTH_TOKEN=hf_xxxx"
echo "     use_auth_token=hf_xxxx"
echo "     HUGGINGFACE_HUB_TOKEN=hf_xxxx"
echo "  3. Push to main to trigger deployment:"
echo "     git checkout main"
echo "     git merge refactor/clean-architecture-transformation"
echo "     git push origin main"
echo "  4. Monitor deployment at:"
echo "     https://github.com/$GH_USER/$REPO_NAME/actions"
echo ""
