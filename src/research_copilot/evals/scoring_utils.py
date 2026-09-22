"""
Shared scoring helpers for Step 39 (score_runs.py, offline) and Step 40
(score_online.py, online) - both score against the same Groq-hosted judge
and the same 8000 TPM on-demand tier limit, so the rate-limit backoff and
context-capping logic is identical either way.
"""

import re
import time

from groq import APIStatusError, RateLimitError

THRESHOLD = 0.5
ROW_PACING_SECONDS = 20
RATE_LIMIT_RETRY_ATTEMPTS = 3
WAIT_TIME_PATTERN = re.compile(r"try again in ([\d.]+)s")


def cap_context(outputs: list[str], char_budget: int) -> list[str]:
    """Keep outputs in order up to char_budget, truncating the one that overflows."""
    capped: list[str] = []
    remaining = char_budget
    for text in outputs:
        text = str(text)
        if remaining <= 0:
            break
        if len(text) > remaining:
            capped.append(text[:remaining])
            break
        capped.append(text)
        remaining -= len(text)
    return capped or [""]


def measure_with_backoff(metric, test_case) -> None:
    """Groq's 8000 TPM cap is tight enough that one row's calls can trip a
    429 mid-run (seen live: 7946/8000 used, next call requested 4037). Groq
    tells us exactly how long to wait, so honor that instead of guessing.
    Also retries other Groq API errors (seen live: a 400 json_validate_failed
    on a row with an unusually long answer, most likely the judge's verdicts
    array getting truncated at max_tokens=4096) - temperature=0 makes this a
    weak fix, but the API isn't fully deterministic in practice either."""
    for attempt in range(1, RATE_LIMIT_RETRY_ATTEMPTS + 1):
        try:
            metric.measure(test_case)
            return
        except APIStatusError as e:
            if attempt == RATE_LIMIT_RETRY_ATTEMPTS:
                raise
            if isinstance(e, RateLimitError):
                match = WAIT_TIME_PATTERN.search(str(e))
                wait = float(match.group(1)) + 2 if match else 30.0
            else:
                wait = 10.0
            print(f"    {type(e).__name__}, waiting {wait:.0f}s (attempt {attempt}/{RATE_LIMIT_RETRY_ATTEMPTS})")
            time.sleep(wait)
