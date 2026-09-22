from __future__ import annotations

from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]

    # Carried across turns so a follow-up like "what about this evening?" can
    # reuse the location/activity from the previous turn without re-asking.
    location_query: Optional[str]
    activity_category: Optional[str]
    time_window: Optional[str]
    resolved_location: Optional[dict]

    weather: Optional[dict]
    error_stage: Optional[str]   # "geocode" | "forecast" | None
    error_detail: Optional[str]

    matched_sop_id: Optional[str]
    match_rationale: Optional[str]

    final_answer: Optional[str]
