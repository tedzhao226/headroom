from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    gates = request.app.state.gates
    return {
        "status": "ok",
        "endpoints": {
            name: {
                "total_tps": gate.total_capacity,
                "current_usage_tps": gate.current_usage_tps,
                "reserved_tokens": gate.reserved_tokens,
                "available": gate.available,
            }
            for name, gate in gates.items()
        },
    }
