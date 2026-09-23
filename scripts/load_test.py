"""Phase 7, step 47: 20 concurrent sessions, then an automated check for
cross-session leakage in traces, logs and Postgres checkpoints.

Start the app for it (plan Q8c stub model, Q9a keep every session):

    MODEL_PROFILE=stub TRACE_SESSION_SAMPLE_RATE=1.0 \
        uv run uvicorn research_copilot.api.main:app --port 8000

    uv run python scripts/load_test.py run   <manifest.json> [--sessions 20] [--topic "... {marker} ..."]
    # wait > 5 min (collector tail-sampling decision_wait)
    uv run python scripts/load_test.py check <manifest.json>

Each session i gets a unique thread_id, user_id and a marker LT-<i>-<hex>
in its topic; the stub model echoes the marker into every message and file
it writes. Leakage = a session's traces, logs or checkpoint rows carrying
another session's session_id, user_id or marker.
"""

import argparse
import json
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg

from research_copilot.config.settings import settings

API = "http://localhost:8000"
MARKER = re.compile(rb"LT-[0-9]+-[0-9a-f]{8}")


def sample_collector_memory(stop: threading.Event, samples: list) -> None:
    while not stop.is_set():
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", "otel-collector"],
                             capture_output=True, text=True).stdout.strip()
        samples.append((round(time.time(), 1), out))
        stop.wait(2)


def run(path: str, n: int, topic: str) -> None:
    sessions = []
    for i in range(n):
        tag = uuid.uuid4().hex[:8]
        sessions.append({"i": i, "thread_id": f"lt-{i}-{tag}", "user_id": f"lt-user-{i}", "marker": f"LT-{i}-{tag}"})

    stop, mem = threading.Event(), []
    sampler = threading.Thread(target=sample_collector_memory, args=(stop, mem), daemon=True)
    sampler.start()

    def research(s: dict) -> dict:
        t0 = time.time()
        r = httpx.post(f"{API}/research", timeout=600, json={
            "topic": topic.format(marker=s["marker"]), "thread_id": s["thread_id"], "user_id": s["user_id"]})
        return {"research_http": r.status_code, "research_status": r.json().get("status") if r.status_code == 200 else r.text[:300],
                "research_s": round(time.time() - t0, 1)}

    def approve(s: dict) -> dict:
        t0 = time.time()
        r = httpx.post(f"{API}/research/{s['thread_id']}/approve", timeout=600)
        body = r.json() if r.status_code == 200 else {}
        return {"approve_http": r.status_code, "approve_status": body.get("status", r.text[:300]),
                "answer": body.get("answer"), "approve_s": round(time.time() - t0, 1)}

    started = time.time()
    with ThreadPoolExecutor(max_workers=n) as pool:
        for s, res in zip(sessions, pool.map(research, sessions)):
            s.update(res)
        paused = [s for s in sessions if s["research_status"] == "paused_for_approval"]
        for s, res in zip(paused, pool.map(approve, paused)):
            s.update(res)
    finished = time.time()
    stop.set()
    sampler.join()

    json.dump({"started": started, "finished": finished, "sessions": sessions, "collector_mem": mem}, open(path, "w"), indent=1)
    print(f"{n} sessions, wall time {finished - started:.1f}s")
    print(f"{'i':>2} {'thread_id':18} {'/research':>9} {'status':20} {'s':>5} | {'/approve':>8} {'status':10} {'s':>5} answer-has-own-marker")
    for s in sessions:
        own = s.get("answer") is not None and s["marker"] in s["answer"]
        print(f"{s['i']:>2} {s['thread_id']:18} {s['research_http']:>9} {str(s['research_status'])[:20]:20} {s['research_s']:>5} | "
              f"{s.get('approve_http', '-'):>8} {str(s.get('approve_status', '-'))[:10]:10} {s.get('approve_s', '-'):>5} {own}")
    ok = sum(1 for s in sessions if s.get("approve_status") == "completed" and s["marker"] in (s.get("answer") or ""))
    print(f"completed with own marker in answer: {ok}/{n}")
    peak = max(mem, key=lambda m: _mib(m[1]), default=(0, "-"))
    print(f"collector memory: {len(mem)} samples every ~2s; first {mem[0][1] if mem else '-'}; peak {peak[1]}")


def _mib(usage: str) -> float:
    """'123.4MiB / 512MiB' -> 123.4"""
    value = usage.split("/")[0].strip()
    number = float(re.match(r"[0-9.]+", value).group(0))
    return number * 1024 if value.endswith("GiB") else number / 1024 if value.endswith("KiB") else number


def lgtm(url: str, *args: str) -> dict:
    return json.loads(subprocess.run(["docker", "exec", "grafana-lgtm", "curl", "-s", "-G", url, *args],
                                     capture_output=True, text=True, check=True).stdout)


