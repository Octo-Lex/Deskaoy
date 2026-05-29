"""JSON-RPC 2.0 protocol helpers for IPC.

Serializes AgentGoal/AgentContext into JSON-RPC requests and
deserializes JSON-RPC responses back into AgentResult objects.

All types come from ``deskaoy.os_types`` — no custom protocol types.

Review note (FLAG-01): os_types dataclasses do NOT have ``.as_dict()``.
We use ``dataclasses.asdict()`` for serialization and field-by-field
reconstruction for deserialization.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import uuid
from typing import Any

from deskaoy.os_types import (
    AgentContext,
    AgentGoal,
    AgentResult,
    CancellationToken,
    Confidence,
    ErrorCode,
    Issue,
    IssueSeverity,
    Learning,
    MutationRecord,
    ResourceRef,
    RestoreMethod,
    ResultStatus,
    ReviewItem,
    SuggestedFollowup,
)

logger = logging.getLogger(__name__)

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

VALID_METHODS = frozenset({"execute", "ping", "status", "shutdown"})


# ---------------------------------------------------------------------------
# Encoding (Python objects → JSON-RPC dict)
# ---------------------------------------------------------------------------

def encode_request(
    method: str,
    params: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Encode a JSON-RPC 2.0 request envelope."""
    if request_id is None:
        request_id = str(uuid.uuid4())
    envelope: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        envelope["params"] = params
    return envelope


