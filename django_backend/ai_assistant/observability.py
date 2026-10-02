"""Observability: audit log for AI operations without sensitive data."""

import logging
import time

logger = logging.getLogger(__name__)


def log_ai_operation(
    *,
    question: str,
    intent: str,
    entities: list,
    filters: dict,
    record_count: int,
    chart_type: str,
    execution_ms: int,
    error: str = "",
    tool: str = "",
    plan_source: str = "",
) -> None:
    safe_question = (question or "")[:300]
    logger.info(
        "ai_chat question=%r intent=%s entities=%s filters=%s "
        "records=%s chart=%s elapsed_ms=%s error=%s tool=%s plan_source=%s",
        safe_question,
        intent,
        ",".join(entities or [])[:200],
        {k: str(v)[:60] for k, v in (filters or {}).items()},
        record_count,
        chart_type,
        execution_ms,
        (error or "")[:300],
        tool[:80],
        plan_source[:20],
    )


class Timer:
    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *args):
        self.ms = int((time.monotonic() - self.start) * 1000)
