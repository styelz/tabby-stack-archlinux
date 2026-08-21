"""Streamable HTTP MCP for Cursor: generate_image on this API host."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from common.auth import check_api_key
from common.mcp_images import dispatch, new_session_id, rpc_error, run_generate_tool

router = APIRouter()


def _session_response(payload: dict, *, session_id: str | None = None) -> JSONResponse:
    response = JSONResponse(payload)
    if session_id:
        response.headers["Mcp-Session-Id"] = session_id
    return response


@router.get("/mcp", dependencies=[Depends(check_api_key)])
@router.get("/v1/mcp", dependencies=[Depends(check_api_key)])
async def mcp_get() -> Response:
    """JSON-RPC is POST-only. GET SSE is optional; 405 stops Cursor reconnect loops."""
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp", dependencies=[Depends(check_api_key)])
@router.post("/v1/mcp", dependencies=[Depends(check_api_key)])
async def mcp_post(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(rpc_error(None, -32700, "Parse error"), status_code=400)

    incoming = request.headers.get("mcp-session-id")
    session_id = incoming or new_session_id()

    async def call_generate(arguments):
        return await run_generate_tool(arguments, request=request)

    if isinstance(body, list):
        results = []
        for item in body:
            reply = await dispatch(item, call_generate=call_generate)
            if reply is not None:
                results.append(reply)
        return _session_response(results, session_id=session_id)

    if not isinstance(body, dict):
        return JSONResponse(rpc_error(None, -32600, "Invalid Request"), status_code=400)

    reply = await dispatch(body, call_generate=call_generate)
    if reply is None:
        response = Response(status_code=202)
        response.headers["Mcp-Session-Id"] = session_id
        return response

    return _session_response(reply, session_id=session_id)
