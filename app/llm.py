"""LLM client and the structured-output schemas the graph nodes use.

Model choice lives entirely in this one place (env-driven) so swapping
providers/models never touches graph.py, weather.py, or sops.yaml.
"""
from __future__ import annotations

import os
from typing import Optional

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field


def get_llm(temperature: float = 0.0) -> ChatGroq:
    model_name = os.environ.get("MODEL_NAME", "openai/gpt-oss-120b")
    return ChatGroq(model=model_name, temperature=temperature)


class ExtractedQuery(BaseModel):
    """What the user is actually asking, resolved against conversation history."""

    location: Optional[str] = Field(
        None,
        description=(
            "The place to check weather for, as a plain city/place name suitable for "
            "a geocoding lookup (e.g. 'Bhopal', 'Chennai'). If the current message does "
            "not name a location but a location was already resolved earlier in this "
            "conversation and nothing suggests the user means somewhere else, reuse that "
            "earlier location. Null only if no location can be determined from the whole "
            "conversation so far."
        ),
    )
    activity_category: str = Field(
        description=(
            "A short free-text description of the activity/category the user cares about, "
            "e.g. 'cycling commute', 'picnic', 'walking the dog', 'taking a toddler to the park'. "
            "If unclear, reuse the prior turn's category when this message is a natural follow-up."
        )
    )
    time_window: str = Field(
        description=(
            "One of: 'now', 'today', 'this_evening', 'tonight', 'tomorrow', 'tomorrow_morning', "
            "or another short free-text label if the user is clearly asking about a different window."
        )
    )


class SOPMatch(BaseModel):
    """The single SOP the matcher picked, or none."""

    sop_id: Optional[str] = Field(
        None,
        description=(
            "The exact id of the single SOP that applies (e.g. 'SOP-007'), copied exactly "
            "from the catalog provided. Null if no SOP in the catalog genuinely applies -- "
            "do not invent an id and do not force a weak match."
        ),
    )
    rationale: str = Field(
        description="One or two sentences on why this SOP (or no SOP) applies, citing the actual weather numbers used."
    )