def check(path: str) -> None:
    m = json.load(open(path))
    sessions = m["sessions"]
    now = int(time.time())
    window = ["--data-urlencode", f"start={now - 3600}", "--data-urlencode", f"end={now}"]
    trace_owner: dict[str, set] = {}
    problems = []
    print(f"{'i':>2} {'traces':>6} {'spans':>6} {'no-sid':>6} {'foreign sid/user/marker':>24} | {'logs':>5} {'foreign':>7} | {'ckpt rows':>9} {'foreign':>7}")

    with psycopg.connect(settings.checkpoint_db_uri) as db:
        for s in sessions:
            sid = s["thread_id"]
            found = lgtm("localhost:3200/api/search", "--data-urlencode", 'q={ span.session_id = "%s" }' % sid,
                         "--data-urlencode", "limit=100", *window)
            ids = [t["traceID"] for t in found.get("traces", [])]
            spans = no_sid = foreign = 0
            for tid in ids:
                trace_owner.setdefault(tid, set()).add(sid)
                for b in lgtm(f"localhost:3200/api/traces/{tid}").get("batches", []):
                    for ss in b["scopeSpans"]:
                        for span in ss["spans"]:
                            spans += 1
                            attrs = {a["key"]: next(iter(a["value"].values())) for a in span.get("attributes", [])}
                            if "session_id" not in attrs:
                                no_sid += 1
                            elif attrs["session_id"] != sid:
                                foreign += 1
                                problems.append(("trace session_id", sid, tid, span["name"], attrs["session_id"]))
                            if "user_id" in attrs and attrs["user_id"] not in (s["user_id"], "unknown"):
                                foreign += 1
                                problems.append(("trace user_id", sid, tid, span["name"], attrs["user_id"]))
                            blob = json.dumps(span).encode()
                            for mk in set(MARKER.findall(blob)) - {s["marker"].encode()}:
                                foreign += 1
                                problems.append(("trace marker", sid, tid, span["name"], mk.decode()))

            logs = lgtm("localhost:3100/loki/api/v1/query_range", "--data-urlencode",
                        'query={service_name="research-copilot-agent"} | session_id="%s"' % sid,
                        "--data-urlencode", f"start={now - 3600}000000000", "--data-urlencode", "limit=1000")
            lines = [v for r in logs["data"]["result"] for v in r["values"]]
            log_foreign = 0
            for line in lines:
                for mk in set(MARKER.findall(json.dumps(line).encode())) - {s["marker"].encode()}:
                    log_foreign += 1
                    problems.append(("log marker", sid, "-", line[1][:80], mk.decode()))

            rows = []
            for table, col in (("checkpoints", "checkpoint::text || metadata::text"), ("checkpoint_blobs", "blob"),
                               ("checkpoint_writes", "blob")):
                for (data,) in db.execute(f"SELECT {col} FROM {table} WHERE thread_id = %s", (sid,)):
                    rows.append(data.encode() if isinstance(data, str) else bytes(data or b""))
            ck_foreign = 0
            for data in rows:
                for mk in set(MARKER.findall(data)) - {s["marker"].encode()}:
                    ck_foreign += 1
                    problems.append(("checkpoint marker", sid, "-", "-", mk.decode()))
            if not any(s["marker"].encode() in d for d in rows):
                problems.append(("checkpoint missing own marker", sid, "-", "-", "-"))
            s["check"] = {"traces": len(ids), "spans": spans}
            print(f"{s['i']:>2} {len(ids):>6} {spans:>6} {no_sid:>6} {foreign:>24} | {len(lines):>5} {log_foreign:>7} | {len(rows):>9} {ck_foreign:>7}")

        approvals = db.execute(
            "SELECT count(*), count(*) FILTER (WHERE decision = 'approve'), count(DISTINCT thread_id) "
            "FROM approval_requests WHERE thread_id = ANY(%s)", ([s["thread_id"] for s in sessions],)).fetchone()

    shared = {t: o for t, o in trace_owner.items() if len(o) > 1}
    print(f"traces found in more than one session's search: {len(shared)}")
    print(f"approval_requests rows: {approvals[0]} ({approvals[1]} approve) over {approvals[2]} threads")
    print(f"sessions with 0 traces in Tempo: {sum(1 for s in sessions if s['check']['traces'] == 0)}")
    print(f"LEAKAGE PROBLEMS: {len(problems)}")
    for p in problems[:30]:
        print("  ", p)


parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["run", "check"])
parser.add_argument("manifest")
parser.add_argument("--sessions", type=int, default=20)
# The real-model runs (plan Q8c) need a research-style request: on a bare
# one-liner the model may answer without pausing (docs/step48, F48-1).
parser.add_argument("--topic", default="Load test topic {marker}")
args = parser.parse_args()
run(args.manifest, args.sessions, args.topic) if args.mode == "run" else check(args.manifest)
