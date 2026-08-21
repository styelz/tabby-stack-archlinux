"""Apply a model profile and hot-swap TabbyAPI without restarting the process."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from common.gpu_mode import (
    COMFY_DIR,
    COMFY_PYTHON,
    GPU_ALIASES,
    free_comfy,
    start_comfy_if_needed,
    write_mode,
)

from select_model import (
    CONFIG_PATH,
    apply_profile,
    ask_profile,
    available_profiles,
    last_profile,
    load_yaml,
    profile_aliases,
)

LOCK = Path(__file__).resolve().parent / "switch-model.lock"

LOAD_FIELDS = (
    "max_seq_len",
    "cache_size",
    "cache_mode",
    "chunk_size",
    "autosplit_reserve",
    "vision",
)


def api_base() -> str:
    _, config = load_yaml(CONFIG_PATH)
    network = config.get("network") or {}
    host = network.get("host") or "127.0.0.1"
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    port = network.get("port") or 5000
    return f"http://{host}:{port}"


def request_json(method: str, url: str, payload: dict | None = None, timeout: float = 30):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        if not body:
            return None
        return json.loads(body.decode())


def server_up(base: str) -> bool:
    try:
        request_json("GET", f"{base}/health", timeout=3)
        return True
    except (URLError, HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        return False


def current_model(base: str) -> str | None:
    try:
        card = request_json("GET", f"{base}/v1/model", timeout=10)
    except (URLError, HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    if isinstance(card, dict):
        return card.get("id")
    return None


def switch_sampler(base: str, preset: str | None):
    if not preset:
        return
    try:
        request_json(
            "POST",
            f"{base}/v1/sampling/override/switch",
            {"preset": preset},
            timeout=15,
        )
        print(f"  sampler: {preset}")
    except HTTPError as exc:
        print(f"  sampler switch failed: {exc.read().decode('utf-8', 'replace')}")
        raise SystemExit(1) from exc


def load_model(base: str, model_name: str, model_cfg: dict):
    payload = {"model_name": model_name}
    for key in LOAD_FIELDS:
        if key in model_cfg and model_cfg[key] is not None:
            payload[key] = model_cfg[key]

    print(f"Loading {model_name} (this can take a minute)...")
    req = Request(
        f"{base}/v1/model/load",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    finished = False
    error = None
    with urlopen(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                print(f"  {data}")
                continue
            if not isinstance(event, dict):
                continue
            if event.get("error"):
                error = event["error"]
                break
            status = event.get("status")
            module = event.get("module")
            modules = event.get("modules")
            model_type = event.get("model_type", "model")
            if status == "finished":
                print(f"  {model_type}: finished")
                finished = True
            elif status == "processing" and module and modules:
                print(f"  {model_type}: {module}/{modules}", end="\r")
    print()
    if error:
        raise SystemExit(f"Load failed: {error}")
    if not finished:
        raise SystemExit("Load stream ended before the model finished loading.")


def unload_tabby(base: str) -> None:
    loaded = current_model(base)
    if not loaded:
        print("TabbyAPI already unloaded")
        return
    print(f"Unloading {loaded}...")
    try:
        request_json("POST", f"{base}/v1/model/unload", timeout=180)
    except HTTPError as exc:
        if exc.code == 503:
            print("TabbyAPI already unloaded")
            return
        raise SystemExit(f"Unload failed: {exc.read().decode('utf-8', 'replace')}") from exc
    print("  LLM unloaded")


def switch_to_comfy(base: str) -> dict:
    started = time.time()
    if server_up(base):
        unload_tabby(base)
    else:
        print(f"TabbyAPI is not running at {base}; starting ComfyUI anyway.")
    write_mode("comfy")
    start_comfy_if_needed()
    elapsed = time.time() - started
    print("GPU mode: comfy")
    print("Remote clients: describe the image in chat or POST /v1/images/generations")
    print(f"Comfy ready ({elapsed:.0f}s)")
    return {"ready_s": elapsed, "mode": "comfy"}


def switch_to_llm(name: str, base: str | None = None, force: bool = False) -> dict:
    """Apply a profile, free Comfy, and load the model. Returns timing metadata."""
    profile = apply_profile(name)
    model_cfg = profile.get("model") or {}
    model_name = model_cfg.get("model_name")
    preset = (profile.get("sampling") or {}).get("override_preset")
    if not model_name:
        raise SystemExit(f"Profile {name} has no model_name")

    if base is None:
        base = api_base()
    if not server_up(base):
        print(f"TabbyAPI is not running at {base}.")
        starter = "start.bat" if os.name == "nt" else "./start.sh"
        print(f"Profile is saved. Start it with {starter} (press Enter to keep this model).")
        return {"ready_s": 0.0, "already": False, "loaded": None, "profile": name, "offline": True}

    started = time.time()
    free_comfy()
    write_mode("llm", profile=name)
    loaded = current_model(base)
    already = loaded == model_name and not force
    if already:
        switch_sampler(base, preset)
        print(f"Already loaded: {loaded}")
        print("GPU mode: llm")
        return {
            "ready_s": time.time() - started,
            "already": True,
            "loaded": loaded,
            "profile": name,
        }
    if loaded == model_name and force:
        unload_tabby(base)
    switch_sampler(base, preset)
    load_model(base, model_name, model_cfg)
    loaded = current_model(base)
    elapsed = time.time() - started
    print(f"Now loaded: {loaded} ({elapsed:.0f}s)")
    print("GPU mode: llm")
    return {"ready_s": elapsed, "already": False, "loaded": loaded, "profile": name}


def resolve_name(raw: str | None) -> str:
    names = available_profiles()
    if not raw:
        if sys.stdin.isatty():
            return ask_profile()
        return last_profile() if last_profile() in names else (names[0] if names else "qwen")
    token = raw.strip()
    lowered = token.lower()
    if lowered == "llm":
        return last_profile() if last_profile() in names else (names[0] if names else "qwen")
    if lowered in GPU_ALIASES:
        return GPU_ALIASES[lowered]
    aliases = profile_aliases()
    name = aliases.get(token) or aliases.get(lowered) or aliases.get(token.upper())
    if not name:
        raise SystemExit(f"Unknown model {raw!r}. Use: {', '.join(names)}, comfy")
    return name


def main():
    parser = argparse.ArgumentParser(
        description="Switch TabbyAPI models or hand the GPU to ComfyUI"
    )
    parser.add_argument("profile", nargs="?", help="qwen, qwen35, comfy, flux, llm, ...")
    parser.add_argument(
        "--no-load",
        action="store_true",
        help="Write the profile only; do not call /v1/model/load",
    )
    args = parser.parse_args()

    name = resolve_name(args.profile)
    if name == "comfy":
        if args.no_load:
            write_mode("comfy")
            print(
                f"GPU mode set to comfy. Start ComfyUI with {COMFY_PYTHON} {COMFY_DIR / 'main.py'}"
            )
            return 0
        switch_to_comfy(api_base())
        return 0

    if args.no_load:
        apply_profile(name)
        print("Profile written. Start or restart TabbyAPI to load it.")
        return 0

    switch_to_llm(name)
    print("Cursor can stay on gpt-4o.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        LOCK.unlink(missing_ok=True)
