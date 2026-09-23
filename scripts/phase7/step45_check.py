"""Step 45 verification, phase 2 (run 5+ min after step45_send.py, within
the hour): count each fake PII value, raw, in what was actually STORED -
Tempo traces, Loki logs, Prometheus label values - and in the collector's
own container log.

    uv run python scripts/phase7/step45_check.py <manifest.json>
"""

import json
import subprocess
import sys
import time

m = json.load(open(sys.argv[1]))
PII = m["pii"]
CONTROL = ["1200 MW", "in 2023", "page 415"]


def lgtm(url: str, *args: str) -> str:
    return subprocess.run(["docker", "exec", "grafana-lgtm", "curl", "-s", "-G", url, *args],
                          capture_output=True, text=True, check=True).stdout


def report(where: str, blob: str) -> None:
    raw = {k: blob.count(v) for k, v in PII.items()}
    control = {c: blob.count(c) for c in CONTROL}
    print(f"  {where}: {len(blob)} bytes | raw PII hits {raw} | '****' x{blob.count('****')} | control {control}")


now = int(time.time())
sessions = [("synthetic", m["synthetic"]["session_id"])]
if "real" in m:
    sessions.append(("real", m["real"]["session_id"]))

for kind, sid in sessions:
    print(f"[{m['label']}] {kind} session {sid}")
    found = json.loads(lgtm("localhost:3200/api/search", "--data-urlencode", 'q={ span.session_id = "%s" }' % sid,
                            "--data-urlencode", f"start={now - 3600}", "--data-urlencode", f"end={now}"))
    ids = [t["traceID"] for t in found.get("traces", [])]
    blob = "".join(lgtm(f"localhost:3200/api/traces/{i}") for i in ids)
    print(f"  tempo traces: {len(ids)}")
    report("tempo", blob)
    if "redaction.masked.keys" in blob:
        keys = set()
        for i in ids:
            for b in json.loads(lgtm(f"localhost:3200/api/traces/{i}"))["batches"]:
                for ss in b["scopeSpans"]:
                    for s in ss["spans"]:
                        for a in s.get("attributes", []):
                            if a["key"] == "redaction.masked.keys":
                                keys.update(a["value"]["stringValue"].split(","))
        print(f"  tempo redaction.masked.keys (union): {sorted(keys)}")
    logs = lgtm("localhost:3100/loki/api/v1/query_range",
                "--data-urlencode", 'query={service_name=~".+"} | session_id="%s"' % sid,
                "--data-urlencode", f"start={now - 3600}000000000", "--data-urlencode", "limit=500")
    n = sum(len(s["values"]) for s in json.loads(logs)["data"]["result"])
    print(f"  loki log lines: {n}")
    report("loki", logs)

prom = lgtm("localhost:9090/api/v1/label/user_id/values")
print("prometheus user_id label values:", json.loads(prom)["data"])
report("prometheus user_id labels", prom)
since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(m["started"] - 5))
col = subprocess.run(["docker", "logs", "--since", since, "otel-collector"], capture_output=True, text=True)
report("collector container log", col.stdout + col.stderr)
