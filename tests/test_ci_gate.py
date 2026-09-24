"""Step 49: the eval gate's verdict logic (no API calls)."""

from research_copilot.evals.ci_gate import GATE_IDS, decide, no_notes_reason, row_problem

SEARCH_FAIL = "Search failed after retries for query 'x': blocked. This is often a temporary block"


def scored(pid, score):
    return {"id": pid, "status": "ok", "correctness_score": score}


def with_problem(row):
    row["problem"] = row_problem(row)
    return row


def test_pass_at_or_above_threshold():
    result = decide([scored("rc-001", 1.0), scored("rc-002", 0.0), scored("rc-003", 0.5)], threshold=0.5)
    assert result["verdict"] == "pass"
    assert result["mean"] == 0.5
    assert result["scored"] == 3


def test_fail_below_threshold():
    result = decide([scored("rc-001", 0.3), scored("rc-002", 0.0), scored("rc-003", 0.3)], threshold=0.5)
    assert result["verdict"] == "fail"


def test_all_searches_blocked_is_inconclusive_not_fail():
    row = with_problem({"id": "rc-002", "status": "ok", "answer": "could not complete",
                        "retrieval_context": [SEARCH_FAIL, SEARCH_FAIL]})
    # mean is 0.33 or 0.67 depending on the blocked row: can't decide
    result = decide([scored("rc-001", 1.0), row, scored("rc-003", 0.0)], threshold=0.5)
    assert result["verdict"] == "inconclusive"
    assert result["problems"][0][:2] == ("inconclusive", "rc-002")


def test_one_successful_search_is_scorable():
    row = {"id": "rc-002", "status": "ok", "retrieval_context": [SEARCH_FAIL, "Title: real result"]}
    assert row_problem(row) is None


def test_provider_error_is_inconclusive():
    row = with_problem({"id": "rc-001", "status": "error", "error_type": "APITimeoutError", "error": "timed out"})
    assert decide([row, scored("rc-002", 1.0), scored("rc-003", 0.0)], threshold=0.5)["verdict"] == "inconclusive"


def test_code_error_fails():
    row = with_problem({"id": "rc-001", "status": "error", "error_type": "KeyError", "error": "'messages'"})
    assert decide([row, scored("rc-002", 1.0), scored("rc-003", 1.0)], threshold=0.5)["verdict"] == "fail"


def test_budget_exceeded_fails():
    row = with_problem({"id": "rc-001", "status": "error", "error_type": "BudgetExceeded", "error": "run cost $1.20"})
    assert decide([row, scored("rc-002", 1.0), scored("rc-003", 1.0)], threshold=0.5)["verdict"] == "fail"


def test_missing_row_is_inconclusive():
    result = decide([scored("rc-001", 1.0), scored("rc-002", 0.0)], threshold=0.5)
    assert result["verdict"] == "inconclusive"
    assert ("inconclusive", "rc-003") == result["problems"][0][:2]


def test_fail_beats_inconclusive():
    blocked = with_problem({"id": "rc-001", "status": "ok", "retrieval_context": [SEARCH_FAIL]})
    crashed = with_problem({"id": "rc-002", "status": "error", "error_type": "TypeError", "error": "x"})
    assert decide([blocked, crashed, scored("rc-003", 1.0)], threshold=0.5)["verdict"] == "fail"


def test_gate_uses_three_prompts():
    assert GATE_IDS == ("rc-001", "rc-002", "rc-003")


def test_no_write_file_scores_zero_without_judge():
    row = {"id": "rc-002", "status": "ok", "tool_calls": ["task", "web_search", "read_file", "finalize_report"]}
    assert "write_file never ran" in no_notes_reason(row)


def test_write_file_ran_goes_to_judge():
    row = {"id": "rc-004", "status": "ok", "tool_calls": ["task", "web_search", "write_file", "task", "read_file"]}
    assert no_notes_reason(row) is None


def test_empty_final_answer_fails():
    # capture_runs records a truncated finalize_report as EmptyFinalAnswer
    row = with_problem({"id": "rc-001", "status": "error", "error_type": "EmptyFinalAnswer",
                        "error": "empty final answer (invalid tool calls: ['finalize_report'])"})
    assert decide([row, scored("rc-002", 1.0), scored("rc-003", 1.0)], threshold=0.5)["verdict"] == "fail"


def blocked(pid):
    return with_problem({"id": pid, "status": "ok", "retrieval_context": [SEARCH_FAIL, SEARCH_FAIL]})


def test_blocked_search_cannot_hide_a_real_regression():
    # best case (blocked row = 1.0) is 0.33 < 0.6: fails whatever it would have scored
    result = decide([blocked("rc-001"), scored("rc-002", 0.0), scored("rc-003", 0.0)], threshold=0.6)
    assert result["verdict"] == "fail"


def test_blocked_search_does_not_fail_a_healthy_pr():
    # worst case (blocked row = 0.0) is 0.67 >= 0.6: passes whatever it would have scored
    result = decide([blocked("rc-001"), scored("rc-002", 1.0), scored("rc-003", 1.0)], threshold=0.6)
    assert result["verdict"] == "pass"


def test_blocked_row_that_could_flip_the_verdict_is_inconclusive():
    result = decide([blocked("rc-001"), scored("rc-002", 1.0), scored("rc-003", 0.0)], threshold=0.6)
    assert result["verdict"] == "inconclusive"


def test_all_blocked_is_inconclusive_not_fail():
    result = decide([blocked("rc-001"), blocked("rc-002"), blocked("rc-003")], threshold=0.6)
    assert result["verdict"] == "inconclusive"
    assert result["mean"] is None
