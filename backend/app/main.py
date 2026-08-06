"""FastAPI backend for the Summit Air Vapi phone agent.

Exposes one webhook route per tool that the Vapi assistant can call:
  - POST /tools/check-availability
  - POST /tools/book-appointment
  - POST /tools/escalate-urgent

Plus:
  - GET /health           liveness probe (also used as a keep-alive ping target)
  - GET /bookings         simple HTML view of everything booked/escalated so far

See prompts/system_prompt.md for how the assistant decides what/when to call.
"""
from __future__ import annotations

import html
import logging
import os
import traceback
from typing import Any, Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import slack, storage
from .availability import get_available_slots
from .security import is_valid_signature

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("summit_air")

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

app = FastAPI(title="Summit Air Phone Agent Backend")


@app.on_event("startup")
def on_startup() -> None:
    storage.init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # TEMPORARY diagnostic: capture unhandled exceptions in the same debug
    # log as raw requests, so tool-call crashes are visible via
    # /debug/raw-tool-requests without needing dashboard log access.
    logger.exception("Unhandled exception on %s", request.url.path)
    try:
        import json as _json

        storage.log_raw_tool_request(
            request.url.path,
            _json.dumps({"unhandled_exception": "".join(traceback.format_exception(exc))}),
        )
    except Exception:
        logger.exception("Failed to log unhandled exception")
    return JSONResponse(status_code=500, content={"error": "internal error"})


# ---------------------------------------------------------------------------
# Vapi tool-call helpers
# ---------------------------------------------------------------------------

