"""JSON-schema definitions for the tools exposed to the Vapi assistant.

Keep parameter names/types in sync with what backend/app/main.py expects and
what prompts/system_prompt.md instructs the model to pass.
"""

PROPERTY_TYPE_ENUM = ["residential", "commercial"]
URGENCY_ENUM = ["routine", "priority", "emergency"]
ESCALATION_REASON_ENUM = [
    "gas_smell",
    "no_heat_winter_vulnerable",
    "no_ac_medical",
    "other",
]


def build_tool_definitions(backend_base_url: str, tool_secret: str) -> list[dict]:
    def server(path: str) -> dict:
        cfg = {"url": backend_base_url.rstrip("/") + path}
        if tool_secret:
            cfg["secret"] = tool_secret
        return cfg

    return [
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": (
                    "Look up real appointment windows to offer the caller. Call this once you "
                    "know whether the job is residential or commercial and how urgent it is, "
                    "before proposing any specific times."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "property_type": {
                            "type": "string",
                            "enum": PROPERTY_TYPE_ENUM,
                            "description": "Whether the service address is a home or a business.",
                        },
                        "urgency_level": {
                            "type": "string",
                            "enum": URGENCY_ENUM,
                            "description": "How urgent the situation is, per the urgency rules.",
                        },
                    },
                    "required": ["property_type", "urgency_level"],
                },
            },
            "server": server("/tools/check-availability"),
        },
        {
            "type": "function",
            "function": {
                "name": "book_appointment",
                "description": (
                    "Book the service call once the caller has picked an appointment window and "
                    "you have all required details. Returns a confirmation number to read back."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Caller's full name."},
                        "phone": {"type": "string", "description": "Best callback phone number."},
                        "address": {
                            "type": "string",
                            "description": "Full service address, including city.",
                        },
                        "property_type": {
                            "type": "string",
                            "enum": PROPERTY_TYPE_ENUM,
                        },
                        "issue_summary": {
                            "type": "string",
                            "description": "Brief summary of the HVAC issue or maintenance request.",
                        },
                        "urgency_level": {
                            "type": "string",
                            "enum": URGENCY_ENUM,
                        },
                        "selected_window": {
                            "type": "string",
                            "description": "The appointment window the caller chose, exactly as offered.",
                        },
                        "vulnerable_occupant": {
                            "type": "boolean",
                            "description": (
                                "True if an elderly person, infant, or someone with a relevant "
                                "medical condition is in the home and factored into urgency."
                            ),
                        },
                        "notes": {
                            "type": "string",
                            "description": "Any extra context (e.g. calling on behalf of someone else).",
                        },
                    },
                    "required": [
                        "name",
                        "phone",
                        "address",
                        "property_type",
                        "issue_summary",
                        "urgency_level",
                        "selected_window",
                    ],
                },
            },
            "server": server("/tools/book-appointment"),
        },
        {
            "type": "function",
            "function": {
                "name": "escalate_urgent",
                "description": (
                    "Immediately alert human dispatch. Call this as soon as you confirm a gas "
                    "smell, no heat with a vulnerable occupant in cold weather, or no AC with a "
                    "medical condition - even before you've finished collecting all booking "
                    "details. Safe to call with partial information."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "enum": ESCALATION_REASON_ENUM,
                        },
                        "name": {"type": "string", "description": "Caller's name, if known yet."},
                        "phone": {"type": "string", "description": "Callback number, if known yet."},
                        "address": {"type": "string", "description": "Address, if known yet."},
                        "details": {
                            "type": "string",
                            "description": "Whatever context is relevant for dispatch.",
                        },
                    },
                    "required": ["reason", "details"],
                },
            },
            "server": server("/tools/escalate-urgent"),
        },
    ]
