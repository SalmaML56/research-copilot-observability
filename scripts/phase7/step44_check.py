"""Step 44 verification, phase 2 (after decision_wait): what reached Tempo."""

import json
import subprocess
import sys
import time


def tempo(path: str) -> dict:
    out = subprocess.run(
        ["docker", "exec", "grafana-lgtm", "curl", "-s", "-G", f"localhost:3200{path[0]}", *path[1:]],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def search(session_id: str, start: int, end: int) -> list:
    q = '{ span.session_id = "%s" }' % session_id
    res = tempo(["/api/search", "--data-urlencode", f"q={q}", "--data-urlencode", f"start={start}",
                 "--data-urlencode", f"end={end}", "--data-urlencode", "limit=20"])
    return res.get("traces", [])


m = json.load(open(sys.argv[1]))
# Last hour up to now. A window tight around the traffic, or one with an end
# in the future, returned no traces from this Tempo even though the traces
# were there (seen 2026-09-23 10:37) - so run this within the hour.
end = int(time.time())
start = end - 3600

kept_ids, mismatches = [], []
for n in m["normal"]:
    found = bool(search(n["session_id"], start, end))
    if found:
        kept_ids.append(n["session_id"])
    if found != n["predicted_kept"]:
        mismatches.append(n)
print(f"(3) normal: {len(kept_ids)}/{len(m['normal'])} in Tempo; predicted {sum(n['predicted_kept'] for n in m['normal'])}; mismatches {len(mismatches)}")
for n in mismatches:
    print("    mismatch:", n)

err = search(m["error"]["session_id"], start, end)
print(f"(1) error session (session policy says drop): {len(err)} trace(s) in Tempo")
for t in err:
    detail = tempo([f"/api/traces/{t['traceID']}"])
    statuses = []
    for b in detail.get("batches", detail.get("resourceSpans", [])):
        for ss in b.get("scopeSpans", b.get("instrumentationLibrarySpans", [])):
            for s in ss["spans"]:
                code = s.get("status", {}).get("code")
                if code:
                    statuses.append((s["name"], code))
    print(f"    trace {t['traceID']} root={t.get('rootTraceName')!r} error spans={statuses}")

for label, f in m["fake"].items():
    hits = search(f["session_id"], start, end)
    print(f"(2) fake {label} cost_usd={f['cost_usd']}: {len(hits)} trace(s) in Tempo {[h['traceID'] for h in hits]}")
