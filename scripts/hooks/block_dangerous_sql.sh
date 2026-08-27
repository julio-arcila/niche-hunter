#!/usr/bin/env bash
# PreToolUse(Bash) guard: refuse commands that would destroy collected history.
#
# Snapshot tables are the compounding asset — a dropped or truncated
# *_snapshots table is unrecoverable, because the sources do not serve history.
# Reads the hook payload as JSON on stdin and answers with a permission
# decision; see .claude/settings.json.
set -euo pipefail

payload="$(cat)"
command="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty')"
[ -z "$command" ] && exit 0

# Case-insensitive, whitespace-tolerant. Checked against the raw command text.
upper="$(printf '%s' "$command" | tr '[:lower:]' '[:upper:]' | tr -s '[:space:]' ' ')"

deny() {
  jq -n --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

case "$upper" in
  *"DROP TABLE"*|*"DROP DATABASE"*|*"DROP SCHEMA"*)
    deny "Blocked: DROP would destroy snapshot history that cannot be re-collected. Write an Alembic migration with a reversible downgrade instead (.claude/rules/data.md)." ;;
  *"TRUNCATE"*)
    deny "Blocked: TRUNCATE would destroy snapshot history that cannot be re-collected (.claude/rules/data.md)." ;;
esac

# DELETE FROM is allowed only when scoped by a WHERE clause.
case "$upper" in
  *"DELETE FROM"*)
    case "$upper" in
      *"DELETE FROM"*" WHERE "*) : ;;
      *) deny "Blocked: DELETE FROM without a WHERE clause. Scope the delete, or write a migration (.claude/rules/data.md)." ;;
    esac ;;
esac

exit 0
