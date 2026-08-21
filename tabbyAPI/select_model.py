"""Apply a model profile to config.yml, optionally asking which one to use."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent
PROFILES_DIR = ROOT / "model_profiles"
CONFIG_PATH = ROOT / "config.yml"
LAST_PATH = PROFILES_DIR / "last.json"


def available_profiles() -> list[str]:
    return sorted(path.stem for path in PROFILES_DIR.glob("*.yml"))


def profile_aliases() -> dict[str, str]:
    aliases = {}
    names = available_profiles()
    for index, name in enumerate(names, start=1):
        aliases[str(index)] = name
        aliases[name.upper()] = name
        aliases[name] = name
    return aliases


def load_yaml(path: Path):
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    with path.open(encoding="utf-8") as handle:
        return yaml, yaml.load(handle)


def save_yaml(yaml: YAML, data, path: Path):
    with path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)


def last_profile() -> str | None:
    if LAST_PATH.exists():
        try:
            return json.loads(LAST_PATH.read_text(encoding="utf-8")).get("profile")
        except (json.JSONDecodeError, OSError):
            return None
    return None


def write_last(name: str):
    LAST_PATH.write_text(json.dumps({"profile": name}), encoding="utf-8")


def write_tabby_overlay(profile: dict):
    """Write per-folder tabby_config.yml so /v1/model/load picks up tool/reasoning settings."""
    model_cfg = dict(profile.get("model") or {})
    model_name = model_cfg.pop("model_name", None)
    if not model_name:
        return

    dest = ROOT / "models" / model_name / "tabby_config.yml"
    if not dest.parent.exists():
        print(f"  skip overlay: {dest.parent} does not exist")
        return

    overlay = {"model": model_cfg}
    draft_cfg = profile.get("draft_model")
    if draft_cfg:
        overlay["draft_model"] = dict(draft_cfg)

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    with dest.open("w", encoding="utf-8") as handle:
        yaml.dump(overlay, handle)
    print(f"  overlay: {dest}")


def apply_profile(name: str):
    profile_path = PROFILES_DIR / f"{name}.yml"
    if not profile_path.exists():
        raise SystemExit(f"Missing profile: {profile_path}")
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing {CONFIG_PATH}")

    _, profile = load_yaml(profile_path)
    yaml, config = load_yaml(CONFIG_PATH)

    pretty = profile.pop("pretty", name)
    write_tabby_overlay(profile)
    for section, values in profile.items():
        if not isinstance(values, dict):
            raise SystemExit(
                f"Profile {name}: '{section}' must be a section of key/value pairs, "
                f"got {type(values).__name__}"
            )
        if section not in config or config[section] is None:
            config[section] = {}
        for key, value in values.items():
            config[section][key] = value

    save_yaml(yaml, config, CONFIG_PATH)
    write_last(name)
    print(f"Using {pretty}")
    print(f"  model: {profile.get('model', {}).get('model_name', name)}")
    return profile


def timed_input(prompt: str, timeout: float, default: str) -> str:
    """Read a line. If nothing is typed before timeout, return default."""
    print(prompt, end="", flush=True)
    if sys.platform == "win32":
        import msvcrt

        chars: list[str] = []
        deadline = time.monotonic() + timeout
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    print()
                    return "".join(chars).strip() or default
                if ch == "\x08":
                    if chars:
                        chars.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                    continue
                if ch in ("\x00", "\xe0"):
                    msvcrt.getwch()
                    continue
                if ch == "\x03":
                    raise KeyboardInterrupt
                chars.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
                continue
            if not chars and time.monotonic() >= deadline:
                print()
                return default
            time.sleep(0.05)

    import select

    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if ready:
        return sys.stdin.readline().strip() or default
    print()
    return default


def ask_profile() -> str:
    names = available_profiles()
    current = last_profile() if last_profile() in names else (names[0] if names else "qwen")
    print()
    print("Which model?")
    print()
    for index, name in enumerate(names, start=1):
        _, data = load_yaml(PROFILES_DIR / f"{name}.yml")
        pretty = data.get("pretty", name)
        print(f"  {index}) {pretty}  [{name}]")
    print()
    default_key = str(names.index(current) + 1) if current in names else "1"
    raw = timed_input(
        f"Input [{default_key}] ({current}, auto in 5s)> ",
        timeout=5,
        default="",
    ).strip()
    if not raw:
        print(f"No choice. Using {current}.")
        return current
    aliases = profile_aliases()
    name = aliases.get(raw) or aliases.get(raw.upper()) or aliases.get(raw.lower())
    if not name:
        print("Invalid choice. Keeping the last model.")
        return current
    return name


def main():
    names = available_profiles()
    parser = argparse.ArgumentParser(description="Select a TabbyAPI model profile")
    parser.add_argument("profile", nargs="?", choices=names)
    parser.add_argument("--ask", action="store_true", help="Prompt even if a profile is given")
    args = parser.parse_args()

    name = args.profile
    if args.ask or not name:
        if sys.stdin.isatty():
            name = ask_profile()
        else:
            name = name or last_profile() or "qwen"
            print(f"No TTY; using {name}")

    apply_profile(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
