"""HTTP routes for the management UI at /v1/ui."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from sse_starlette import EventSourceResponse

from ui.assets import STATIC_DIR, file_response
from ui.auth import (
    COOKIE_NAME,
    authenticate_user,
    clear_session_cookie,
    client_ip,
    create_session,
    destroy_session,
    login_allowed,
    record_login_attempt,
    is_admin_username,
    require_ui_admin,
    require_ui_user,
    set_session_cookie,
    stack_username,
    validate_session,
)
from ui.manager import (
    gallery_listing,
    install_log_sink,
    journalctl_history,
    start_stack_restart,
    start_stack_update,
    stack_status,
    stream_journal_lines,
)

# Served under /v1 so SSH forwarders that only proxy /openai/v1 and
# /lmstudio/v1 keep the console on the same path prefix as the API.
UI_PREFIX = "/v1/ui"
router = APIRouter(prefix=UI_PREFIX, tags=["ui"])
legacy_router = APIRouter(tags=["ui-legacy"])


def _session_token(request: Request) -> str:
    return request.cookies.get(COOKIE_NAME) or ""


@legacy_router.get("/ui", include_in_schema=False)
@legacy_router.get("/ui/", include_in_schema=False)
@legacy_router.get("/ui/{rest:path}", include_in_schema=False)
async def ui_legacy_redirect(rest: str = ""):
    """Local /ui bookmarks → /v1/ui. Relative so /openai/ui keeps its prefix."""
    target = f"../v1/ui/{rest}" if rest else "../v1/ui/"
    return RedirectResponse(target, status_code=308)


@router.get("/login", include_in_schema=False)
async def ui_login_page(request: Request):
    if validate_session(_session_token(request)):
        return RedirectResponse("./", status_code=303)
    return file_response("login.html")


@router.get("", include_in_schema=False)
async def ui_index_noslash(request: Request):
    # Relative "ui/" from .../v1/ui → .../v1/ui/ (keeps /openai or /lmstudio).
    return RedirectResponse("ui/", status_code=308)


@router.get("/", include_in_schema=False)
async def ui_index(request: Request):
    if not validate_session(_session_token(request)):
        return RedirectResponse("./login", status_code=303)
    return file_response("index.html")


@router.get("/assets/{name}", include_in_schema=False)
async def ui_asset(name: str):
    return file_response(name)


@router.post("/auth/login", include_in_schema=False)
async def ui_login(request: Request):
    ip = client_ip(request)
    if not login_allowed(ip):
        raise HTTPException(429, "Too many login attempts. Wait a minute and try again.")
    try:
        body = await request.json()
    except Exception:
        body = {}
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    record_login_attempt(ip)
    if not authenticate_user(username, password):
        raise HTTPException(401, "Invalid username or password.")
    try:
        from ui.users import record_login

        record_login(username)
    except Exception:
        pass
    token = create_session(username)
    response = Response(
        content=json.dumps({"ok": True, "username": username, "redirect": "./"}),
        media_type="application/json",
    )
    set_session_cookie(response, token, request)
    return response


@router.post("/auth/logout", include_in_schema=False)
async def ui_logout(request: Request):
    destroy_session(_session_token(request))
    response = Response(content=json.dumps({"ok": True}), media_type="application/json")
    clear_session_cookie(response)
    return response


@router.get("/auth/check", include_in_schema=False)
async def ui_auth_check(request: Request):
    username = validate_session(_session_token(request))
    if not username:
        raise HTTPException(401, "Not authenticated")
    return {
        "ok": True,
        "username": username,
        "stack_user": stack_username(),
        "is_admin": is_admin_username(username),
    }


@router.get("/status", include_in_schema=False)
async def ui_status(request: Request, _user: str = Depends(require_ui_user)):
    from ui.metrics import ensure_metrics_sampler

    ensure_metrics_sampler()
    return await stack_status(request)


@router.get("/metrics", include_in_schema=False)
async def ui_metrics(
    hours: float | None = None,
    days: float | None = None,
    max_points: int = 720,
    _user: str = Depends(require_ui_user),
):
    from ui.metrics import ensure_metrics_sampler, metrics_history

    ensure_metrics_sampler()
    if days is not None and hours is not None:
        # Prefer the more specific unit the client sent last in query order:
        # if both are present, days wins (explicit multi-day view).
        hours = None
    try:
        return metrics_history(hours=hours, days=days, max_points=max_points)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/logs/history", include_in_schema=False)
async def ui_log_history(lines: int = 300, _user: str = Depends(require_ui_user)):
    install_log_sink()
    return {"lines": journalctl_history(lines)}


@router.get("/logs/stream", include_in_schema=False)
async def ui_log_stream(_user: str = Depends(require_ui_user)):
    install_log_sink()

    async def events():
        async for line in stream_journal_lines():
            yield {"event": "log", "data": json.dumps({"line": line})}

    return EventSourceResponse(events(), ping=15)


@router.post("/restart", include_in_schema=False)
async def ui_restart(_admin: str = Depends(require_ui_admin)):
    return start_stack_restart()


@router.post("/update", include_in_schema=False)
async def ui_update(request: Request, _admin: str = Depends(require_ui_admin)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await asyncio.to_thread(start_stack_update, full=bool(body.get("full")))


@router.post("/gpu", include_in_schema=False)
async def ui_gpu(request: Request, _user: str = Depends(require_ui_user)):
    from common.gpu_mode import GPU_ALIASES, comfy_up
    from endpoints.core.image_jobs import ensure_comfy, loaded_tabby_name, reload_last_llm
    from select_model import available_profiles, last_profile, profile_aliases

    try:
        body = await request.json()
    except Exception:
        body = {}
    token = str(body.get("mode") or "").strip().lower()
    if not token:
        raise HTTPException(400, "mode is required")
    if token in GPU_ALIASES:
        try:
            await ensure_comfy()
        except (SystemExit, RuntimeError) as exc:
            raise HTTPException(500, str(exc)) from exc
        return {
            "ok": True,
            "mode": "comfy",
            "tabby_model": None,
            "comfy_up": comfy_up(),
            "message": "GPU handed to ComfyUI.",
        }
    names = available_profiles()
    aliases = profile_aliases()
    if token == "llm":
        name = last_profile() if last_profile() in names else (names[0] if names else None)
    else:
        name = aliases.get(token) or aliases.get(str(body.get("mode") or "").strip())
    if not name:
        raise HTTPException(400, f"Unknown mode {token!r}")
    try:
        await reload_last_llm(name)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "mode": "llm",
        "tabby_model": loaded_tabby_name(),
        "comfy_up": comfy_up(),
        "message": f"GPU handed to TabbyAPI ({name})",
    }


@router.post("/chat", include_in_schema=False)
async def ui_chat(request: Request, _user: str = Depends(require_ui_user)):
    from ui.chat import run_console_chat

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "JSON body required") from exc
    return await run_console_chat(request, body, username=_user)




@router.get("/users", include_in_schema=False)
async def ui_users_list(_admin: str = Depends(require_ui_admin)):
    from ui.users import list_accounts

    return {"users": list_accounts()}


@router.post("/users", include_in_schema=False)
async def ui_users_create(request: Request, _admin: str = Depends(require_ui_admin)):
    from ui.users import create_user

    try:
        body = await request.json()
    except Exception:
        body = {}
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    try:
        user = create_user(username, password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "user": user}


@router.post("/users/{name}/password", include_in_schema=False)
async def ui_users_password(name: str, request: Request, _admin: str = Depends(require_ui_admin)):
    from ui.users import set_password

    try:
        body = await request.json()
    except Exception:
        body = {}
    password = str(body.get("password") or "")
    try:
        set_password(name, password)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@router.delete("/users/{name}", include_in_schema=False)
async def ui_users_delete(name: str, _admin: str = Depends(require_ui_admin)):
    from ui.auth import destroy_sessions_for_user
    from ui.chats import delete_store
    from ui.users import delete_user

    try:
        delete_user(name)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    destroy_sessions_for_user(name)
    delete_store(name)
    return {"ok": True}


@router.get("/chats", include_in_schema=False)
async def ui_chats_get(_user: str = Depends(require_ui_user)):
    from ui.chats import load_store

    return load_store(_user)


@router.put("/chats", include_in_schema=False)
async def ui_chats_put(request: Request, _user: str = Depends(require_ui_user)):
    from ui.chats import save_store

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "JSON body required") from exc
    return save_store(_user, body)


def _workspace_chat_id(chat_id: str) -> str:
    from ui.workspace import safe_name

    raw = str(chat_id or "").strip()
    if not raw:
        raise HTTPException(400, "Invalid chat id")
    return safe_name(raw)


@router.get("/workspace/{chat_id}", include_in_schema=False)
async def ui_workspace_list(chat_id: str, _user: str = Depends(require_ui_user)):
    from ui.workspace import listing, site_entry

    cid = _workspace_chat_id(chat_id)
    return {**listing(_user, cid), "entry": site_entry(_user, cid)}


@router.get("/workspace/{chat_id}/file", include_in_schema=False)
async def ui_workspace_file(
    chat_id: str, path: str = "", _user: str = Depends(require_ui_user)
):
    from ui.workspace import guess_media_type, resolve_file

    if not path:
        raise HTTPException(400, "path is required")
    try:
        file_path = resolve_file(_user, _workspace_chat_id(chat_id), path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "File not found.") from exc
    return FileResponse(
        file_path, media_type=guess_media_type(file_path), filename=file_path.name
    )


@router.put("/workspace/{chat_id}/file", include_in_schema=False)
async def ui_workspace_write_file(
    chat_id: str, request: Request, path: str = "", _user: str = Depends(require_ui_user)
):
    from ui.workspace import is_text_path, listing, site_entry, write_text

    if not path:
        raise HTTPException(400, "path is required")
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "JSON body required") from exc
    contents = body.get("contents")
    if not isinstance(contents, str):
        raise HTTPException(400, "contents must be a string")
    cid = _workspace_chat_id(chat_id)
    if not is_text_path(path):
        raise HTTPException(400, "Only text files can be edited here.")
    try:
        written = write_text(_user, cid, path, contents)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "path": written, **listing(_user, cid), "entry": site_entry(_user, cid)}


@router.delete("/workspace/{chat_id}/file", include_in_schema=False)
async def ui_workspace_delete_file(
    chat_id: str, path: str = "", _user: str = Depends(require_ui_user)
):
    from ui.workspace import delete_file, listing, site_entry

    if not path:
        raise HTTPException(400, "path is required")
    cid = _workspace_chat_id(chat_id)
    try:
        delete_file(_user, cid, path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "File not found.") from exc
    return {"ok": True, **listing(_user, cid), "entry": site_entry(_user, cid)}


@router.post("/workspace/{chat_id}/preview", include_in_schema=False)
async def ui_workspace_preview(
    chat_id: str, request: Request, _user: str = Depends(require_ui_user)
):
    """Hand back a token URL the browser can open as a plain website."""
    from ui.preview import mint
    from ui.workspace import site_entry

    cid = _workspace_chat_id(chat_id)
    try:
        body = await request.json()
    except Exception:
        body = {}
    wanted = str(body.get("path") or "")
    entry = site_entry(_user, cid, wanted)
    if not entry:
        raise HTTPException(404, "No page to open yet. Ask for an HTML file first.")
    token = mint(_user, cid)
    base = f"code/{quote(_user, safe='')}/{quote(cid, safe='')}/{token}/"
    return {"ok": True, "base": base, "path": entry, "url": base + quote(entry)}


@router.get("/workspace/{chat_id}/zip", include_in_schema=False)
async def ui_workspace_zip(chat_id: str, _user: str = Depends(require_ui_user)):
    from ui.workspace import zip_bytes

    cid = _workspace_chat_id(chat_id)
    data = zip_bytes(_user, cid)
    filename = f"{cid}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/workspace/{chat_id}", include_in_schema=False)
async def ui_workspace_clear(chat_id: str, _user: str = Depends(require_ui_user)):
    from ui.preview import drop_chat
    from ui.workspace import delete_workspace

    cid = _workspace_chat_id(chat_id)
    delete_workspace(_user, cid)
    drop_chat(_user, cid)
    return {"ok": True, "files": [], "bytes": 0, "count": 0}


@router.get("/code/{username}/{chat_id}/{token}/{path:path}", include_in_schema=False)
async def ui_code_preview(
    request: Request, username: str, chat_id: str, token: str, path: str = ""
):
    """Serve a Code-mode project as a site. The path token is the credential.

    Deliberately not cookie-authenticated: the sandbox CSP gives this document
    an opaque origin, and such a document does not send SameSite=Lax cookies
    with its own subresource requests.
    """
    from ui.preview import SANDBOX_CSP, resolve
    from ui.workspace import guess_media_type, resolve_file, safe_name, site_entry

    owner = resolve(token)
    if not owner or owner[0] != username or owner[1] != safe_name(chat_id):
        raise HTTPException(404, "This preview link expired. Open the site again.")
    user, cid = owner
    rel = path or ""
    # Starlette has already redirected a missing trailing slash, so an empty
    # path here means the directory form.
    if not rel or rel.endswith("/"):
        rel = f"{rel}index.html"
    try:
        file_path = resolve_file(user, cid, rel)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        # Root of a project that keeps its page elsewhere, e.g. site/index.html.
        entry = site_entry(user, cid) if rel == "index.html" else ""
        if not entry:
            raise HTTPException(404, "File not found.") from exc
        return RedirectResponse(f"{request.url.path}{quote(entry)}", status_code=307)
    return FileResponse(
        file_path,
        media_type=guess_media_type(file_path),
        headers={
            "Content-Security-Policy": SANDBOX_CSP,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        },
    )


@router.get("/gallery/list", include_in_schema=False)
async def ui_gallery_list(
    page: int = 1,
    per_page: int = 24,
    _user: str = Depends(require_ui_user),
):
    return gallery_listing(
        page,
        per_page,
        username=_user,
        is_admin=is_admin_username(_user),
    )


@router.post("/gallery/delete", include_in_schema=False)
async def ui_gallery_delete(request: Request, _user: str = Depends(require_ui_user)):
    from common.gallery_owners import can_access, owner_of
    from common.gpu_mode import delete_generated_images, list_generated_files

    try:
        body = await request.json()
    except Exception:
        body = {}
    wipe_all = bool(body.get("all"))
    names = body.get("names") if isinstance(body.get("names"), list) else []
    admin = is_admin_username(_user)
    if wipe_all:
        if admin:
            removed = delete_generated_images([], delete_all=True)
        else:
            own = [path.name for path in list_generated_files() if owner_of(path.name) == _user]
            removed = delete_generated_images(own, delete_all=False)
        return {"deleted": removed, "count": len(removed)}
    if not names:
        raise HTTPException(400, "Provide names or all=true")
    allowed = []
    for raw in names:
        name = str(raw)
        if can_access(name, _user, admin):
            allowed.append(name)
    if not allowed:
        raise HTTPException(404, "Image not found.")
    removed = delete_generated_images(allowed, delete_all=False)
    return {"deleted": removed, "count": len(removed)}


@router.get("/gallery/file/{name}", include_in_schema=False)
async def ui_gallery_file(name: str, _user: str = Depends(require_ui_user)):
    from common.gallery_owners import can_access
    from common.gpu_mode import generated_image_path

    path = generated_image_path(name)
    if not path or not can_access(name, _user, is_admin_username(_user)):
        raise HTTPException(404, "Image not found.")
    return FileResponse(path, media_type="image/png", filename=name)


@router.get("/gallery/thumb/{name}", include_in_schema=False)
async def ui_gallery_thumb(name: str, _user: str = Depends(require_ui_user)):
    from common.gallery_owners import can_access
    from common.gpu_mode import ensure_gallery_thumb, generated_image_path, generated_thumb_path

    if not can_access(name, _user, is_admin_username(_user)):
        raise HTTPException(404, "Image not found.")
    thumb = generated_thumb_path(name)
    if thumb:
        return FileResponse(thumb, media_type="image/jpeg", filename=thumb.name)
    png_name = name[: -len(".jpg")] + ".png" if name.endswith(".jpg") else name
    original = generated_image_path(png_name)
    if original:
        built = ensure_gallery_thumb(original)
        if built:
            return FileResponse(built, media_type="image/jpeg", filename=built.name)
        return FileResponse(original, media_type="image/png", filename=original.name)
    raise HTTPException(404, "Image not found.")
