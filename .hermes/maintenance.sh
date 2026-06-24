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

# --- 1. Sync main branch ---
REMOTE_BRANCH=$(git remote show origin | sed -n '/HEAD branch/s/.*: //p')
log "Default branch: $REMOTE_BRANCH"
log "Fetching origin $REMOTE_BRANCH..."
git fetch origin "$REMOTE_BRANCH" 2>&1 | tee -a "$LOG"
log "Resetting to origin/$REMOTE_BRANCH..."
git reset --hard "origin/$REMOTE_BRANCH" | tee -a "$LOG"

# --- 2. Check Python dependencies ---
log "Checking outdated Python dependencies..."
OUTDATED=$(python3.12 -m pip list --outdated 2>&1 | grep -v 'pip ' | grep -v '^Package' || true)
if [ -n "$OUTDATED" ] && [ "$OUTDATED" != "ALL_UP_TO_DATE" ]; then
    log "Outdated Python packages found:"
    echo "$OUTDATED" | tee -a "$LOG"
else
    log "No outdated Python dependencies."
fi

# --- 3. Open PRs / CI: auto-merge clean dependabot PRs ---
log "Checking open PRs..."
# NOTE: .mergeable is the string "MERGEABLE" (not boolean true)
PR_URLS=$(gh pr list --repo "$GITHUB_REPO" --state open --json url,mergeable,mergeStateStatus,statusCheckRollup \
    --jq '.[] | select(.mergeable == "MERGEABLE" and .mergeStateStatus == "CLEAN") | .url' 2>/dev/null || true)
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

# Sync again after merges (in case of auto-merge on main)
git fetch origin "$REMOTE_BRANCH" 2>&1 | tee -a "$LOG"
git reset --hard "origin/$REMOTE_BRANCH" | tee -a "$LOG"

# --- 4. Label unlabeled issues as needs-triage ---
log "Labeling unlabeled open issues..."
gh issue list --repo "$GITHUB_REPO" --state open --limit 50 --json number,labels,title \
    | jq -c '.[] | select((.labels | length) == 0) | .number' 2>/dev/null \
    | while read -r ISSUE; do
        [ -z "$ISSUE" ] && continue
        log "Labeling issue #$ISSUE as needs-triage"
        gh issue edit "$ISSUE" --repo "$GITHUB_REPO" --add-label needs-triage 2>&1 | tee -a "$LOG" || true
done

# --- 5. FusionAL recall health check ---
log "Checking FusionAL-Recall health..."
if [ -f "$REPO/.env" ]; then
    set -a
    source "$REPO/.env"
    set +a
fi
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8107/mcp 2>&1 || echo "000")
log "FusionAL-Recall port 8107 HTTP status: $HEALTH"
RECENT=$(curl -s -X POST "http://localhost:8107/recall/list_recent" \
    -H "X-API-Key: ${FUSIONAL_API_KEY:-changeme}" \
    -H "Content-Type: application/json" \
    -d '{"n": 5}' 2>&1 || echo '{"items":[], "error": "curl failed"}')
echo "$RECENT" | tee -a "$LOG"

log "Maintenance script completed successfully."