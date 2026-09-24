# Step 50: prompt versioning (Langfuse prompt management)

Required: version the prompts with Langfuse or Phoenix prompt management and
stamp the version onto every trace.

## What was built

- `src/research_copilot/agents/prompt_registry.py`: maps the three agent
  system prompts (plan Q8: lead, researcher, writer; judge criteria stay in
  git) to Langfuse prompts `research-copilot-lead`, `-researcher`, `-writer`.
  It computes the `prompt_version` stamp, e.g. `lead=1,researcher=1,writer=1`.
- `scripts/phase8/sync_prompts.py`: pushes the code text to Langfuse. It
  creates a new version (labelled `production`) only when the text changed.
  `--check` exits 1 if out of sync and 2 if Langfuse can't be read.
- The stamp replaces the hand-set `PROMPT_VERSION=v1` env var, which is
  removed from `settings.py` and `.env.example`. It now goes on:
  - the FastAPI root span, every child span (via `IdentitySpanProcessor`),
    log records and the spanmetrics `prompt_version` dimension
  - Langfuse eval-capture traces (`capture_runs.py`, `capture_ab_runs.py`):
    as a trace tag `prompt_version:<stamp>`, as metadata, and in the JSONL row
- `IdentitySpanProcessor`'s default for spans outside a request changed from
  `"v1"` (a false claim) to `"unknown"`.

### Design (plan Q6: prompts are edited in code)

The agent always runs the code text. Langfuse is the version registry: the
stamp shows Langfuse's version number only when its `production` text is
identical to the code. Otherwise, or when Langfuse is unreachable or not
configured (CI), each role is stamped `local-<sha256[:8]>` of its code text,
and a mismatch logs a warning that names the sync script. So the stamp never
claims a version that did not run, and a prompt change can't reach
production from the Langfuse UI, bypassing review and the Step 49 gate.

The downside: moving the `production` label in the Langfuse UI does **not**
roll the agent back. A rollback is a git revert followed by a sync.

## Verified before building: events_only doesn't affect prompt management

Tested against the running self-hosted v4 instance:

- Prompt create, new version, get by label, get by version, list, promote
  (`update_prompt`) and delete all work. Prompts live in Postgres, not in the
  ClickHouse trace tables that events_only mode restricts.
- A prompt linked to a generation directly in the SDK
  (`start_as_current_observation(..., prompt=p)`) is stored:
  `events_full.prompt_name/prompt_version/prompt_id` were populated.

## Findings

1. **Per-generation prompt linking mislinks on this agent (why plan Q7
   skipped it).**
   - Passing `metadata={"langfuse_prompt": p}` to a bare model call linked
     nothing: `CallbackHandler._register_langfuse_prompt` only registers on
     a non-root chain.
   - On the real graph (stub model), the same metadata linked **all 8**
     generations (lead, researcher and writer) to the one prompt.
   - The subagents use different prompts, so those links would be wrong.
2. **Constructing the Langfuse SDK client would re-introduce the P5-02
   double export.**
   - `get_client()` adds a `LangfuseSpanProcessor` to the global
     TracerProvider (`langfuse/_client/resource_manager.py`).
   - The client is also a per-public-key singleton, so building one with
     tracing disabled would change it for `api/main.py`'s `create_score`
     calls too.
   - So the runtime lookup is a plain `httpx` GET on
     `/api/public/v2/prompts/{name}`.
   - Verified after the change: after `api.main` is imported and the stamp
     computed, the provider's processors are `['BatchSpanProcessor',
     'IdentitySpanProcessor']`, with no Langfuse processor.
3. **A `/` in a prompt name breaks the REST API, silently.**
   - The first names were `research-copilot/lead` etc. An unencoded `/`
     misses the API route, and Langfuse's Next.js app answers with its HTML
     404 page.
   - The first registry version read every 404 as "prompt missing", so a
     second sync created a duplicate version 2 of every prompt (seen live).
   - The SDK's own `prompts.delete` doesn't encode the name either, and
     failed the same way.
   - Fixed three ways: dash names, `quote(name, safe="")`, and only
     Langfuse's JSON `LangfuseNotFoundError` counts as missing. The duplicate
     prompts were deleted and re-synced, so the history starts at a real
     version 1.
4. **`--check` reported "OUT OF SYNC (production is missing)" when Langfuse
   was unreachable.** This was misleading. Fixed: the sync script now reads
   with `raise_errors=True` and exits 2 with the real error.
5. **Environment: this Codespace (2 cores, 8 GB, no swap) can't run the whole
   stack at once any more.**
   - Memory pressure reached 92% and I/O pressure 99%, with a load average
     of about 40.
   - `langfuse-web` restarted 9 times, and Docker DNS timed out
     (`EAI_AGAIN redis`).
   - Verification ran with services staged: Phoenix stopped, and LGTM +
     collector swapped with `langfuse-worker` as each check needed.
   - No code change. Worth a bigger machine type if all services must run
     together.

## Verification (real output)

- Before any sync: `lead=local-e36efaa4,researcher=local-f3c8d8fe,writer=local-bff935b5`.
- `sync_prompts.py`, run in sequence (`lead` had been created by an earlier
  sync that was cut off by Finding 5):
  - `--check`: exit 1
  - sync: created `researcher`/`writer` version 1
  - sync again: all three "in sync (production = version 1)", no new version
  - `--check`: exit 0
  - stamp: `lead=1,researcher=1,writer=1`
- Edited lead text (in-process): `lead=local-9b145735,researcher=1,writer=1`,
  plus the warning.
- Version bump, on a throwaway `zz-phase8-bump` prompt (deleted after):
  first sync created v1, the same text again changed nothing, an edit
  created v2.
- `LANGFUSE_HOST=http://localhost:3999`: `--check` exit 2 ("Cannot read
  prompts from Langfuse (ConnectError ...)"). The stamp falls back to the
  three local hashes.
- Langfuse eval trace `aace6790dc5e1be50ef8024e9141ebd5` (`capture_runs`, stub
  model): 40/40 observations in `events_full` have tag
  `prompt_version:lead=1,researcher=1,writer=1` and the matching metadata.
- API on the stub model, session `phase8-step50-1790253343`, Tempo trace
  `477656fae7346e23342b722bfcc09b66`:
  - Tempo: root `POST /research` and all 38 spans stamped
    `lead=1,researcher=1,writer=1`
  - Loki: both request log lines carry it
  - Prometheus: 182 spanmetrics series carry it (14 `unknown` series are
    spans outside a request)

## Operating it

After merging a prompt change, run `uv run python scripts/phase8/sync_prompts.py`.
Until then the running agent stamps `local-<hash>` for that role, which is
still exact. `--check` is the quick "is Langfuse in sync with git?" check
used by the runbook.
