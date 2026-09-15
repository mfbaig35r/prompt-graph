#!/usr/bin/env bash
# Rebuild the prompt library in prompt-graph from the diligence-kernel markdown.
#
# The markdown is the source of truth. The database is derived, which is why it is gitignored
# and why this exists: a machine that needs the corpus rebuilds it rather than being handed a
# copy of somebody's .db.
#
#   scripts/rebuild_corpus.sh                      # into $PROMPT_GRAPH_DB or the default
#   scripts/rebuild_corpus.sh --db /tmp/demo.db    # into a throwaway file
#   scripts/rebuild_corpus.sh --dry-run            # parse and report, write nothing
#   scripts/rebuild_corpus.sh --kernel ~/src/dk    # an existing checkout elsewhere
#
# Re-running is safe: table_ingest versions by content, so unchanged prompts are left alone
# and only genuinely changed ones get a new minor version.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MATTER="${PROMPT_GRAPH_MATTER:-Diligence Corpus Library}"
OBJECTIVE="The firm's review-table prompt library, held here for versioning, dependency impact and the evaluation log. Prompts are authored in the diligence-kernel markdown corpus; this holds their history and analysis."
KERNEL_REMOTE="${DILIGENCE_KERNEL_REMOTE:-https://github.com/mfbaig35r/diligence-kernel.git}"
KERNEL="${DILIGENCE_KERNEL:-}"
DB=""
DRY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --db)      DB="$2"; shift 2 ;;
    --kernel)  KERNEL="$2"; shift 2 ;;
    --dry-run) DRY="--dry-run"; shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || { echo "No venv at $REPO/.venv. Run: uv venv .venv && uv pip install --python .venv/bin/python -e '.[ui]'" >&2; exit 1; }
"$PY" -c "import prompt_graph" 2>/dev/null || { echo "prompt_graph is not installed in $REPO/.venv. Run: uv pip install --python .venv/bin/python -e '.[ui]'" >&2; exit 1; }

# Locate the corpus: an explicit path, a sibling checkout, or a cached clone.
if [ -z "$KERNEL" ]; then
  if [ -d "$REPO/../diligence-kernel/review-table-prompts" ]; then
    KERNEL="$(cd "$REPO/../diligence-kernel" && pwd)"
  else
    KERNEL="${XDG_CACHE_HOME:-$HOME/.cache}/prompt-graph/diligence-kernel"
    if [ -d "$KERNEL/.git" ]; then
      echo "updating $KERNEL"
      git -C "$KERNEL" pull --ff-only --quiet
    else
      echo "cloning $KERNEL_REMOTE -> $KERNEL"
      mkdir -p "$(dirname "$KERNEL")"
      git clone --depth 1 --quiet "$KERNEL_REMOTE" "$KERNEL"
    fi
  fi
fi

SYNC="$KERNEL/scripts/sync_prompt_graph.py"
[ -f "$SYNC" ] || { echo "No sync script at $SYNC. Pass --kernel with a diligence-kernel checkout." >&2; exit 1; }
[ -d "$KERNEL/review-table-prompts" ] || { echo "No review-table-prompts/ in $KERNEL." >&2; exit 1; }

[ -n "$DB" ] && export PROMPT_GRAPH_DB="$DB"
echo "corpus : $KERNEL/review-table-prompts"
echo "matter : $MATTER"
echo "target : $("$PY" -c 'from prompt_graph import db; print(db.db_path())')"
echo

# The sync ingests into an existing matter and will not create one, so make it first. Idempotent:
# matter_open returns the existing row untouched when it is already there.
if [ -z "$DRY" ]; then
  "$PY" - "$MATTER" "$OBJECTIVE" <<'PYEOF'
import sys
from prompt_graph import db, service
name, objective = sys.argv[1], sys.argv[2]
conn = db.connect()
conn.execute("BEGIN")
try:
    row, created = service.matter_open(conn, name, create=True, objective=objective,
                                       side="buy", actor="rebuild_corpus.sh")
    conn.execute("COMMIT")
except Exception:
    conn.execute("ROLLBACK")
    raise
print(f"matter {'created' if created else 'already present'}: {row['name']}")
PYEOF
fi

# The sync script parses the markdown and calls prompt_graph.service.table_ingest directly.
# It only needs prompt-graph's own dependencies; the kernel's heavier extras are not imported
# on this path, which is why this runs in prompt-graph's venv rather than a second one.
"$PY" "$SYNC" --matter "$MATTER" --corpus "$KERNEL/review-table-prompts" \
  --actor "rebuild_corpus.sh" --change-note "Rebuilt from the markdown corpus." $DRY
