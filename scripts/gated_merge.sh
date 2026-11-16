#!/usr/bin/env bash
# gated_merge.sh <pr> [repo]: squash-merge a PR ONLY if it has checks and every one passed (fail
# closed; plans 0089 / 0091). The `gh pr checks --watch` exit code and a bucket check decide; the
# gate never pipes a check listing into the merge. Exit 0 merged, 1 not green / merge failed,
# 2 usage or no checks. GATED_MERGE_WAIT (s, default 30) lets a fresh push's checks register.
set -u
[ $# -ge 1 ] || { sed -n '2,5p' "$0"; exit 2; }
PR=$1; R=${2:-camila-blank/workspace-bench}
sleep "${GATED_MERGE_WAIT:-30}"
# the head whose checks we wait on; the merge is refused if the branch moves after this
sha=$(gh pr view "$PR" -R "$R" --json headRefOid -q .headRefOid 2>/dev/null)
if [ -z "$sha" ]; then echo "CANNOT READ the head of #$PR: refusing to merge"; exit 2; fi
n=$(gh pr checks "$PR" -R "$R" --json name --jq 'length' 2>/dev/null)
if [ -z "$n" ] || [ "$n" = 0 ]; then echo "NO CHECKS on #$PR: refusing to merge"; exit 2; fi
if ! gh pr checks "$PR" -R "$R" --watch --fail-fast > /dev/null 2>&1; then
  echo "CHECKS NOT GREEN on #$PR: not merged"; gh pr checks "$PR" -R "$R" 2>&1 | grep -v "pass" | head -5; exit 1
fi
green=$(gh pr checks "$PR" -R "$R" --json bucket --jq 'all(.[]; .bucket == "pass" or .bucket == "skipping")' 2>/dev/null)
if [ "$green" != true ]; then echo "CHECKS NOT GREEN on #$PR (buckets): not merged"; exit 1; fi
if (cd / && gh pr merge "$PR" -R "$R" --squash --match-head-commit "$sha"); then echo "MERGED #$PR"; exit 0; fi
echo "MERGE FAILED on #$PR (conflict or branch protection)"; exit 1
