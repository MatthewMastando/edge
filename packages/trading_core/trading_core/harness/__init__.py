"""Agent harness interfaces: LLM provider contract, recorded provider, tool specs.

The job runner, workflow stages, tool registry and validators land in Stage 1B.
"""

from trading_core.harness.provider import (
    FORBIDDEN_TOOL_NAME_PATTERN,
    Message,
    MessageRole,
    ModelRequest,
    ModelResponse,
    Provider,
    ToolCall,
    ToolResult,
    ToolSpec,
    is_forbidden_tool_name,
)
from trading_core.harness.recorded import (
    RECORDED_PROVIDER_NAME,
    NoRecordingError,
    RecordedProvider,
    Recording,
    RecordingMatch,
)

__all__ = [
    "FORBIDDEN_TOOL_NAME_PATTERN",
    "RECORDED_PROVIDER_NAME",
    "Message",
    "MessageRole",
    "ModelRequest",
    "ModelResponse",
    "NoRecordingError",
    "Provider",
    "RecordedProvider",
    "Recording",
    "RecordingMatch",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "is_forbidden_tool_name",
]
