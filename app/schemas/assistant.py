from typing import Any, Optional

from pydantic import BaseModel, Field


class AssistantChatRequest(BaseModel):
    """OpenAI-compatible chat completion body forwarded to OpenRouter."""

    messages: list[dict[str, Any]]
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[Any] = Field(default=None)
    temperature: float = 0.25
    model: Optional[str] = None
