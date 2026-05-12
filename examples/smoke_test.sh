#!/usr/bin/env bash
# Regression smoke test for scenegraph-review.
# Exercises every endpoint touched by the recent cleanup commit.
# Exits non-zero on any failure. Safe to run against live (uses a known
# image, restores any state it changes within the same test).
set -euo pipefail

BASE="${1:-http://128.237.74.104:5590}"
CODE="${ACCESS_CODE:-sgreview2026}"
JAR=$(mktemp)
trap "rm -f $JAR" EXIT

pass() { printf "  ✓ %s\n" "$1"; }
fail() { printf "  ✗ %s\n" "$1"; exit 1; }

echo "=== scenegraph-review smoke test ==="
echo "  base: $BASE"
echo

echo "--- 1. /api/health (no auth) ---"
H=$(curl -fs $BASE/api/health)
echo "  $H"
[[ "$H" == *'"ok":true'* ]] && pass "health ok" || fail "health"
echo "$H" | grep -q expert_gold_enabled && pass "feature flag exposed on health" || fail "no flag"

echo
echo "--- 2. /api/features (no auth) ---"
F=$(curl -fs $BASE/api/features)
echo "  $F"
[[ "$F" == *expert_gold_enabled* ]] && pass "features ok" || fail "features"

echo
echo "--- 3. /api/auth — bad code rejected ---"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/auth \
    -H "Content-Type: application/json" -d '{"access_code":"wrong"}')
[[ "$HTTP" == "403" ]] && pass "wrong code → 403" || fail "expected 403, got $HTTP"

echo
echo "--- 4. /api/auth — correct code accepted ---"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/auth \
    -H "Content-Type: application/json" -d "{\"access_code\":\"$CODE\"}" \
    -c $JAR)
[[ "$HTTP" == "200" ]] && pass "auth → 200" || fail "expected 200, got $HTTP"

echo
echo "--- 5. /api/list ---"
N_TOTAL=$(curl -fs -b $JAR $BASE/api/list | python3 -c 'import sys,json;d=json.load(sys.stdin);print(len(d))')
N_WITH=$(curl -fs -b $JAR $BASE/api/list | python3 -c 'import sys,json;d=json.load(sys.stdin);print(sum(1 for x in d if x["has_scenegraph"]))')
echo "  $N_TOTAL images, $N_WITH have scenegraphs"
[[ "$N_TOTAL" == "106" ]] && pass "list returns 106 images" || fail "expected 106 images, got $N_TOTAL"
[[ "$N_WITH" == "106" ]] && pass "all 106 have scenegraphs" || fail "scenegraph count drift: $N_WITH"

echo
echo "--- 6. pick a known image (first one) and walk through its endpoints ---"
ID=$(curl -fs -b $JAR $BASE/api/list | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[0]["image_id"])')
echo "  using: $ID"

# /api/sg
SG=$(curl -fs -b $JAR "$BASE/api/sg/$ID")
echo "$SG" | python3 -c 'import sys,json;d=json.load(sys.stdin);assert d["image_id"];assert d["modality"] in ("RGB","IR");assert "primary_subject" in d' \
    && pass "sg fetch + schema-shape" || fail "sg shape"

# /api/gold — this is the rewritten endpoint
GOLD=$(curl -fs -b $JAR "$BASE/api/gold/$ID")
N_KEYS=$(echo "$GOLD" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(len(d))')
SAMPLE=$(echo "$GOLD" | python3 -c 'import sys,json;d=json.load(sys.stdin);print({k:v for k,v in d.items() if v})')
echo "  /api/gold returns $N_KEYS short_keys, non-empty: $SAMPLE"
[[ "$N_KEYS" == "12" ]] && pass "gold returns 12 short_keys (matches schema)" || fail "expected 12, got $N_KEYS"

# /api/image — verify Cache-Control header (new!)
CC=$(curl -fsI -b $JAR "$BASE/api/image/$ID" | grep -i '^cache-control:' | tr -d '\r')
echo "  $CC"
[[ "$CC" == *"max-age"* ]] && pass "image: Cache-Control header set" || fail "no Cache-Control on /api/image"

# /api/thumb — verify Cache-Control header (new!)
CC=$(curl -fsI -b $JAR "$BASE/api/thumb/$ID" | grep -i '^cache-control:' | tr -d '\r')
echo "  $CC"
[[ "$CC" == *"max-age"* ]] && pass "thumb: Cache-Control header set" || fail "no Cache-Control on /api/thumb"

echo
echo "--- 7. /api/sg PUT round-trip (verifies save path) ---"
ORIG=$(curl -fs -b $JAR "$BASE/api/sg/$ID")
# add a marker entity, PUT, GET back, verify, restore
MOD=$(echo "$ORIG" | python3 -c '
import sys, json
d = json.load(sys.stdin)
d["secondary_entities"].append({
    "id": "smoke_test_entity",
    "type": "object", "count": 1,
    "relation": "smoke-test marker (will be removed in ~1s)",
    "attrs": {"smoke_test": True}
})
print(json.dumps(d))
')
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -b $JAR -X PUT "$BASE/api/sg/$ID" \
    -H "Content-Type: application/json" -d "$MOD")
[[ "$HTTP" == "200" ]] && pass "PUT (add) → 200" || fail "expected 200, got $HTTP"

# verify it round-trips
GOT_TAG=$(curl -fs -b $JAR "$BASE/api/sg/$ID" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print(any(e.get("id") == "smoke_test_entity" for e in d["secondary_entities"]))
')
[[ "$GOT_TAG" == "True" ]] && pass "PUT round-trip: marker entity persisted" || fail "marker not in GET"

# restore
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -b $JAR -X PUT "$BASE/api/sg/$ID" \
    -H "Content-Type: application/json" -d "$ORIG")
[[ "$HTTP" == "200" ]] && pass "PUT (restore) → 200" || fail "restore failed"
LEFT=$(curl -fs -b $JAR "$BASE/api/sg/$ID" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print(any(e.get("id") == "smoke_test_entity" for e in d["secondary_entities"]))
')
[[ "$LEFT" == "False" ]] && pass "marker removed on restore" || fail "marker still present"

echo
echo "--- 8. /api/sg/<id>/download (single JSON, attachment) ---"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -b $JAR "$BASE/api/sg/$ID/download")
[[ "$HTTP" == "200" ]] && pass "download single → 200" || fail "download single failed"

echo
echo "--- 9. /api/download_all (NDJSON, full bundle) ---"
TMP=$(mktemp)
curl -fs -b $JAR "$BASE/api/download_all" -o $TMP
LINES=$(wc -l < $TMP | tr -d " ")
echo "  ndjson lines: $LINES"
[[ "$LINES" == "106" ]] && pass "NDJSON bundle has 106 lines" || fail "expected 106, got $LINES"
# verify each line is valid JSON and stripped of _diagnostics
HAS_DIAG=$(python3 -c "
import json
n=0
for line in open('$TMP'):
    d = json.loads(line)
    if '_diagnostics' in d: n += 1
print(n)
")
[[ "$HAS_DIAG" == "0" ]] && pass "_diagnostics stripped from bundle" || fail "_diagnostics still in $HAS_DIAG records"
rm -f $TMP

echo
echo "--- 10. unauthenticated calls are blocked ---"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/list")
[[ "$HTTP" == "401" ]] && pass "no-cookie → 401" || fail "expected 401, got $HTTP"

echo
echo "=== all checks passed ==="
