STREAM_POLICY_VERSION = "voxlush.stream.v4"


def execution_state(result):
    """Execution evidence is independent of answer validity and cost settlement.

    Old saved results lack this field. Preserve explicit old completion evidence;
    an old parser error without such evidence cannot prove termination.
    """
    state = result.get("execution_state")
    if state in {"not_sent", "execution_unknown", "terminated"}:
        return state
    category = result.get("error_category")
    if category == "not_sent":
        return "not_sent"
    if result.get("response_complete") or result.get("finish_reason"):
        return "terminated"
    if category in {"outcome_unknown", "malformed_response"}:
        return "execution_unknown"
    return "terminated"  # Legacy settled/fixture results used the v1-v3 contract.
