"""Step 48 verification: real runs through the approval queue.

    uv run python scripts/phase7/step48_approval.py pause  <manifest.json> [RUN ...]
    (restart the app here)
    uv run python scripts/phase7/step48_approval.py decide <manifest.json>

pause:  3 real /research runs in parallel; records when each response
        (status paused_for_approval) came back.
decide: after the restart, sends one decision per run at a known delay -
        A approve, B reject WITH a reason, C reject WITHOUT one. A run that
        pauses again is approved after 15s, up to 3 rounds. Then prints the
        approval_requests rows next to the client-side expected waits.
"""

import json
import subprocess
import sys
import threading
import time
import uuid

import httpx

API = "http://localhost:8000"
# A full research request. A one-line question ("In two sentences, what is
# a tokamak?") made 2 of 3 runs answer directly WITHOUT calling
# finalize_report, i.e. without ever pausing (2026-09-23 11:07).
TOPIC = "Research the current status of the ITER fusion project and write a short report."
PLAN = {  # run -> (first decision, reason, seconds after the decide phase starts)
    "A": ("approve", None, 10),
    "B": ("reject", "Too short - add one sentence on ITER, then finalize again.", 40),
    "C": ("reject", None, 70),
}

mode, path = sys.argv[1], sys.argv[2]


def pause(names: list[str]) -> None:
    """Only the named runs (default: all). Runs already in the manifest
    that did pause are kept, so a run that completed without pausing can be
    redone on its own."""
    try:
        runs = {n: r for n, r in json.load(open(path)).items() if r["status"] == "paused_for_approval"}
    except FileNotFoundError:
        runs = {}

    def one(name: str) -> None:
        tid = f"s48-{name}-{uuid.uuid4()}"
        r = httpx.post(f"{API}/research", json={"topic": TOPIC, "thread_id": tid, "user_id": "step48-verify"}, timeout=1800)
        runs[name] = {"thread_id": tid, "http": r.status_code, "status": r.json().get("status"), "paused_seen_at": time.time()}

    threads = [threading.Thread(target=one, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    json.dump(runs, open(path, "w"), indent=1)
    for n, r in sorted(runs.items()):
        print(n, r)


def decide() -> None:
    runs = json.load(open(path))
    start = time.time()
    log = []

    def one(name: str) -> None:
        decision, reason, delay = PLAN[name]
        tid = runs[name]["thread_id"]
        time.sleep(max(0, start + delay - time.time()))
        for round_no in range(1, 4):
            sent = time.time()
            if decision == "approve":
                r = httpx.post(f"{API}/research/{tid}/approve", timeout=1800)
            else:
                r = httpx.post(f"{API}/research/{tid}/reject", json={"reason": reason} if reason else None, timeout=1800)
            status = r.json().get("status") if r.status_code == 200 else r.text[:200]
            log.append({"run": name, "round": round_no, "decision": decision, "reason": reason,
                        "sent_at": sent, "http": r.status_code, "status": status})
            if status != "paused_for_approval":
                return
            runs[name].setdefault("repauses", []).append(time.time())
            time.sleep(15)
            decision, reason = "approve", None

    threads = [threading.Thread(target=one, args=(n,)) for n in PLAN]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print("client log (expected wait = sent_at - when the pause was seen):")
    for e in sorted(log, key=lambda e: e["sent_at"]):
        r = runs[e["run"]]
        seen = r["paused_seen_at"] if e["round"] == 1 else r["repauses"][e["round"] - 2]
        e["expected_wait"] = round(e["sent_at"] - seen, 1)
        print(f"  {e['run']} round {e['round']}: {e['decision']:7} reason={bool(e['reason'])!s:5} "
              f"expected_wait~{e['expected_wait']:7}s -> http {e['http']} {e['status']}")
    json.dump({"runs": runs, "log": log}, open(path, "w"), indent=1)

    ids = ",".join(f"'{r['thread_id']}'" for r in runs.values())
    sql = ("SELECT split_part(thread_id, '-', 2) AS run, id, decision, reason IS NOT NULL AS has_reason, "
           "round(EXTRACT(EPOCH FROM decided_at - paused_at)::numeric, 1) AS wait_s "
           f"FROM approval_requests WHERE thread_id IN ({ids}) ORDER BY id")
    print(subprocess.run(["docker", "exec", "checkpoint-postgres", "psql", "-U", "checkpoints", "-d", "checkpoints", "-c", sql],
                         capture_output=True, text=True).stdout)


pause(sys.argv[3:] or list(PLAN)) if mode == "pause" else decide()
