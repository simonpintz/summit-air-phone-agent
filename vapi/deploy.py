#!/usr/bin/env python3
"""Idempotent deploy script for the Summit Air Vapi assistant.

Creates (or updates, if already created) the custom tools, the assistant
(system prompt + first message + tools), and a phone number, all wired to
the backend at BACKEND_BASE_URL.

Usage:
    export VAPI_API_KEY=...
    export VAPI_TOOL_SECRET=...        # shared secret for tool webhook HMAC
    export BACKEND_BASE_URL=https://your-backend.onrender.com
    export VAPI_AREA_CODE=555          # optional, US area code for the number
    python vapi/deploy.py

Safe to re-run: matches existing tools/assistant/phone number by name and
updates them in place instead of creating duplicates.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from tool_definitions import build_tool_definitions  # noqa: E402

VAPI_API_BASE = "https://api.vapi.ai"
ASSISTANT_NAME = "Summit Air Dispatcher"
PHONE_NUMBER_NAME = "Summit Air Main Line"

REPO_ROOT = Path(__file__).parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "system_prompt.md"


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(f"ERROR: required environment variable {name} is not set.", file=sys.stderr)
        sys.exit(1)
    return value


def _client(api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=VAPI_API_BASE,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30.0,
    )


def parse_prompt_file(path: Path) -> tuple[str, str]:
    """Returns (first_message, system_prompt_body)."""
    content = path.read_text()
    parts = content.split("\n---\n")
    if len(parts) < 3:
        raise ValueError(
            f"Expected {path} to have two '---' separators (header / first message / body)."
        )
    first_message_section = parts[1]
    body = "\n---\n".join(parts[2:]).strip()

    quote_lines = []
    in_quote = False
    for line in first_message_section.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            in_quote = True
            quote_lines.append(stripped.lstrip(">").strip())
        elif in_quote and not stripped:
            break

    first_message = " ".join(quote_lines).strip().strip('"')
    if not first_message:
        raise ValueError("Could not find a blockquoted first message in the prompt file.")

    return first_message, body


def upsert_tools(client: httpx.Client, backend_base_url: str, tool_secret: str) -> list[str]:
    definitions = build_tool_definitions(backend_base_url, tool_secret)

    existing = client.get("/tool").raise_for_status().json()
    existing_by_name = {}
    for tool in existing:
        fn = tool.get("function") or {}
        if fn.get("name"):
            existing_by_name[fn["name"]] = tool

    tool_ids = []
    for definition in definitions:
        name = definition["function"]["name"]
        if name in existing_by_name:
            tool_id = existing_by_name[name]["id"]
            resp = client.patch(
                f"/tool/{tool_id}",
                json={"function": definition["function"], "server": definition["server"]},
            )
            resp.raise_for_status()
            print(f"Updated tool '{name}' ({tool_id})")
        else:
            resp = client.post("/tool", json=definition)
            resp.raise_for_status()
            tool_id = resp.json()["id"]
            print(f"Created tool '{name}' ({tool_id})")
        tool_ids.append(tool_id)

    return tool_ids


def upsert_assistant(client: httpx.Client, tool_ids: list[str], first_message: str, system_prompt: str) -> str:
    payload = {
        "name": ASSISTANT_NAME,
        "firstMessage": first_message,
        "model": {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.4,
            "messages": [{"role": "system", "content": system_prompt}],
            "toolIds": tool_ids,
        },
    }

    existing = client.get("/assistant").raise_for_status().json()
    match = next((a for a in existing if a.get("name") == ASSISTANT_NAME), None)

    if match:
        assistant_id = match["id"]
        resp = client.patch(f"/assistant/{assistant_id}", json=payload)
        resp.raise_for_status()
        print(f"Updated assistant '{ASSISTANT_NAME}' ({assistant_id})")
    else:
        resp = client.post("/assistant", json=payload)
        resp.raise_for_status()
        assistant_id = resp.json()["id"]
        print(f"Created assistant '{ASSISTANT_NAME}' ({assistant_id})")

    return assistant_id


def upsert_phone_number(client: httpx.Client, assistant_id: str, area_code: str | None) -> dict:
    existing = client.get("/phone-number").raise_for_status().json()
    match = next((p for p in existing if p.get("name") == PHONE_NUMBER_NAME), None)

    if match:
        phone_id = match["id"]
        resp = client.patch(f"/phone-number/{phone_id}", json={"assistantId": assistant_id})
        resp.raise_for_status()
        number = resp.json()
        print(f"Updated phone number {number.get('number')} ({phone_id}) -> assistant {assistant_id}")
        return number

    payload = {
        "provider": "vapi",
        "name": PHONE_NUMBER_NAME,
        "assistantId": assistant_id,
    }
    if area_code:
        payload["numberDesiredAreaCode"] = area_code

    resp = client.post("/phone-number", json=payload)
    resp.raise_for_status()
    number = resp.json()
    print(f"Created phone number {number.get('number')} ({number.get('id')}) -> assistant {assistant_id}")
    return number


def main() -> None:
    api_key = _require_env("VAPI_API_KEY")
    backend_base_url = _require_env("BACKEND_BASE_URL")
    tool_secret = os.environ.get("VAPI_TOOL_SECRET", "")
    area_code = os.environ.get("VAPI_AREA_CODE") or None

    if not tool_secret:
        print(
            "WARNING: VAPI_TOOL_SECRET is not set - tool webhooks will be deployed without "
            "signature verification. Fine for a quick local test, not recommended once the "
            "number is live.",
            file=sys.stderr,
        )

    first_message, system_prompt = parse_prompt_file(PROMPT_PATH)

    with _client(api_key) as client:
        tool_ids = upsert_tools(client, backend_base_url, tool_secret)
        assistant_id = upsert_assistant(client, tool_ids, first_message, system_prompt)
        number = upsert_phone_number(client, assistant_id, area_code)

    print("\nDone.")
    print(f"Assistant ID: {assistant_id}")
    print(f"Phone number: {number.get('number')}")
    print("Dashboard: https://dashboard.vapi.ai/assistants")


if __name__ == "__main__":
    main()