def encode_response(
    request_id: str,
    result: Any = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Encode a JSON-RPC 2.0 response envelope."""
    envelope: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        envelope["error"] = error
    else:
        envelope["result"] = result
    return envelope


def goal_to_params(goal: AgentGoal, context: AgentContext) -> dict[str, Any]:
    """Serialize AgentGoal + AgentContext into JSON-RPC params dict.

    Uses ``dataclasses.asdict()`` — CancellationToken is handled specially
    since it's a mutable object (we serialize only ``_cancelled``).
    """
    goal_dict = dataclasses.asdict(goal)
    ctx_dict = dataclasses.asdict(context)
    # CancellationToken is not JSON-serializable as-is; keep the cancelled flag.
    if "cancellation_token" in ctx_dict and isinstance(
        ctx_dict["cancellation_token"], dict
    ):
        ct = ctx_dict["cancellation_token"]
        ctx_dict["cancellation_token"] = {"cancelled": ct.get("_cancelled", False)}
    return {"goal": goal_dict, "context": ctx_dict}


def build_execute_request(
    goal: AgentGoal,
    context: AgentContext,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build a complete JSON-RPC request for the ``execute`` method."""
    return encode_request("execute", goal_to_params(goal, context), request_id)


def build_ping_request(request_id: str | None = None) -> dict[str, Any]:
    """Build a JSON-RPC ping request."""
    return encode_request("ping", request_id=request_id)


def build_status_request(request_id: str | None = None) -> dict[str, Any]:
    """Build a JSON-RPC status request."""
    return encode_request("status", request_id=request_id)


def build_shutdown_request(request_id: str | None = None) -> dict[str, Any]:
    """Build a JSON-RPC shutdown request."""
    return encode_request("shutdown", request_id=request_id)


# ---------------------------------------------------------------------------
# Decoding (JSON-RPC dict → Python objects)
# ---------------------------------------------------------------------------

def parse_request(raw: bytes | str) -> dict[str, Any]:
    """Parse and validate a JSON-RPC 2.0 request.

    Returns the parsed dict or raises a JSON-RPC error dict.
    """
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        msg = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _error_response("", PARSE_ERROR, f"Parse error: {exc}")

    if not isinstance(msg, dict):
        return _error_response("", INVALID_REQUEST, "Request must be a JSON object")

    # Validate required fields
    if "method" not in msg:
        return _error_response(
            msg.get("id", ""), INVALID_REQUEST, "Missing 'method' field"
        )

    method = msg["method"]
    if method not in VALID_METHODS:
        return _error_response(
            msg.get("id", ""), METHOD_NOT_FOUND, f"Unknown method: {method}"
        )

    return msg


def decode_goal_from_params(params: dict[str, Any]) -> tuple[AgentGoal, AgentContext]:
    """Extract AgentGoal and AgentContext from JSON-RPC params dict."""
    goal_data = params["goal"]
    ctx_data = params["context"]

    goal = AgentGoal(
        capability=goal_data["capability"],
        params=goal_data.get("params", {}),
        priority=goal_data.get("priority", "normal"),
        parent_task_id=goal_data.get("parent_task_id", ""),
        related_results=goal_data.get("related_results", []),
        user_preferences=goal_data.get("user_preferences", {}),
    )

    # Reconstruct CancellationToken
    ct_data = ctx_data.get("cancellation_token", {})
    ct = CancellationToken()
    if isinstance(ct_data, dict) and ct_data.get("cancelled", False):
        ct.cancel()

    context = AgentContext(
        execution_id=ctx_data["execution_id"],
        idempotency_key=ctx_data["idempotency_key"],
        task_id=ctx_data["task_id"],
        user_id=ctx_data["user_id"],
        session_id=ctx_data["session_id"],
        dry_run=ctx_data.get("dry_run", False),
        timeout_seconds=ctx_data.get("timeout_seconds", 60),
        cancellation_token=ct,
        client=ctx_data.get("client"),
        additional_clients=ctx_data.get("additional_clients", {}),
        user_memory=ctx_data.get("user_memory", {}),
        recent_activity=ctx_data.get("recent_activity", []),
        connected_services=ctx_data.get("connected_services", {}),
        available_tools=ctx_data.get("available_tools", []),
        autonomy_mode=ctx_data.get("autonomy_mode", "autopilot"),
        max_cost=ctx_data.get("max_cost", 0.0),
        locale=ctx_data.get("locale", "en-US"),
        timezone=ctx_data.get("timezone", "America/New_York"),
    )
    return goal, context


def decode_result_from_response(response: dict[str, Any]) -> AgentResult:
    """Decode a JSON-RPC response into an AgentResult.

    If the response contains an ``error`` field, returns a FAILURE
    AgentResult with the error details.
    """
    if "error" in response:
        err = response["error"]
        return AgentResult(
            execution_id="",
            status=ResultStatus.FAILURE,
            summary=err.get("message", "Unknown JSON-RPC error"),
            data={"error_code": err.get("code", -1)},
            confidence=Confidence(score=0.0, reason="JSON-RPC error"),
            issues=[Issue(
                severity=IssueSeverity.ERROR,
                code=ErrorCode.INTERNAL_ERROR,
                message=err.get("message", "Unknown error"),
            )],
        )

    result_data = response.get("result", {})
    return _dict_to_agent_result(result_data)


def _dict_to_agent_result(d: dict[str, Any]) -> AgentResult:
    """Reconstruct an AgentResult from its dict representation."""
    return AgentResult(
        execution_id=d.get("execution_id", ""),
        status=ResultStatus(d.get("status", "failure")),
        summary=d.get("summary", ""),
        data=d.get("data", {}),
        artifacts=_deserialize_list(d.get("artifacts", []), ResourceRef),
        mutations=_deserialize_list(d.get("mutations", []), MutationRecord),
        confidence=_deserialize_confidence(d.get("confidence", {})),
        issues=_deserialize_list(d.get("issues", []), Issue),
        needs_review=_deserialize_list(d.get("needs_review", []), ReviewItem),
        suggested_followups=_deserialize_list(
            d.get("suggested_followups", []), SuggestedFollowup
        ),
        learnings=_deserialize_list(d.get("learnings", []), Learning),
        metadata=d.get("metadata", {}),
    )


def _deserialize_confidence(d: dict[str, Any]) -> Confidence:
    """Deserialize a Confidence dict."""
    if not d:
        return Confidence(score=0.0, reason="unset")
    return Confidence(
        score=d.get("score", 0.0),
        reason=d.get("reason", ""),
        factors=d.get("factors", {}),
    )


def _deserialize_list(items: list[dict], cls: type) -> list[Any]:
    """Deserialize a list of dicts into dataclass instances.

    Handles common dataclasses used in AgentResult. Falls back to
    returning the raw dicts for unknown types.
    """
    result = []
    for item in items:
        if not isinstance(item, dict):
            result.append(item)
            continue
        try:
            if cls is ResourceRef:
                result.append(ResourceRef(
                    uri=item.get("uri", ""),
                    mime_type=item.get("mime_type", ""),
                    size_bytes=item.get("size_bytes", 0),
                    filename=item.get("filename", ""),
                    expires_at=item.get("expires_at", ""),
                ))
            elif cls is MutationRecord:
                result.append(MutationRecord(
                    resource_type=item.get("resource_type", ""),
                    resource_id=item.get("resource_id", ""),
                    operation=item.get("operation", ""),
                    before_state=item.get("before_state"),
                    after_state=item.get("after_state"),
                    restore_method=RestoreMethod(item.get("restore_method", "none")),
                    state_version=item.get("state_version", ""),
                ))
            elif cls is Issue:
                result.append(Issue(
                    severity=IssueSeverity(item.get("severity", "error")),
                    code=ErrorCode(item.get("code", "internal_error")),
                    message=item.get("message", ""),
                    details=item.get("details", {}),
                    retry_possible=item.get("retry_possible", False),
                    retry_after_seconds=item.get("retry_after_seconds", 0),
                ))
            elif cls is ReviewItem:
                result.append(ReviewItem(
                    item=item.get("item", ""),
                    reason=item.get("reason", ""),
                    severity=item.get("severity", "suggestion"),
                    options=item.get("options", []),
                    action_class=item.get("action_class", ""),
                ))
            elif cls is SuggestedFollowup:
                result.append(SuggestedFollowup(
                    label=item.get("label", ""),
                    agent=item.get("agent", ""),
                    capability=item.get("capability", ""),
                    params=item.get("params", {}),
                    priority=item.get("priority", "normal"),
                    action_class=item.get("action_class", ""),
                ))
            elif cls is Learning:
                result.append(Learning(
                    type=item.get("type", "observation"),
                    domain=item.get("domain", ""),
                    key=item.get("key", ""),
                    value=item.get("value"),
                    confidence=item.get("confidence", 0.0),
                    source=item.get("source", ""),
                    expires_at=item.get("expires_at", ""),
                ))
            else:
                result.append(item)
        except Exception:
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_response(
    request_id: str | None, code: int, message: str
) -> dict[str, Any]:
    """Build a JSON-RPC error response."""
    return encode_response(
        request_id=request_id or "",
        error={"code": code, "message": message},
    )


def json_dumps(obj: Any) -> bytes:
    """Serialize a JSON-RPC message to UTF-8 bytes with newline delimiter."""
    return (json.dumps(obj, default=str) + "\n").encode("utf-8")


def json_loads_line(line: bytes) -> dict[str, Any]:
    """Deserialize a single newline-delimited JSON-RPC message."""
    return json.loads(line.decode("utf-8").strip())
