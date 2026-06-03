"""WebSocket endpoint for streaming analysis events."""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from tradingagents.web_api.config import settings
from tradingagents.web_api.models.ws_messages import StartAnalysisMessage
from tradingagents.web_api.services.graph_runner import GraphRunner

router = APIRouter(tags=["ws"])


@router.websocket("/api/ws")
async def analysis_websocket(websocket: WebSocket):
    await websocket.accept()

    session_id = str(uuid.uuid4())
    await websocket.send_json({
        "type": "connection_established",
        "payload": {"session_id": session_id},
    })

    # ── Wait for start_analysis message ────────────────────────────────
    try:
        raw = await asyncio.wait_for(
            websocket.receive_json(), timeout=settings.ws_start_timeout
        )
    except asyncio.TimeoutError:
        await websocket.close(code=1008, reason="No start_analysis received")
        return
    except WebSocketDisconnect:
        return

    if raw.get("type") != "start_analysis":
        await websocket.close(code=1008, reason="Expected start_analysis")
        return

    try:
        msg = StartAnalysisMessage.model_validate(raw)
    except Exception as exc:
        await websocket.send_json({
            "type": "error",
            "payload": {"message": f"Invalid start_analysis payload: {exc}"},
        })
        await websocket.close(code=1008)
        return

    # ── Run graph and stream events ────────────────────────────────────
    runner = GraphRunner()
    event_queue = await runner.start(msg.payload)

    cancelled = False

    # Background receiver: listens for cancel messages without tight polling
    async def _receiver():
        nonlocal cancelled
        try:
            while True:
                raw = await websocket.receive_json()
                if raw.get("type") == "cancel_analysis":
                    cancelled = True
                    await runner.cancel()
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass

    recv_task = asyncio.create_task(_receiver())

    try:
        # ── Analysis streaming phase ──────────────────────────────────
        heartbeat_interval = 5
        last_heartbeat = time.monotonic()
        while not cancelled:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                if event is None:
                    break
                await websocket.send_json(event)
                last_heartbeat = time.monotonic()
            except asyncio.TimeoutError:
                now = time.monotonic()
                if now - last_heartbeat >= heartbeat_interval:
                    try:
                        await websocket.send_json({"type": "heartbeat", "payload": {}})
                        last_heartbeat = now
                    except Exception:
                        break

        # ── Post-analysis: keep connection alive for viewing results ──
        # Don't close immediately — client may still be viewing the report.
        # Close after 5 minutes of inactivity or when client disconnects.
        keepalive_end = time.monotonic() + 300
        while not cancelled and time.monotonic() < keepalive_end:
            await asyncio.sleep(15)
            try:
                await websocket.send_json({"type": "heartbeat", "payload": {}})
            except Exception:
                break

    except WebSocketDisconnect:
        await runner.cancel()
    except Exception as exc:
        try:
            await websocket.send_json({
                "type": "error",
                "payload": {"message": str(exc)},
            })
        except Exception:
            pass
    finally:
        recv_task.cancel()
        try:
            await recv_task
        except (asyncio.CancelledError, Exception):
            pass
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass
