#!/usr/bin/env bash
# Smoke test for agent-memory Phase 1. Isolated temp dir, fixture corpus.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILURES=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; FAILURES=$((FAILURES + 1)); }

# Copy the tools into the temp dir so SCRIPT_DIR (and its corpus.txt) is the fixture.
cp "$REPO_DIR/ingest.py" "$REPO_DIR/recall" "$REPO_DIR/remember" "$TMP/"
chmod +x "$TMP/recall" "$TMP/remember"

# Fixture corpus and files.
mkdir -p "$TMP/fixtures" "$TMP/episodes"
cat > "$TMP/fixtures/vite.md" <<'EOF'
# Vite zombie prevention

Use scripts/start-vite.sh, never npx vite directly. Zombie processes
pile up otherwise and choke the box.
EOF

cat > "$TMP/fixtures/secret.md" <<'EOF'
# Fake secret fixture

export DATABASE_API_KEY=abcdef0123456789ZZZZ

This file should be skipped by the content secret scan.
EOF

cat > "$TMP/corpus.txt" <<EOF
# fixture corpus
fixtures|$TMP/fixtures/**/*.md
episodes|$TMP/episodes/**/*.md
EOF

# Env overrides: db and root both live in the temp dir.
export AGENT_MEMORY_DB="$TMP/index.db"
export AGENT_MEMORY_ROOT="$TMP"

cd "$TMP"

# --- a. ingest indexes the vite fixture; summary reports 1+ indexed ---
INGEST_OUT="$(python3 "$TMP/ingest.py")"
echo "$INGEST_OUT"
TOTAL_INDEXED="$(echo "$INGEST_OUT" | sed -n 's/^total indexed: *\([0-9][0-9]*\).*/\1/p')"
if [ "${TOTAL_INDEXED:-0}" -ge 1 ]; then
  pass "a: ingest reports ${TOTAL_INDEXED} indexed (>=1)"
else
  fail "a: ingest reported ${TOTAL_INDEXED:-0} indexed"
fi

# --- b. the secret fixture is skipped (secret-scan count 1, not recallable) ---
SECRET_COUNT="$(echo "$INGEST_OUT" | sed -n 's/^ *secret-scan: *\([0-9][0-9]*\).*/\1/p')"
if [ "${SECRET_COUNT:-0}" -eq 1 ]; then
  pass "b: secret-scan skipped 1 file"
else
  fail "b: secret-scan count was ${SECRET_COUNT:-0}, expected 1"
fi

# --- c. recall "vite zombie" returns the fixture path in the top result ---
RECALL_OUT="$(python3 "$TMP/recall" "vite zombie" -k 3)"
echo "$RECALL_OUT"
TOP_LINE="$(echo "$RECALL_OUT" | grep -m1 '^1\. ')"
if echo "$TOP_LINE" | grep -q "fixtures/vite.md"; then
  pass "c: recall top hit is the vite fixture"
else
  fail "c: recall top hit was: $TOP_LINE"
fi

# also confirm the secret file is NOT recallable
if python3 "$TMP/recall" "DATABASE_API_KEY" -k 3 | grep -q "secret.md"; then
  fail "b2: secret.md was recallable (should be skipped)"
else
  pass "b2: secret.md is not recallable"
fi

# --- d. remember WITHOUT --evidence exits 2 ---
if python3 "$TMP/remember" --source tester "some content without evidence" 2>/dev/null; then
  fail "d: remember without --evidence did NOT fail"
else
  RC=$?
  if [ "$RC" -eq 2 ]; then
    pass "d: remember without --evidence exited 2"
  else
    fail "d: remember without --evidence exited $RC, expected 2"
  fi
fi

# --- e. remember WITH --evidence creates episode with frontmatter; recall finds it ---
EP_PATH="$(python3 "$TMP/remember" --source tester --evidence "commit:abc123" --tags smoke,test \
  "quokka telemetry drift caught during nightly reconcile sweep")"
echo "created: $EP_PATH"
if [ -f "$EP_PATH" ] \
  && grep -q "^source: tester$" "$EP_PATH" \
  && grep -q "^evidence: commit:abc123$" "$EP_PATH" \
  && grep -q "^tags: \[smoke, test\]$" "$EP_PATH" \
  && grep -q "^date: " "$EP_PATH"; then
  pass "e1: episode written with correct frontmatter"
else
  fail "e1: episode frontmatter wrong or file missing ($EP_PATH)"
fi
if python3 "$TMP/recall" "quokka telemetry drift" -k 3 | grep -q "$(basename "$EP_PATH")"; then
  pass "e2: recall finds the new episode"
else
  fail "e2: recall did not find the new episode"
fi

# --- f. recall of a nonexistent term exits 0 and prints no-results ---
if NR_OUT="$(python3 "$TMP/recall" "nonexistent-term-zzz" -k 3)"; then
  if echo "$NR_OUT" | grep -qi "no results"; then
    pass "f: nonexistent term exits 0 with no-results message"
  else
    fail "f: nonexistent term exited 0 but no 'no results' message: $NR_OUT"
  fi
else
  fail "f: recall of nonexistent term exited nonzero"
fi

echo "----------------------------------------"
if [ "$FAILURES" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "$FAILURES TEST(S) FAILED"
  exit 1
fi
