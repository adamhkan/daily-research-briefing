#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d "$RUN_LOG_DIR" ]]; then
  echo "No application logs were produced."
  exit 0
fi
git config user.name 'github-actions[bot]'
git config user.email 'github-actions[bot]@users.noreply.github.com'
git add -- "$RUN_LOG_DIR"
if git diff --cached --quiet; then
  echo "No new logs to save."
  exit 0
fi
git commit -m "chore: save workflow logs for run $GITHUB_RUN_ID attempt $GITHUB_RUN_ATTEMPT"
# Another briefing, diagnostic run, or code push may have advanced the branch.
for attempt in 1 2 3; do
  git fetch origin "$GITHUB_REF_NAME"
  git rebase "origin/$GITHUB_REF_NAME"
  if git push origin "HEAD:refs/heads/$GITHUB_REF_NAME"; then
    exit 0
  fi
done
echo 'Could not commit logs to the remote branch; use the uploaded log artifact.' >&2
exit 1
