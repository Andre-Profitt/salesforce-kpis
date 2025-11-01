"""
Flywheel log schema - OpenAI-compatible format for decision capture.

This schema ensures all workload decisions are captured in a standardized
format that can be used for model training, A/B testing, and optimization.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class Message(BaseModel):
    """Chat message in OpenAI format."""
    role: str = Field(..., description="Role: user, assistant, system")
    content: str = Field(..., description="Message content")


class Request(BaseModel):
    """LLM request format."""
    model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Model identifier"
    )
    messages: List[Message] = Field(..., description="Conversation messages")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=256, ge=1)
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional request context"
    )


class Choice(BaseModel):
    """Response choice."""
    message: Message
    finish_reason: Optional[str] = None
    index: int = 0


class Usage(BaseModel):
    """Token usage statistics."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Response(BaseModel):
    """LLM response format."""
    choices: List[Choice] = Field(..., description="Response choices")
    usage: Usage = Field(default_factory=Usage)
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Response metadata (latency, etc.)"
    )


class FlywheelRecord(BaseModel):
    """
    Complete flywheel log record.

    This captures the full decision context for offline analysis and
    model optimization.
    """
    timestamp: int = Field(
        ...,
        description="Unix timestamp (seconds)"
    )
    client_id: str = Field(
        ...,
        description="Client/environment identifier (e.g., 'salesforce-prod')"
    )
    workload_id: str = Field(
        ...,
        description="Workload identifier (e.g., 'lead.route', 'first_touch_detect')"
    )
    request: Request = Field(..., description="Input request")
    response: Response = Field(..., description="Output response")

    # Additional context
    lead_id: Optional[str] = Field(None, description="Salesforce Lead ID")
    user_id: Optional[str] = Field(None, description="Salesforce User ID")
    policy_version: Optional[str] = Field(None, description="Policy version used")
    replay_id: Optional[str] = Field(None, description="CDC replay ID")

    class Config:
        """Pydantic config."""
        json_schema_extra = {
            "example": {
                "timestamp": 1698765432,
                "client_id": "salesforce-prod",
                "workload_id": "lead.route",
                "request": {
                    "model": "claude-3-5-sonnet-20241022",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Lead: Acme Corp; 500 employees; US; product=Analytics"
                        }
                    ],
                    "temperature": 0.0,
                    "max_tokens": 256
                },
                "response": {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"segment":"MM","region":"NA","owner":"005xx..."}'
                            },
                            "finish_reason": "stop",
                            "index": 0
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 50,
                        "completion_tokens": 30,
                        "total_tokens": 80
                    }
                },
                "lead_id": "00Q5e000001AbcD",
                "policy_version": "v1.2.0"
            }
        }


def validate_record(data: dict) -> FlywheelRecord:
    """
    Validate a flywheel record against the schema.

    Args:
        data: Dictionary to validate

    Returns:
        Validated FlywheelRecord

    Raises:
        ValidationError: If data doesn't match schema
    """
    return FlywheelRecord(**data)
