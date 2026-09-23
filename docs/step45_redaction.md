# Step 45 — Redaction of sensitive content: verification

Plan: `docs/phase7_plan.md` §45, Q7a/Q7b.

## What was built

- A `redaction` processor in `collector/otel-collector-config.yaml`, placed in
  `traces/in` (after `transform/cost`, **before** the `span_metrics` /
  sampling fork), in `logs`, and in `metrics`. It masks with `****`:
  emails, phone numbers (NANP with separators, and international with
  `+cc` and separators), `sk-…` keys (DeepSeek/OpenAI/Langfuse secret),
  `pk-lf-…`, Groq `gsk_…`, AWS `AKIA…`, GitHub `gh?_…` and bearer tokens.
  Any attribute whose **key** looks like a credential
  (`password|secret|api_key|authorization`) has its whole value masked.
  `summary: info` adds `redaction.masked.count` to each touched item.
- Capture mode per environment (Q7a). **Redacted is the default.**
  `docker-compose.yml` always loads a second config file,
  `collector/capture-${COLLECTOR_CAPTURE:-redacted}.yaml`:
  - `capture-redacted.yaml`: `{}`, so the base file as-is.
  - `capture-full.yaml` (the opt-in, `COLLECTOR_CAPTURE=full` in `.env`):
    no redaction, and the `debug` exporter back on traces/logs.
  - Any other value: `unable to read the file …capture-bogus.yaml`, and the
    collector refuses to start. It fails closed and never silently runs unredacted.
- The `debug` exporter (`verbosity: detailed` prints whole prompts and answers)
  is removed from traces/logs in the default mode (Q7b). It stays on metrics
  (P5-12), where the values are already redacted.

`collector validate` passed for `redacted` and `full`, and failed for `bogus`.

## Pre-ship over-match scan (real data, not synthetic)

The candidate regexes were run over real stored data. That was 4 traces
(6,968 string attribute values) and 1,202 log lines from Tempo/Loki, plus
541,807 characters of real run outputs in `data/eval_results/`.

- **F45-1 (real bug caught before shipping):** the first international-phone
  pattern `\+\d{1,3}(?:[\s.-]?\d{2,4}){2,5}` matched `+2023 200`, `+2024 403`
  and others in real httpx log lines: a URL-encoded search query (`…+2023`)
  followed by the HTTP status. Fix: the country code must be followed by a
  separator, so `\+\d{1,3}[\s.-]\d{1,4}(?:[\s.-]\d{2,4}){2,4}\b`. The rescan found
  0 matches for any pattern on all of that data.

## Verification run (2026-09-23)

Scripts: `scripts/phase7/step45_send.py`, `scripts/phase7/step45_check.py`.
Fake PII: `jane.doe.step45@example.com`, `+1 415-555-0133`,
`+44 20 7946 0958`, `sk-step45FAKE…`, `gsk_step45FAKE…`,
`Bearer step45FAKEtoken…`. Control text that must survive: `1200 MW`,
`in 2023`, `page 415`.

Each run sent:
- A synthetic span (attribute + span event + `user_id` + an
  `http.request.header.authorization` attribute) and an OTLP log (body +
  attribute).
- (Redacted run only) a **real** `POST /research` whose topic carries the PII,
  with `user_id = jane.doe.step45@example.com`. That's a full DeepSeek run to the
  approval pause, so the PII also flows through model inputs/outputs,
  tool spans and app logs.

The check counts each raw value in what was actually **stored**, more than 5 min later:

**Default (redacted):**
```
[redacted] synthetic session s45-redacted-synthetic-85fd9f54-…
  tempo: 1538 bytes | raw PII hits {all 0} | '****' x14 | control {'1200 MW': 2, 'in 2023': 2, 'page 415': 2}
  loki:  3534 bytes | raw PII hits {all 0} | '****' x12 | control {… 2, 2, 2}
[redacted] real session s45-redacted-real-37e2310a-…
  tempo traces: 1
  tempo: 1314654 bytes | raw PII hits {all 0} | '****' x682 | control {'1200 MW': 78, 'in 2023': 137, 'page 415': 78}
  loki log lines: 33
  loki: 33069 bytes | raw PII hits {all 0} | '****' x39 | control {… 1, 1, 1}
prometheus user_id label values: ['****', 'step44-verify', 'step46-stream-test', 'step46-test', 'unknown']
  collector container log: 4055364 bytes | raw PII hits {all 0} | '****' x1240
```
Synthetic span as stored in Tempo:
```
user_id = ****
input.value = Contact **** or call **** / ****. Keys: **** ****. Header: **** Control, must survive: the reactor produced 1200 MW in 2023, see page 415.
http.request.header.authorization = ****
redaction.masked.count = 3
event detail = Contact **** or call **** / ****. …
```

**Opt-in (`COLLECTOR_CAPTURE=full`):**
```
[full] synthetic session s45-full-synthetic-7c3a4914-…
  tempo: raw PII hits {'email': 3, 'phone_us': 2, 'phone_intl': 2, 'sk_key': 2, 'groq_key': 2, 'bearer': 3} | '****' x0
  loki:  raw PII hits {'email': 2, 'phone_us': 2, 'phone_intl': 2, 'sk_key': 2, 'groq_key': 2, 'bearer': 2} | '****' x0
prometheus user_id label values: ['****', 'jane.doe.step45@example.com', …]
  collector container log: raw PII hits {'email': 51, …}   (debug exporter)
```
The collector was then put back in the default mode.

## Findings and gaps

- **F45-1:** the phone-regex over-match described above.
- **F45-2 (small over-match, accepted):** `.` is a valid bearer-token
  character, so a sentence-final period right after a token is masked with it
  (`Header: ****` lost its `.`).
- **F45-3:** `blocked_key_patterns` **masks** the whole value. It does not delete the
  attribute, and `summary: info` gives only a count (key names need
  `summary: debug`). The config comments were corrected to match what was observed.
- **F45-4 (real consequence of full mode):** in full mode the raw email
  became a Prometheus `user_id` label value through the `span_metrics`
  dimension. Prometheus keeps it for its retention period, and switching back to
  redacted does not remove it. So full capture must never be turned on
  against a shared/prod metrics store.

**Not covered by collector redaction (Q7b, documented gaps):**
1. **Checkpoint DB.** `checkpoint-postgres` stores the full message history,
   PII included, as written by LangGraph.
2. **Eval files.** `data/eval_results/*` (online samples, captures) store
   raw prompts and answers.
3. **Direct-to-Langfuse mode.** `TRACING_BACKEND=langfuse|both` exports
   straight to Langfuse and never passes through the collector.
4. **The app's own stdout JSON log** (found in this run). `logging_setup.py`
   prints every record to stdout with `user_id`, and it showed
   `jane.doe.step45@example.com` in raw form. Only the OTLP copy goes through the collector.
5. **Span names and span status messages.** The processor reads attributes
   (resource, span, span event, log, datapoint) and log bodies only.
6. **The approval-queue table** (added next, in Step 48) will store the optional reject
   reason as free text.
7. Regexes are shape-based. Names, street addresses and unformatted phone
   numbers (`4155550133`) are not detected.
