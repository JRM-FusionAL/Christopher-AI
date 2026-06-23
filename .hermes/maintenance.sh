#!/bin/bash
set -euo pipefail

REPO="/home/jrm_fusional/Projects/Christopher-AI"
LOG="$REPO/.hermes/maintenance.log"
GITHUB_REPO="JRM-FusionAL/Christopher-AI"

cd "$REPO"
mkdir -p .hermes

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

# --- 1. Sync ---
BRANCH=$(git remote show origin | sed -n '/HEAD branch/s/.*: //p')
log "Default branch: $BRANCH"
log "Running: git fetch origin $BRANCH"
git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG"

log "Running: git reset --hard origin/$BRANCH"
git reset --hard "origin/$BRANCH" | tee -a "$LOG"

# --- 2. Check dependencies ---
log "Checking for outdated dependencies..."
DEPS_JSON=$(timeout 60 pnpm outdated --json 2>&1 || true)
log "Running: pnpm outdated --json"
echo "$DEPS_JSON" | tee -a "$LOG"

if echo "$DEPS_JSON" | grep -qv '{}'; then
    log "Outdated dependencies found."
    TS=$(date '+%Y%m%d%H%M%S')
    log "Running: git checkout -b maintenance/update-deps-$TS"
    git checkout -b "maintenance/update-deps-$TS" 2>&1 | tee -a "$LOG"

    log "Updating dependencies..."
    log "Running: pnpm update"
    pnpm update 2>&1 | tee -a "$LOG"

    git add -A
    if git diff --cached --quiet; then
        log "No changes to commit after update."
        git checkout "$BRANCH"
    else
        git commit -m "chore: update dependencies ($TS)" | tee -a "$LOG"
        log "Pushing branch maintenance/update-deps-$TS"
        git push -u origin "maintenance/update-deps-$TS" 2>&1 | tee -a "$LOG"

        # Create PR
        log "Creating PR for dependency updates..."
        gh pr create \
            --repo "$GITHUB_REPO" \
            --title "chore: update dependencies ($TS)" \
            --body "Automated dependency update."
        2>&1 | tee -a "$LOG" || log "PR creation failed or PR already exists"
    fi
else
    log "No outdated dependencies."
fi

# Return to default branch
git checkout "$BRANCH" 2>/dev/null || true

# --- 3. Open PRs / CI ---
log "Checking open PRs..."
PR_URLS=$(gh pr list --repo "$GITHUB_REPO" --state open --json url,mergeable,mergeStateStatus,statusCheckRollup --jq '.[] | select(.mergeable == true and .mergeStateStatus == "CLEAN") | .url' 2>/dev/null || true)
if [ -n "$PR_URLS" ]; then
    while read -r PR_URL; do
        [ -z "$PR_URL" ] && continue
        PR_NUM=$(basename "$PR_URL")
        log "Merging PR #$PR_NUM (CI passed): $PR_URL"
        gh pr merge "$PR_NUM" --repo "$GITHUB_REPO" --squash --delete-branch 2>&1 | tee -a "$LOG" || log "Merge failed for PR #$PR_NUM"
    done <<< "$PR_URLS"
else
    log "No mergeable PRs with passing CI."
fi

# --- 4. Label issues ---
log "Labeling open issues..."
gh issue list --repo "$GITHUB_REPO" --state open --limit 50 --json number,labels,title | jq -c '.[] | select((.labels | length) == 0) | .number' 2>/dev/null | while read -r ISSUE; do
    [ -z "$ISSUE" ] && continue
    log "Labeling issue #$ISSUE as needs-triage"
    gh issue edit "$ISSUE" --repo "$GITHUB_REPO" --add-label needs-triage 2>&1 | tee -a "$LOG" || true
done

# --- 5. FUSIONAL recall ---
log "Running FUSIONAL recall checks..."
RECENT=$(curl -s -X POST "http://localhost:8102/recall/list_recent" \
    -H "X-API-Key: changeme" \
    -H "Content-Type: application/json" \
    -d '{"n": 10}' || echo '{"items":[]}')
echo "$RECENT" | tee -a "$LOG"

log "Maintenance script completed successfully."