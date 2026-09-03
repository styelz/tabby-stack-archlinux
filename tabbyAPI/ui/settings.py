"""Admin read/write for config.yml and tabby.env."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Literal, Optional, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined
from ruamel.yaml import YAML

from common.config_models import BaseConfigModel, TabbyConfigModel

TABBY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = TABBY_ROOT / "config.yml"
ENV_PATH = TABBY_ROOT / "deploy" / "arch" / "tabby.env"
ENV_EXAMPLE_PATH = TABBY_ROOT / "deploy" / "arch" / "tabby.env.example"

SECRET_KEYS = frozenset(
    {
        "seqlog_api_key",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
    }
)

SYSTEM_FIELDS = (
    {
        "name": "COMFYUI_DIR",
        "label": "ComfyUI directory",
        "description": "ComfyUI tree on this host.",
    },
    {
        "name": "COMFYUI_URL",
        "label": "ComfyUI URL",
        "description": "ComfyUI HTTP API.",
    },
    {
        "name": "TABBY_PUBLIC_BASE",
        "label": "Public base URL",
        "description": "Base URL written into image markdown for remote clients. Blank uses the Host the client already called.",
    },
    {
        "name": "TABBY_SSH_REMOTE",
        "label": "SSH remote",
        "description": "Reverse tunnel. Empty disables ssh. Example: user@host.example",
    },
    {
        "name": "TABBY_SSH_FORWARD",
        "label": "SSH forward",
        "description": "Remote listen to local TabbyAPI.",
    },
    {
        "name": "TABBY_SSH_KEY",
        "label": "SSH key path",
        "description": "Private key for TABBY_SSH_REMOTE.",
    },
    {
        "name": "TABBY_LOG_CONSOLE_WIDTH",
        "label": "Log console width",
        "description": "Console wrap width.",
        "kind": "int",
    },
    {
        "name": "TABBY_LOG_LEVEL",
        "label": "Log level",
        "description": "DEBUG, INFO, WARNING, or ERROR.",
        "kind": "select",
        "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    {
        "name": "HF_TOKEN",
        "label": "Hugging Face token",
        "description": "Used by the installer and fetch_models.py for gated repos.",
        "secret": True,
    },
    {
        "name": "HUGGING_FACE_HUB_TOKEN",
        "label": "Hugging Face hub token",
        "description": "Alternate Hugging Face token name.",
        "secret": True,
    },
)

_ENV_ASSIGN = re.compile(r"^(\s*)(?:#\s*)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class SettingsError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump())
    return str(value)


def _unwrap_optional(ann: Any) -> tuple[Any, bool]:
    origin = get_origin(ann)
    if origin is Union:
        args = [item for item in get_args(ann) if item is not type(None)]
        if len(args) == 1:
            return args[0], True
        return ann, True
    return ann, False


def _kind_from_annotation(ann: Any) -> dict[str, Any]:
    ann, optional = _unwrap_optional(ann)
    origin = get_origin(ann)
    args = get_args(ann)
    if ann is bool:
        return {"kind": "bool", "optional": optional}
    if origin is Literal:
        return {"kind": "select", "choices": [str(item) for item in args], "optional": optional}
    if origin is list:
        inner = args[0] if args else str
        inner_origin = get_origin(inner)
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return {"kind": "json", "optional": optional}
        if inner in (int, float) or inner_origin is Union:
            return {"kind": "list_number", "optional": optional}
        return {"kind": "list_text", "optional": optional}
    if origin is dict or ann is dict:
        return {"kind": "json", "optional": optional}
    if origin is Union:
        literals: list[str] = []
        for item in args:
            if get_origin(item) is Literal:
                literals.extend(str(part) for part in get_args(item))
        out: dict[str, Any] = {"kind": "text", "optional": True}
        if literals:
            out["choices"] = literals
        return out
    if ann is int:
        return {"kind": "int", "optional": optional}
    if ann is float:
        return {"kind": "float", "optional": optional}
    return {"kind": "text", "optional": optional}


def _field_default(info: Any) -> Any:
    if info.default is not PydanticUndefined:
        return _jsonable(info.default)
    factory = getattr(info, "default_factory", None)
    if factory is not None and factory is not PydanticUndefined:
        try:
            return _jsonable(factory())
        except Exception:
            return None
    return None


def _section_included(model_cls: type) -> bool:
    try:
        meta = getattr(model_cls(), "_metadata", None)
    except Exception:
        return True
    return bool(meta is None or getattr(meta, "include_in_config", True))


def tabby_schema() -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for name, info in TabbyConfigModel.model_fields.items():
        model_cls, _optional = _unwrap_optional(info.annotation)
        if not isinstance(model_cls, type) or not issubclass(model_cls, BaseConfigModel):
            continue
        if not _section_included(model_cls):
            continue
        fields = []
        for field_name, field_info in model_cls.model_fields.items():
            spec = _kind_from_annotation(field_info.annotation)
            spec.update(
                {
                    "name": field_name,
                    "label": field_name.replace("_", " "),
                    "description": (field_info.description or "").strip(),
                    "default": _field_default(field_info),
                    "secret": field_name in SECRET_KEYS,
                }
            )
            if spec["kind"] == "bool" and spec.get("optional") and spec.get("default") is None:
                spec["kind"] = "select"
                spec["choices"] = ["true", "false"]
                spec["blank"] = "auto"
            fields.append(spec)
        description = (model_cls.__doc__ or "").strip().split("\n", 1)[0]
        if name == "model":
            description = (
                f"{description} A profile switch overwrites load keys "
                "(context, cache, tool_format, reasoning)."
            ).strip()
        sections.append(
            {
                "name": name,
                "label": name.replace("_", " "),
                "description": description,
                "fields": fields,
            }
        )
    return sections


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    return yaml


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _load_config_doc() -> tuple[YAML, Any]:
    yaml = _yaml()
    if not CONFIG_PATH.is_file():
        return yaml, {}
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        data = yaml.load(handle)
    return yaml, data if data is not None else {}


def _file_tabby_values() -> dict[str, dict[str, Any]]:
    _, data = _load_config_doc()
    plain = _plain(data) if isinstance(data, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for section in tabby_schema():
        raw = plain.get(section["name"])
        row = raw if isinstance(raw, dict) else {}
        out[section["name"]] = {
            field["name"]: _jsonable(row[field["name"]])
            for field in section["fields"]
            if field["name"] in row
        }
    return out


def _live_tabby_values() -> dict[str, dict[str, Any]]:
    from common.tabby_config import config

    out: dict[str, dict[str, Any]] = {}
    for section in tabby_schema():
        obj = getattr(config, section["name"], None)
        row: dict[str, Any] = {}
        for field in section["fields"]:
            row[field["name"]] = _jsonable(getattr(obj, field["name"], None)) if obj is not None else None
        out[section["name"]] = row
    return out


def _mask(section: str, name: str, value: Any) -> Any:
    if name in SECRET_KEYS or f"{section}.{name}" in SECRET_KEYS:
        return ""
    return value


def _env_unquote(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_ASSIGN.match(line)
        if not match:
            continue
        values[match.group(2)] = _env_unquote(match.group(3))
    return values


def _system_schema(file_values: dict[str, str]) -> list[dict[str, Any]]:
    known = {item["name"] for item in SYSTEM_FIELDS}
    fields = []
    for item in SYSTEM_FIELDS:
        field = dict(item)
        field.setdefault("kind", "text")
        field.setdefault("secret", field["name"] in SECRET_KEYS)
        field.setdefault("optional", True)
        fields.append(field)
    for name in sorted(file_values):
        if name in known:
            continue
        fields.append(
            {
                "name": name,
                "label": name.replace("_", " "),
                "description": "From tabby.env.",
                "kind": "text",
                "optional": True,
                "secret": name in SECRET_KEYS,
                "extra": True,
            }
        )
    return fields


def _env_quote(value: str) -> str:
    if any(char in value for char in " \t#\"'") and not value.startswith("$"):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _write_env(updates: dict[str, Optional[str]]) -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not ENV_PATH.is_file():
        if ENV_EXAMPLE_PATH.is_file():
            shutil.copy(ENV_EXAMPLE_PATH, ENV_PATH)
        else:
            ENV_PATH.write_text("# tabby.env\n", encoding="utf-8")
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        match = _ENV_ASSIGN.match(line)
        if not match:
            out.append(line)
            continue
        key = match.group(2)
        if key not in updates:
            out.append(line)
            continue
        seen.add(key)
        value = updates[key]
        if value is None:
            out.append(f"# {key}=")
        else:
            out.append(f"{key}={_env_quote(str(value))}")
    extras = [key for key in updates if key not in seen]
    if extras:
        if out and out[-1].strip():
            out.append("")
        for key in extras:
            value = updates[key]
            if value is None:
                out.append(f"# {key}=")
            else:
                out.append(f"{key}={_env_quote(str(value))}")
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    tmp = ENV_PATH.with_suffix(ENV_PATH.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ENV_PATH)


def _coerce_field(spec: dict[str, Any], value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "" and spec.get("optional"):
        return None
    kind = spec.get("kind")
    if kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if kind == "int":
        if value == "" or value is None:
            return None
        return int(value)
    if kind == "float":
        if value == "" or value is None:
            return None
        return float(value)
    if kind == "select":
        if spec.get("blank") and (value in ("", None, "auto")):
            return None
        if spec.get("choices") == ["true", "false"]:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        return None if value in ("", None) else str(value)
    if kind == "list_text":
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            return [str(item) for item in value]
        return []
    if kind == "list_number":
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            return [float(part) if "." in part else int(part) for part in parts]
        if isinstance(value, list):
            return [float(item) if isinstance(item, float) else int(item) for item in value]
        return []
    if kind == "json":
        if isinstance(value, str):
            if not value.strip():
                return None
            import json

            return json.loads(value)
        return value
    if isinstance(value, str) and spec.get("choices") and value in spec["choices"]:
        return value
    if isinstance(value, str) and value.lower() == "auto":
        return "auto"
    return value


def _atomic_yaml(yaml: YAML, data: Any) -> None:
    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)
    tmp.replace(CONFIG_PATH)


def _apply_tabby(updates: dict[str, dict[str, Any]]) -> None:
    schema = {section["name"]: {field["name"]: field for field in section["fields"]} for section in tabby_schema()}
    yaml, data = _load_config_doc()
    if not isinstance(data, dict):
        data = {}
    merged = _plain(data)
    for section, fields in updates.items():
        if section not in schema:
            raise SettingsError(f"Unknown section {section}")
        if not isinstance(fields, dict):
            raise SettingsError(f"{section} must be an object")
        row = dict(merged.get(section) or {})
        for key, raw in fields.items():
            spec = schema[section].get(key)
            if not spec:
                raise SettingsError(f"Unknown setting {section}.{key}")
            if spec.get("secret") and (raw is None or raw == ""):
                continue
            try:
                row[key] = _coerce_field(spec, raw)
            except Exception as exc:
                raise SettingsError(f"{section}.{key}: {exc}") from exc
        merged[section] = row
        if section not in data or data[section] is None:
            data[section] = {}
        for key, value in row.items():
            data[section][key] = value
    try:
        TabbyConfigModel.model_validate(merged)
    except Exception as exc:
        raise SettingsError(str(exc)) from exc
    if not CONFIG_PATH.is_file():
        from common.tabby_config import generate_config_file

        generate_config_file(filename=str(CONFIG_PATH))
        yaml, data = _load_config_doc()
        if not isinstance(data, dict):
            data = {}
        for section, row in merged.items():
            if section not in data or data[section] is None:
                data[section] = {}
            for key, value in (row or {}).items():
                data[section][key] = value
    _atomic_yaml(yaml, data)


def _reload_live() -> None:
    from common.tabby_config import config

    cwd = Path.cwd()
    try:
        os.chdir(TABBY_ROOT)
        config.load()
    finally:
        os.chdir(cwd)


def load_settings() -> dict[str, Any]:
    file_values = _file_tabby_values()
    live_values = _live_tabby_values()
    env_values = _parse_env(ENV_PATH)
    process_env = {key: os.environ.get(key, "") for key in env_values}
    system_fields = _system_schema(env_values)
    tabby = []
    for section in tabby_schema():
        name = section["name"]
        fields = []
        for field in section["fields"]:
            row = file_values.get(name, {})
            if field["name"] in row:
                file_val = row[field["name"]]
            else:
                file_val = field.get("default")
            live_val = live_values.get(name, {}).get(field["name"])
            env_key = f"TABBY_{name}_{field['name']}".upper()
            item = dict(field)
            item["value"] = "" if field.get("secret") else file_val
            item["set"] = bool(row.get(field["name"])) if field.get("secret") else field["name"] in row
            item["live"] = None if field.get("secret") else live_val
            item["env"] = os.environ.get(env_key)
            fields.append(item)
        tabby.append({**section, "fields": fields})
    system = []
    for field in system_fields:
        name = field["name"]
        raw = env_values.get(name, "")
        item = dict(field)
        item["value"] = "" if field.get("secret") else raw
        item["set"] = bool(raw)
        item["live"] = None if field.get("secret") else process_env.get(name, os.environ.get(name, ""))
        system.append(item)
    return {
        "ok": True,
        "tabby": tabby,
        "system": {
            "name": "system",
            "label": "System",
            "description": "Stack settings from tabby.env. Applied on the next API restart.",
            "path": str(ENV_PATH),
            "fields": system,
        },
        "paths": {"config": str(CONFIG_PATH), "env": str(ENV_PATH)},
        "restart_hint": "Network, model, and tabby.env changes apply after Restart API.",
    }


def save_settings(body: dict[str, Any]) -> dict[str, Any]:
    tabby = body.get("tabby")
    system = body.get("system")
    if tabby is not None:
        if not isinstance(tabby, dict):
            raise SettingsError("tabby must be an object")
        _apply_tabby(tabby)
    if system is not None:
        if not isinstance(system, dict):
            raise SettingsError("system must be an object")
        updates: dict[str, Optional[str]] = {}
        for key, raw in system.items():
            name = str(key).strip()
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                raise SettingsError(f"Invalid environment key {name}")
            if raw is None:
                updates[name] = None
            elif name in SECRET_KEYS and str(raw) == "":
                continue
            else:
                updates[name] = str(raw)
        if updates:
            _write_env(updates)
    reload_warning = ""
    try:
        _reload_live()
    except Exception as exc:
        reload_warning = f"Saved, but live reload failed: {exc}"
    data = load_settings()
    if reload_warning:
        data = dict(data)
        data["reload_warning"] = reload_warning
    return data
