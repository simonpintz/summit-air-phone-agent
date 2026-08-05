"""Slack incoming-webhook notifier for urgent escalations and new bookings."""
from __future__ import annotations

import os
from typing import Optional

import httpx

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

REASON_LABELS = {
    "gas_smell": "Gas smell reported",
    "no_heat_winter_vulnerable": "No heat + vulnerable occupant",
    "no_ac_medical": "No AC + medical condition",
    "other": "Flagged urgent",
}


async def send_urgent_alert(
    *,
    reason: str,
    customer_name: Optional[str],
    phone_number: Optional[str],
    address: Optional[str],
    details: Optional[str],
) -> None:
    if not SLACK_WEBHOOK_URL:
        return

    label = REASON_LABELS.get(reason, reason)
    text = (
        f":rotating_light: *URGENT - {label}* :rotating_light:\n"
        f"*Name:* {customer_name or 'unknown'}\n"
        f"*Phone:* {phone_number or 'unknown'}\n"
        f"*Address:* {address or 'unknown'}\n"
        f"*Details:* {details or 'n/a'}"
    )
    payload = {"text": text}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(SLACK_WEBHOOK_URL, json=payload)
        except httpx.HTTPError:
            # Never let a Slack outage break the call - the booking/escalation
            # is already persisted in SQLite regardless of alert delivery.
            pass


async def send_booking_notification(*, confirmation_number: str, customer_name: str,
                                      urgency_level: str, selected_window: str) -> None:
    if not SLACK_WEBHOOK_URL:
        return

    text = (
        f":white_check_mark: *New booking ({urgency_level})* — {confirmation_number}\n"
        f"*Name:* {customer_name}\n"
        f"*Window:* {selected_window}"
    )
    payload = {"text": text}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(SLACK_WEBHOOK_URL, json=payload)
        except httpx.HTTPError:
            pass
