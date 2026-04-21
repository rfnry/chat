from __future__ import annotations

import logging
from typing import Any

from rfnry_chat_server import (
    ChatServer,
    HandlerContext,
    HandlerSend,
    MessageEvent,
    PostgresChatStore,
)

from src.auth import authenticate

logger = logging.getLogger("stock-tool")

_STOCK = {
    "FBA-MERV11-16x25x1": 4820,
    "FBA-MERV13-20x25x1": 1340,
    "FBA-MERV8-16x20x1": 8600,
}

_SHIPMENTS = {
    "SHP-1001": {"status": "in_transit", "carrier": "UPS", "eta": "2026-04-23"},
    "SHP-1002": {"status": "delivered", "carrier": "FedEx", "delivered_at": "2026-04-19"},
    "SHP-1003": {"status": "label_created", "carrier": "USPS"},
}


def build(store: PostgresChatStore) -> ChatServer:
    chat_server = ChatServer(store=store, authenticate=authenticate)

    @chat_server.on_message()
    async def log_message(ctx: HandlerContext, _send: HandlerSend) -> None:
        assert isinstance(ctx.event, MessageEvent)
        text = next(
            (getattr(p, "text", "") for p in ctx.event.content if getattr(p, "type", None) == "text"),
            "",
        )
        logger.info("msg thread=%s author=%s text=%s", ctx.thread.id, ctx.event.author.id, text)

    @chat_server.on_tool_call("check_stock")
    async def check_stock(ctx: HandlerContext, send: HandlerSend):
        sku = _arg(ctx.event.tool.arguments, "sku", required=True)
        quantity = _STOCK.get(sku)
        if quantity is None:
            yield send.tool_result(
                ctx.event.tool.id,
                error={"code": "sku_not_found", "message": f"unknown sku: {sku}"},
            )
            return
        yield send.tool_result(ctx.event.tool.id, result={"sku": sku, "available": quantity})

    @chat_server.on_tool_call("shipping_status")
    async def shipping_status(ctx: HandlerContext, send: HandlerSend):
        shipment_id = _arg(ctx.event.tool.arguments, "shipment_id", required=True)
        row = _SHIPMENTS.get(shipment_id)
        if row is None:
            yield send.tool_result(
                ctx.event.tool.id,
                error={"code": "shipment_not_found", "message": f"unknown shipment: {shipment_id}"},
            )
            return
        yield send.tool_result(ctx.event.tool.id, result={"shipment_id": shipment_id, **row})

    return chat_server


def _arg(arguments: Any, key: str, *, required: bool = False) -> Any:
    if not isinstance(arguments, dict):
        if required:
            raise ValueError(f"missing argument: {key}")
        return None
    value = arguments.get(key)
    if value is None and required:
        raise ValueError(f"missing argument: {key}")
    return value
