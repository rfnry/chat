from __future__ import annotations

from typing import Any

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "order_lookup",
        "description": "Look up an order by its id and return status + line items.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Route the conversation to a human agent with a short reason.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}, "priority": {"type": "string"}},
            "required": ["reason"],
        },
    },
]


_ORDERS = {
    "ORD-1001": {
        "status": "shipped",
        "total_cents": 4999,
        "lines": [{"sku": "FBA-MERV11-16x25x1", "qty": 4}],
        "shipment_id": "SHP-1001",
    },
    "ORD-1002": {
        "status": "delivered",
        "total_cents": 8400,
        "lines": [{"sku": "FBA-MERV13-20x25x1", "qty": 2}],
        "shipment_id": "SHP-1002",
    },
}


async def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "order_lookup":
        order_id = arguments.get("order_id", "")
        row = _ORDERS.get(order_id)
        if row is None:
            return {"success": False, "error": "order_not_found", "order_id": order_id}
        return {"success": True, "order_id": order_id, **row}

    if name == "escalate_to_human":
        return {
            "success": True,
            "routed_to": "tier2",
            "reason": arguments.get("reason", ""),
            "priority": arguments.get("priority", "normal"),
        }

    return {"success": False, "error": "unknown_tool", "tool": name}
