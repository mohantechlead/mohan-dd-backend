"""Ninja schemas for the AI chat API contract."""

from ninja import Schema
from typing import List, Optional


class ChatRequestSchema(Schema):
    message: str
    conversation_id: Optional[str] = None


class VisualizationSpecSchema(Schema):
    type: str  # bar | line | pie | scatter | none
    title: Optional[str] = None
    x_key: Optional[str] = None
    y_key: Optional[str] = None
    series: List[dict] = []


class ResponseMetadataSchema(Schema):
    intent: Optional[str] = None
    entities: List[str] = []
    filters: dict = {}
    date_range: dict = {}
    record_count: int = 0
    chart_type: str = "none"
    warnings: List[str] = []
    execution_ms: int = 0
    tool: Optional[str] = None


class ChatResponseSchema(Schema):
    message: str
    data: List[dict] = []
    visualization: VisualizationSpecSchema
    metadata: ResponseMetadataSchema
