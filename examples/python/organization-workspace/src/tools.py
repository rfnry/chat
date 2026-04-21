from __future__ import annotations

from typing import Any

from src.settings import settings

_LEGAL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_case_law",
        "description": "Search internal case-law index for precedents matching a query.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "draft_clause",
        "description": "Draft a standard contract clause for a given topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "parties": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["topic"],
        },
    },
]

_MEDICAL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "drug_interaction_check",
        "description": "Check for interactions between a list of drug names.",
        "input_schema": {
            "type": "object",
            "properties": {
                "drugs": {"type": "array", "items": {"type": "string"}, "minItems": 2},
            },
            "required": ["drugs"],
        },
    },
    {
        "name": "symptom_triage",
        "description": "Return a triage tier and next-step guidance for a symptom set.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symptoms": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["symptoms"],
        },
    },
]


def tool_definitions() -> list[dict[str, Any]]:
    return {"legal": _LEGAL_TOOLS, "medical": _MEDICAL_TOOLS}[settings.WORKSPACE]


_CASE_LAW = [
    {"id": "TX-2019-0441", "summary": "Contract interpretation — ambiguous arbitration clause."},
    {"id": "NY-2021-0918", "summary": "Non-compete enforceability under expanded narrow-tailoring test."},
    {"id": "CA-2023-0122", "summary": "Data-processing addendum scope vs subprocessor liability."},
]

_CLAUSE_TEMPLATES = {
    "confidentiality": (
        "Each Party shall treat as confidential all non-public information disclosed by "
        "the other Party, and shall not disclose such information except as required by law."
    ),
    "indemnification": (
        "Each Party (the Indemnifying Party) shall indemnify, defend, and hold harmless the "
        "other Party from and against any third-party claims arising out of breaches of this Agreement."
    ),
    "termination": (
        "Either Party may terminate this Agreement upon thirty (30) days prior written notice "
        "to the other Party. Obligations accrued before termination survive."
    ),
}

_INTERACTIONS = {
    frozenset({"warfarin", "ibuprofen"}): {
        "severity": "major",
        "note": "NSAID potentiates anticoagulant effect; elevated bleeding risk.",
    },
    frozenset({"lisinopril", "spironolactone"}): {
        "severity": "moderate",
        "note": "Both retain potassium; monitor serum levels.",
    },
    frozenset({"metformin", "acetaminophen"}): {
        "severity": "none",
        "note": "No clinically significant interaction.",
    },
}

_TRIAGE_RULES = [
    (frozenset({"chest pain", "shortness of breath"}), {"tier": "emergency", "next": "Seek emergency care immediately."}),
    (frozenset({"headache", "fever"}), {"tier": "urgent", "next": "Schedule same-day primary-care visit."}),
    (frozenset({"cough"}), {"tier": "routine", "next": "Monitor; visit if symptoms persist beyond 10 days."}),
]


async def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "search_case_law":
        query = str(arguments.get("query", "")).lower()
        hits = [c for c in _CASE_LAW if query in c["summary"].lower()]
        return {"query": query, "results": hits or _CASE_LAW[:2]}

    if name == "draft_clause":
        topic = str(arguments.get("topic", "")).lower()
        parties = arguments.get("parties") or ["Party A", "Party B"]
        body = _CLAUSE_TEMPLATES.get(topic, f"[No template for {topic!r}; returning boilerplate.]")
        return {"topic": topic, "parties": parties, "body": body}

    if name == "drug_interaction_check":
        drugs = [str(d).lower() for d in (arguments.get("drugs") or [])]
        key = frozenset(drugs)
        match = _INTERACTIONS.get(key)
        if match is not None:
            return {"drugs": drugs, **match}
        return {"drugs": drugs, "severity": "unknown", "note": "No cached record; refer to primary source."}

    if name == "symptom_triage":
        symptoms = [str(s).lower() for s in (arguments.get("symptoms") or [])]
        sset = frozenset(symptoms)
        for required, verdict in _TRIAGE_RULES:
            if required.issubset(sset):
                return {"symptoms": symptoms, **verdict}
        return {"symptoms": symptoms, "tier": "routine", "next": "Observe; consult if worsening."}

    return {"success": False, "error": "unknown_tool", "tool": name}
