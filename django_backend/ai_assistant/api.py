"""Ninja router: POST /chat (read-only) + GET /context (safe metadata)."""

import logging
import uuid

from ninja import Router
from ninja_jwt.authentication import JWTAuth

from .analytics import build_response
from .context import ENTITIES, ENTITY_NOUNS
from .data_service import execute_plan
from .observability import Timer, log_ai_operation
from .permissions import is_admin
from .planner import gemini_explain, new_conversation_id, parse_message
from .schemas import (
    ChatRequestSchema,
    ChatResponseSchema,
    ResponseMetadataSchema,
    VisualizationSpecSchema,
)
from .validators import validate_query_plan

logger = logging.getLogger(__name__)
router = Router()

# In-memory conversation history (last 10 turns per conversation).
_CONVERSATIONS: dict[str, list] = {}


@router.get("/context", auth=JWTAuth())
def ai_context(request):
    """Safe, read-only entity metadata for clients/debugging. No PII."""
    return {
        entity: {
            "label": meta["label"],
            "description": meta["description"],
            "fields": meta["safe_fields"],
            "status_values": meta["status_values"],
        }
        for entity, meta in ENTITIES.items()
    }


@router.post("/chat", response=ChatResponseSchema, auth=JWTAuth())
def ai_chat(request, payload: ChatRequestSchema):
    conversation_id = payload.conversation_id or new_conversation_id()
    history = _CONVERSATIONS.get(conversation_id, [])
    admin = is_admin(request)

    with Timer() as timer:
        try:
            plan, confidence, note = parse_message(payload.message, history)
            if plan is None:
                _remember(conversation_id, history, {}, {}, [])
                log_ai_operation(
                    question=payload.message, intent="clarify", entities=[],
                    filters={}, record_count=0, chart_type="none",
                    execution_ms=timer.ms if hasattr(timer, "ms") else 0,
                )
                return _response(
                    message=note, rows=[], viz=_empty_viz(),
                    plan={"entity": "", "operation": "", "filters": {}, "date_range": {}},
                    chart="none", ms=0,
                )
            rows, provenance = execute_plan(plan, admin=admin)
            message, data, viz = build_response(plan, rows, provenance, admin)
            record_count = _record_count(plan, rows)
            if plan.get("operation") in ("brief", "advise", "capabilities", "audit"):
                # Composed answers; polishing would shrink them away.
                polished = None
            else:
                noun = ENTITY_NOUNS.get(plan.get("entity"), ("record", "records"))[0]
                op = plan.get("operation")
                field = (plan.get("field") or "").replace("_", " ")
                if op == "count":
                    measure = "a count of records"
                elif op in ("sum", "avg", "min", "max"):
                    measure = f"{op} of {field or 'the amount'}"
                elif op in ("group_count", "group_sum", "top_n"):
                    measure = "per-group totals from real rows"
                elif op == "fulfilment":
                    measure = "delivered vs ordered quantities for one order"
                else:
                    measure = ""
                polished = gemini_explain(message, data, noun, measure)
            if polished:
                message = polished
            _remember(conversation_id, history, plan, provenance, rows,
                      user_message=payload.message)
            ms = getattr(timer, "ms", 0)
            log_ai_operation(
                question=payload.message, intent=plan.get("operation", ""),
                entities=[plan.get("entity", "")], filters=plan.get("filters", {}),
                record_count=record_count, chart_type=viz.get("type", "none"),
                execution_ms=ms, tool=provenance.get("tool", ""),
                plan_source=note,
            )
            return _response(message, data, viz, plan, viz.get("type", "none"), ms,
                             record_count, tool=provenance.get("tool", ""))
        except Exception as exc:  # never leak stack traces or raw SQL
            logger.exception("ai_chat failed")
            ms = getattr(timer, "ms", 0)
            log_ai_operation(
                question=payload.message, intent="error", entities=[],
                filters={}, record_count=0, chart_type="none",
                execution_ms=ms, error=str(exc),
            )
            return _response(
                message="I couldn't answer that because of an internal error. "
                        "Try a narrower question, e.g. a specific order number or month.",
                rows=[], viz=_empty_viz(),
                plan={"entity": "", "operation": "", "filters": {}, "date_range": {}},
                chart="none", ms=ms,
            )


def _remember(conversation_id: str, history: list, plan: dict,
               provenance: dict, rows: list, user_message: str = ""):
    history.append({
        "message": (user_message or "")[:300],
        "entity": plan.get("entity"),
        "filters": dict(plan.get("filters") or {}),
        "date_range": dict(plan.get("date_range") or {}),
        "plan": {
            "entity": plan.get("entity"),
            "operation": plan.get("operation"),
            "field": plan.get("field"),
            "group_by": plan.get("group_by"),
            "filters": dict(plan.get("filters") or {}),
            "date_range": dict(plan.get("date_range") or {}),
            "limit": plan.get("limit"),
            "chart": plan.get("chart"),
        },
    })
    _CONVERSATIONS[conversation_id] = history[-10:]


def _record_count(plan: dict, rows: list) -> int:
    """Real records analyzed: for scalar count ops the value IS the count."""
    if plan.get("operation") == "count" and rows:
        try:
            return int(rows[0].get("value") or 0)
        except (TypeError, ValueError):
            return 0
    return len(rows) if isinstance(rows, list) else 0


def _empty_viz() -> dict:
    return {"type": "none", "title": None, "x_key": None, "y_key": None, "series": []}


def _response(message, rows, viz, plan, chart, ms, record_count=None, tool=""):
    if record_count is None:
        record_count = len(rows) if isinstance(rows, list) else 0
    return {
        "message": message,
        "data": rows if isinstance(rows, list) else [],
        "visualization": {
            "type": viz.get("type", "none"),
            "title": viz.get("title"),
            "x_key": viz.get("x_key"),
            "y_key": viz.get("y_key"),
            "series": viz.get("series", []),
        },
        "metadata": {
            "intent": plan.get("operation"),
            "entities": [plan.get("entity")] if plan.get("entity") else [],
            "filters": plan.get("filters") or {},
            "date_range": plan.get("date_range") or {},
            "record_count": record_count,
            "chart_type": chart,
            "warnings": [],
            "execution_ms": ms,
            "tool": tool,
        },
    }
