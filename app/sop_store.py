"""Loads SOPs from sops.yaml.

Deliberately reads the file fresh on every call instead of caching at import
time. That is what lets the policy team edit sops.yaml (add, remove, reword an
SOP) and have it take effect on the very next chat turn, with the graph code
never touched and the process never restarted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

DEFAULT_SOPS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sops.yaml")


@dataclass(frozen=True)
class SOP:
    id: str
    category: str
    title: str
    severity: str
    overrides: bool
    condition: str
    guidance: str


SEVERITY_RANK = {"low": 0, "moderate": 1, "high": 2, "critical": 3}


def load_sops(path: str | None = None) -> list[SOP]:
    sops_path = path or os.environ.get("SOPS_PATH") or DEFAULT_SOPS_PATH
    with open(sops_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    sops = []
    for entry in raw.get("sops", []):
        sops.append(
            SOP(
                id=entry["id"],
                category=entry["category"],
                title=entry["title"],
                severity=entry["severity"],
                overrides=bool(entry.get("overrides", False)),
                condition=entry["condition"].strip(),
                guidance=entry["guidance"].strip(),
            )
        )
    return sops


def get_sop_by_id(sop_id: str, path: str | None = None) -> SOP | None:
    for sop in load_sops(path):
        if sop.id == sop_id:
            return sop
    return None


def catalog_for_matching(path: str | None = None) -> list[dict]:
    """Condition-only view handed to the matching LLM (no guidance text --
    the matcher's job is to pick a policy, not to see the advice yet)."""
    return [
        {
            "id": sop.id,
            "category": sop.category,
            "severity": sop.severity,
            "overrides": sop.overrides,
            "condition": sop.condition,
        }
        for sop in load_sops(path)
    ]
