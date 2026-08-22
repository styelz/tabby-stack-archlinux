"""Server-owned mixed coding+images controller.

Phases:

- QUEUE — start Comfy, or append dests the current job is still missing
- WAIT — job queued/running; invent Shell sleep/ls only (no URLs)
- DOWNLOAD — job done; curl only timestamped files that exist on this host
- CODE — return None so the 9B writes HTML/CSS/JS

The coding model never submits the batch. A tool-role wait turn must still
QUEUE dests the in-flight job does not cover; otherwise a logo-only MCP dump
blocks planets for the rest of the chat.
"""

from __future__ import annotations

QUEUE = "queue"
WAIT = "wait"
DOWNLOAD = "download"
CODE = "code"
STOP = "stop"
REFUSE = "refuse"


def missing_planned_items(job, planned: list[dict]) -> list[dict]:
    """Planned PNG dests this job does not already have."""
    from common.image_paths import job_output_paths, safe_rel_png_path

    have = {safe_rel_png_path(path) for path in job_output_paths(job)}
    have.discard("")
    gap: list[dict] = []
    for row in planned or []:
        if not isinstance(row, dict):
            continue
        dest = safe_rel_png_path(str(row.get("output_path") or ""))
        if not dest or dest in have:
            continue
        gap.append(row)
        have.add(dest)
    return gap


def phase_for(
    *,
    mixed: bool,
    job,
    covers: bool,
    faking: bool,
    client_saved: bool,
    download_stopped: bool,
    files_missing: bool,
) -> str:
    """Which mixed-image phase this turn is in. I/O stays in phrase_switch."""
    if not mixed:
        return CODE
    if faking:
        return REFUSE
    status = str(getattr(job, "status", "") or "") if job is not None else ""
    if job is not None and status in ("queued", "running"):
        return WAIT if covers else QUEUE
    if job is not None and status in ("done", "error"):
        if not covers:
            return QUEUE
        if client_saved:
            return CODE
        if download_stopped and not files_missing:
            return STOP
        urls = getattr(job, "urls", None)
        if urls or status == "done":
            return DOWNLOAD
    if job is None:
        return QUEUE
    return CODE