def _extract_tool_calls(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Pull the list of tool calls and the call id out of a Vapi webhook payload."""
    message = payload.get("message", payload)
    tool_calls = message.get("toolCallList") or message.get("toolCalls") or []
    call = message.get("call") or {}
    call_id = call.get("id")
    return tool_calls, call_id


def _get_arguments(tool_call: dict[str, Any]) -> dict[str, Any]:
    # Vapi's own docs have shown both a flat shape (arguments directly on the
    # tool call) and a nested shape (arguments under `function`) - handle both.
    function = tool_call.get("function") or {}
    arguments = function.get("arguments")
    if arguments is None:
        arguments = tool_call.get("arguments", {})
    if isinstance(arguments, str):
        import json

        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {}
    return arguments or {}


def _get_tool_call_id(tool_call: dict[str, Any]) -> Optional[str]:
    return tool_call.get("id") or tool_call.get("toolCallId")


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"error": "invalid signature"})


_SENSITIVE_HEADER_PREFIXES = ("authorization",)


def _safe_headers(request: Request) -> dict[str, str]:
    return {
        k: v for k, v in request.headers.items() if not k.lower().startswith(_SENSITIVE_HEADER_PREFIXES)
    }


async def _read_and_verify(request: Request) -> Optional[dict[str, Any]]:
    raw_body = await request.body()
    signature = request.headers.get("x-vapi-signature")
    secret_header = request.headers.get("x-vapi-secret")
    valid = is_valid_signature(raw_body, signature, secret_header)

    # TEMPORARY diagnostic: log every raw tool-call payload we receive, plus
    # whether it passed signature verification and the full header set, so we
    # can debug integration issues without dashboard log access. Safe to
    # remove once the auth mechanism is confirmed stable.
    try:
        debug_record = {
            "headers": _safe_headers(request),
            "signature_valid": valid,
            "body": raw_body.decode("utf-8", errors="replace"),
        }
        import json as _json

        storage.log_raw_tool_request(request.url.path, _json.dumps(debug_record))
    except Exception:
        logger.exception("Failed to log raw tool request")

    if not valid:
        return None
    import json

    return json.loads(raw_body or b"{}")


def _results_response(tool_call_id: str, result: str) -> dict[str, Any]:
    return {"results": [{"toolCallId": tool_call_id, "result": result}]}


# ---------------------------------------------------------------------------
# Tool: check_availability
# ---------------------------------------------------------------------------

@app.post("/tools/check-availability")
async def check_availability(request: Request, x_vapi_signature: Optional[str] = Header(default=None)):
    payload = await _read_and_verify(request)
    if payload is None:
        return _unauthorized()

    tool_calls, call_id = _extract_tool_calls(payload)
    results = []
    for tool_call in tool_calls:
        args = _get_arguments(tool_call)
        urgency_level = str(args.get("urgency_level", "routine")).lower()
        property_type = args.get("property_type", "residential")

        slots = get_available_slots(urgency_level)
        slots_text = "; ".join(slots)
        result = (
            f"Available windows for this {property_type} {urgency_level} request: {slots_text}. "
            "Offer these to the caller and ask which works best."
        )
        logger.info("check_availability call_id=%s urgency=%s -> %s", call_id, urgency_level, slots)
        results.append({"toolCallId": _get_tool_call_id(tool_call), "result": result})

    return {"results": results}


# ---------------------------------------------------------------------------
# Tool: book_appointment
# ---------------------------------------------------------------------------

@app.post("/tools/book-appointment")
async def book_appointment(request: Request, x_vapi_signature: Optional[str] = Header(default=None)):
    payload = await _read_and_verify(request)
    if payload is None:
        return _unauthorized()

    tool_calls, call_id = _extract_tool_calls(payload)
    results = []
    for tool_call in tool_calls:
        args = _get_arguments(tool_call)

        customer_name = str(args.get("name", "")).strip() or "Unknown caller"
        phone_number = str(args.get("phone", "")).strip() or "Unknown"
        address = str(args.get("address", "")).strip() or "Unknown"
        property_type = str(args.get("property_type", "residential")).lower()
        issue_summary = str(args.get("issue_summary", "")).strip() or "Not specified"
        urgency_level = str(args.get("urgency_level", "routine")).lower()
        selected_window = str(args.get("selected_window", "")).strip() or "Unspecified window"
        vulnerable_occupant = bool(args.get("vulnerable_occupant", False))
        notes = args.get("notes")

        booking = storage.create_booking(
            call_id=call_id,
            customer_name=customer_name,
            phone_number=phone_number,
            address=address,
            property_type=property_type,
            issue_summary=issue_summary,
            urgency_level=urgency_level,
            vulnerable_occupant=vulnerable_occupant,
            selected_window=selected_window,
            notes=notes,
        )

        confirmation_number = booking["confirmation_number"]
        logger.info(
            "book_appointment call_id=%s confirmation=%s urgency=%s",
            call_id, confirmation_number, urgency_level,
        )

        await slack.send_booking_notification(
            confirmation_number=confirmation_number,
            customer_name=customer_name,
            urgency_level=urgency_level,
            selected_window=selected_window,
        )

        result = (
            f"Booked. Confirmation number {confirmation_number}. "
            f"{customer_name}, {property_type}, window: {selected_window}. "
            "Read this confirmation number back to the caller clearly."
        )
        results.append({"toolCallId": _get_tool_call_id(tool_call), "result": result})

    return {"results": results}


# ---------------------------------------------------------------------------
# Tool: escalate_urgent
# ---------------------------------------------------------------------------

@app.post("/tools/escalate-urgent")
async def escalate_urgent(request: Request, x_vapi_signature: Optional[str] = Header(default=None)):
    payload = await _read_and_verify(request)
    if payload is None:
        return _unauthorized()

    tool_calls, call_id = _extract_tool_calls(payload)
    results = []
    for tool_call in tool_calls:
        args = _get_arguments(tool_call)

        reason = str(args.get("reason", "other")).strip() or "other"
        customer_name = args.get("name")
        phone_number = args.get("phone")
        address = args.get("address")
        details = args.get("details")

        storage.create_escalation(
            call_id=call_id,
            customer_name=customer_name,
            phone_number=phone_number,
            address=address,
            reason=reason,
            details=details,
        )

        logger.warning("escalate_urgent call_id=%s reason=%s", call_id, reason)

        await slack.send_urgent_alert(
            reason=reason,
            customer_name=customer_name,
            phone_number=phone_number,
            address=address,
            details=details,
        )

        result = (
            "Dispatch has been alerted immediately. Continue the call: if this is a gas smell, "
            "make sure the caller knows to leave the property and call the gas company or 911 "
            "before anything else. Otherwise continue collecting booking details as priority."
        )
        results.append({"toolCallId": _get_tool_call_id(tool_call), "result": result})

    return {"results": results}


# ---------------------------------------------------------------------------
# Admin view
# ---------------------------------------------------------------------------

def _check_admin(token: Optional[str]) -> bool:
    if not ADMIN_TOKEN:
        return True
    return token == ADMIN_TOKEN


@app.get("/debug/raw-tool-requests")
def debug_raw_tool_requests(token: Optional[str] = None, limit: int = 20):
    """TEMPORARY: inspect exactly what Vapi is sending, to debug integration
    issues. Remove once the tool-call format is confirmed stable."""
    if not _check_admin(token):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return {"requests": storage.list_raw_tool_requests(limit)}


@app.get("/bookings", response_class=HTMLResponse)
def view_bookings(token: Optional[str] = None):
    if not _check_admin(token):
        return HTMLResponse("<h1>Unauthorized</h1>", status_code=401)

    bookings = storage.list_bookings()
    escalations = storage.list_escalations()

    def row(b: dict[str, Any]) -> str:
        cells = [
            b.get("confirmation_number", ""),
            b.get("created_at", ""),
            b.get("customer_name", ""),
            b.get("phone_number", ""),
            b.get("address", ""),
            b.get("property_type", ""),
            b.get("urgency_level", ""),
            b.get("issue_summary", ""),
            b.get("selected_window", ""),
            "yes" if b.get("vulnerable_occupant") else "no",
        ]
        return "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in cells) + "</tr>"

    def esc_row(e: dict[str, Any]) -> str:
        cells = [
            e.get("created_at", ""),
            e.get("reason", ""),
            e.get("customer_name", ""),
            e.get("phone_number", ""),
            e.get("address", ""),
            e.get("details", ""),
        ]
        return "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in cells) + "</tr>"

    body = f"""
    <html>
    <head>
        <title>Summit Air - Bookings</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; margin: 2rem; color: #222; }}
            h1 {{ margin-bottom: 0.25rem; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
            th, td {{ border: 1px solid #ddd; padding: 6px 10px; font-size: 13px; text-align: left; }}
            th {{ background: #f4f4f4; }}
            .urgent {{ color: #b00020; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>Summit Air - Bookings</h1>
        <p>{len(bookings)} booking(s)</p>
        <table>
            <tr><th>Confirmation</th><th>Created</th><th>Name</th><th>Phone</th><th>Address</th>
                <th>Type</th><th>Urgency</th><th>Issue</th><th>Window</th><th>Vulnerable occupant</th></tr>
            {''.join(row(b) for b in bookings)}
        </table>
        <h1 class="urgent">Escalations</h1>
        <p>{len(escalations)} escalation(s)</p>
        <table>
            <tr><th>Created</th><th>Reason</th><th>Name</th><th>Phone</th><th>Address</th><th>Details</th></tr>
            {''.join(esc_row(e) for e in escalations)}
        </table>
    </body>
    </html>
    """
    return HTMLResponse(body)
