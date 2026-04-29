from __future__ import annotations

import json
from typing import Any

from aula_project.scheduled_review import NewThreadMessages, build_openai_prompt_input


REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "thread_id": {"type": "string"},
                    "flag": {"type": "boolean"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                    "reason": {"type": "string"},
                    "recommended_action": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "thread_id",
                    "flag",
                    "priority",
                    "reason",
                    "recommended_action",
                    "evidence",
                ],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["items", "summary"],
}


def review_new_messages_with_openai(
    items: list[NewThreadMessages],
    *,
    model: str,
) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - depends on optional runtime dependency
        raise RuntimeError("The 'openai' package is not installed. Run 'uv sync --dev'.") from exc

    client = OpenAI()
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    "You review Danish Aula school messages for a parent. "
                    "Return strict JSON matching the schema. Be conservative but do not miss practical logistics."
                ),
            },
            {
                "role": "user",
                "content": build_openai_prompt_input(items),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "aula_message_relevance_review",
                "strict": True,
                "schema": REVIEW_SCHEMA,
            }
        },
    )
    return json.loads(response.output_text)
