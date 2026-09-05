"""NVIDIA fan curves, power limit, and persistence for tsctl / Settings."""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import time
from ctypes import POINTER, byref, c_char_p, c_int, c_uint, c_void_p
from pathlib import Path
from typing import Any, Optional

NVML_SUCCESS = 0
NVML_TEMPERATURE_GPU = 0
NVML_FAN_POLICY_AUTO = 0
NVML_FAN_POLICY_MANUAL = 1

PROFILES = ("auto", "quiet", "balanced", "performance", "custom")

# auto_below: driver fan (idle stop) until this temp; hysteresis drops 4 C.
# points: (temp_c, fan_percent) after that, interpolated.
FAN_CURVES: dict[str, dict[str, Any]] = {
    "quiet": {
        "auto_below": 55,
        "points": [(55, 30), (68, 38), (78, 55), (85, 80), (90, 100)],
        "power_frac": 0.55,
    },
    "balanced": {
        "auto_below": 48,
        "points": [(48, 30), (62, 42), (75, 60), (83, 85), (90, 100)],
        "power_frac": 1.0,
    },
    "performance": {
        "auto_below": 0,
        "points": [(35, 40), (50, 55), (70, 75), (80, 100)],
        "power_frac": 1.0,
    },
}

TABBY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = TABBY_ROOT / "deploy" / "arch" / "tabby.env"


class GpuControlError(RuntimeError):
    pass


def _nvml_lib() -> Any:
    return ctypes.CDLL("libnvidia-ml.so.1")


def _err(nvml: Any, code: int) -> str:
    nvml.nvmlErrorString.restype = c_char_p
    nvml.nvmlErrorString.argtypes = [c_int]
    raw = nvml.nvmlErrorString(int(code))
    if not raw:
        return f"nvml {code}"
    return raw.decode("utf-8", errors="replace")


class Nvml:
    def __init__(self) -> None:
        self.nvml = _nvml_lib()
        self.nvml.nvmlInit_v2.restype = c_int
        code = self.nvml.nvmlInit_v2()
        if code != NVML_SUCCESS:
            raise GpuControlError(f"NVML init: {_err(self.nvml, code)}")
        self._bind()

    def _bind(self) -> None:
        n = self.nvml
        n.nvmlShutdown.restype = c_int
        n.nvmlDeviceGetCount_v2.restype = c_int
        n.nvmlDeviceGetCount_v2.argtypes = [POINTER(c_uint)]
        n.nvmlDeviceGetHandleByIndex_v2.restype = c_int
        n.nvmlDeviceGetHandleByIndex_v2.argtypes = [c_uint, POINTER(c_void_p)]
        n.nvmlDeviceGetName.restype = c_int
        n.nvmlDeviceGetName.argtypes = [c_void_p, c_char_p, c_uint]
        n.nvmlDeviceGetTemperature.restype = c_int
        n.nvmlDeviceGetTemperature.argtypes = [c_void_p, c_uint, POINTER(c_uint)]
        n.nvmlDeviceGetNumFans.restype = c_int
        n.nvmlDeviceGetNumFans.argtypes = [c_void_p, POINTER(c_uint)]
        n.nvmlDeviceGetFanSpeed_v2.restype = c_int
        n.nvmlDeviceGetFanSpeed_v2.argtypes = [c_void_p, c_uint, POINTER(c_uint)]
        n.nvmlDeviceSetFanSpeed_v2.restype = c_int
        n.nvmlDeviceSetFanSpeed_v2.argtypes = [c_void_p, c_uint, c_uint]
        n.nvmlDeviceSetDefaultFanSpeed_v2.restype = c_int
        n.nvmlDeviceSetDefaultFanSpeed_v2.argtypes = [c_void_p, c_uint]
        n.nvmlDeviceGetFanControlPolicy_v2.restype = c_int
        n.nvmlDeviceGetFanControlPolicy_v2.argtypes = [c_void_p, c_uint, POINTER(c_uint)]
        n.nvmlDeviceSetFanControlPolicy.restype = c_int
        n.nvmlDeviceSetFanControlPolicy.argtypes = [c_void_p, c_uint, c_uint]
        n.nvmlDeviceGetMinMaxFanSpeed.restype = c_int
        n.nvmlDeviceGetMinMaxFanSpeed.argtypes = [c_void_p, POINTER(c_uint), POINTER(c_uint)]
        n.nvmlDeviceGetPowerUsage.restype = c_int
        n.nvmlDeviceGetPowerUsage.argtypes = [c_void_p, POINTER(c_uint)]
        n.nvmlDeviceGetPowerManagementLimit.restype = c_int
        n.nvmlDeviceGetPowerManagementLimit.argtypes = [c_void_p, POINTER(c_uint)]
        n.nvmlDeviceGetPowerManagementDefaultLimit.restype = c_int
        n.nvmlDeviceGetPowerManagementDefaultLimit.argtypes = [c_void_p, POINTER(c_uint)]
        n.nvmlDeviceGetPowerManagementLimitConstraints.restype = c_int
        n.nvmlDeviceGetPowerManagementLimitConstraints.argtypes = [
            c_void_p,
            POINTER(c_uint),
            POINTER(c_uint),
        ]
        n.nvmlDeviceSetPowerManagementLimit.restype = c_int
        n.nvmlDeviceSetPowerManagementLimit.argtypes = [c_void_p, c_uint]
        n.nvmlDeviceGetClockInfo.restype = c_int
        n.nvmlDeviceGetClockInfo.argtypes = [c_void_p, c_uint, POINTER(c_uint)]

    def close(self) -> None:
        try:
            self.nvml.nvmlShutdown()
        except Exception:
            pass

    def __enter__(self) -> "Nvml":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _check(self, code: int, what: str) -> None:
        if code != NVML_SUCCESS:
            raise GpuControlError(f"{what}: {_err(self.nvml, code)}")

    def count(self) -> int:
        value = c_uint()
        self._check(self.nvml.nvmlDeviceGetCount_v2(byref(value)), "GPU count")
        return int(value.value)

    def handle(self, index: int) -> c_void_p:
        device = c_void_p()
        self._check(
            self.nvml.nvmlDeviceGetHandleByIndex_v2(c_uint(index), byref(device)),
            f"GPU {index}",
        )
        return device

    def name(self, device: c_void_p) -> str:
        buf = ctypes.create_string_buffer(96)
        code = self.nvml.nvmlDeviceGetName(device, buf, 96)
        if code != NVML_SUCCESS:
            return ""
        return buf.value.decode("utf-8", errors="replace")

    def temperature(self, device: c_void_p) -> Optional[int]:
        value = c_uint()
        code = self.nvml.nvmlDeviceGetTemperature(device, NVML_TEMPERATURE_GPU, byref(value))
        if code != NVML_SUCCESS:
            return None
        return int(value.value)

    def num_fans(self, device: c_void_p) -> int:
        value = c_uint()
        code = self.nvml.nvmlDeviceGetNumFans(device, byref(value))
        if code != NVML_SUCCESS:
            return 0
        return int(value.value)

    def fan_speed(self, device: c_void_p, fan: int) -> Optional[int]:
        value = c_uint()
        code = self.nvml.nvmlDeviceGetFanSpeed_v2(device, c_uint(fan), byref(value))
        if code != NVML_SUCCESS:
            return None
        return int(value.value)

    def fan_policy(self, device: c_void_p, fan: int) -> Optional[int]:
        value = c_uint()
        code = self.nvml.nvmlDeviceGetFanControlPolicy_v2(device, c_uint(fan), byref(value))
        if code != NVML_SUCCESS:
            return None
        return int(value.value)

    def fan_minmax(self, device: c_void_p) -> tuple[int, int]:
        low = c_uint()
        high = c_uint()
        code = self.nvml.nvmlDeviceGetMinMaxFanSpeed(device, byref(low), byref(high))
        if code != NVML_SUCCESS:
            return 30, 100
        return int(low.value), int(high.value)

    def power_mw(self, device: c_void_p) -> Optional[int]:
        value = c_uint()
        code = self.nvml.nvmlDeviceGetPowerUsage(device, byref(value))
        if code != NVML_SUCCESS:
            return None
        return int(value.value)

    def power_limit_mw(self, device: c_void_p) -> Optional[int]:
        value = c_uint()
        code = self.nvml.nvmlDeviceGetPowerManagementLimit(device, byref(value))
        if code != NVML_SUCCESS:
            return None
        return int(value.value)

    def power_default_mw(self, device: c_void_p) -> Optional[int]:
        value = c_uint()
        code = self.nvml.nvmlDeviceGetPowerManagementDefaultLimit(device, byref(value))
        if code != NVML_SUCCESS:
            return None
        return int(value.value)

    def power_range_mw(self, device: c_void_p) -> tuple[Optional[int], Optional[int]]:
        low = c_uint()
        high = c_uint()
        code = self.nvml.nvmlDeviceGetPowerManagementLimitConstraints(device, byref(low), byref(high))
        if code != NVML_SUCCESS:
            return None, None
        return int(low.value), int(high.value)

    def clock_mhz(self, device: c_void_p, kind: int) -> Optional[int]:
        value = c_uint()
        code = self.nvml.nvmlDeviceGetClockInfo(device, c_uint(kind), byref(value))
        if code != NVML_SUCCESS:
            return None
        return int(value.value)

    def set_fan(self, device: c_void_p, fan: int, percent: int) -> None:
        self._check(
            self.nvml.nvmlDeviceSetFanControlPolicy(device, c_uint(fan), NVML_FAN_POLICY_MANUAL),
            f"fan {fan} policy",
        )
        self._check(
            self.nvml.nvmlDeviceSetFanSpeed_v2(device, c_uint(fan), c_uint(percent)),
            f"fan {fan} speed",
        )

    def reset_fan(self, device: c_void_p, fan: int) -> None:
        self._check(
            self.nvml.nvmlDeviceSetDefaultFanSpeed_v2(device, c_uint(fan)),
            f"fan {fan} default",
        )
        self._check(
            self.nvml.nvmlDeviceSetFanControlPolicy(device, c_uint(fan), NVML_FAN_POLICY_AUTO),
            f"fan {fan} auto",
        )

    def set_power_mw(self, device: c_void_p, milliwatts: int) -> None:
        self._check(
            self.nvml.nvmlDeviceSetPowerManagementLimit(device, c_uint(milliwatts)),
            "power limit",
        )


def _mw_to_w(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    return int(round(value / 1000.0))


def query() -> dict[str, Any]:
    """Live sensors. Reads do not need root."""
    try:
        nvml = Nvml()
    except (OSError, GpuControlError) as exc:
        return {"ok": False, "error": str(exc), "gpus": []}
    gpus: list[dict[str, Any]] = []
    try:
        for index in range(nvml.count()):
            device = nvml.handle(index)
            fans = []
            count = nvml.num_fans(device)
            for fan in range(count):
                fans.append(
                    {
                        "index": fan,
                        "speed": nvml.fan_speed(device, fan),
                        "policy": nvml.fan_policy(device, fan),
                    }
                )
            low, high = nvml.fan_minmax(device)
            pmin, pmax = nvml.power_range_mw(device)
            gpus.append(
                {
                    "index": index,
                    "name": nvml.name(device),
                    "temperature_c": nvml.temperature(device),
                    "fans": fans,
                    "fan_min": low,
                    "fan_max": high,
                    "fan_control": count > 0,
                    "power_w": _mw_to_w(nvml.power_mw(device)),
                    "power_limit_w": _mw_to_w(nvml.power_limit_mw(device)),
                    "power_default_w": _mw_to_w(nvml.power_default_mw(device)),
                    "power_min_w": _mw_to_w(pmin),
                    "power_max_w": _mw_to_w(pmax),
                    "clock_graphics_mhz": nvml.clock_mhz(device, 0),
                    "clock_memory_mhz": nvml.clock_mhz(device, 2),
                    "root": os.geteuid() == 0,
                }
            )
    except GpuControlError as exc:
        nvml.close()
        return {"ok": False, "error": str(exc), "gpus": gpus}
    nvml.close()
    return {"ok": True, "gpus": gpus}


def format_status(info: Optional[dict[str, Any]] = None) -> str:
    data = info if info is not None else query()
    if not data.get("ok") and not data.get("gpus"):
        return data.get("error") or "NVIDIA GPU not available"
    lines: list[str] = []
    if data.get("error"):
        lines.append(str(data["error"]))
    for gpu in data.get("gpus") or []:
        fans = gpu.get("fans") or []
        speeds = ", ".join(
            f"{item.get('speed')}%" if item.get("speed") is not None else "?" for item in fans
        ) or "n/a"
        manual = any(item.get("policy") == NVML_FAN_POLICY_MANUAL for item in fans)
        lines.append(
            f"{gpu.get('name') or 'GPU'}  {gpu.get('temperature_c')}C  "
            f"fan {speeds} ({'manual' if manual else 'auto'})  "
            f"{gpu.get('power_w')}W / {gpu.get('power_limit_w')}W "
            f"(min {gpu.get('power_min_w')}, max {gpu.get('power_max_w')})"
        )
        if gpu.get("clock_graphics_mhz") is not None:
            lines.append(
                f"  clocks  {gpu.get('clock_graphics_mhz')} / {gpu.get('clock_memory_mhz')} MHz  "
                f"fan range {gpu.get('fan_min')}-{gpu.get('fan_max')}%"
            )
    return "\n".join(lines) if lines else "No NVIDIA GPU"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    assign = re.compile(r"^(\s*)(?:#\s*)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = assign.match(line)
        if not match:
            continue
        raw = match.group(3).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        values[match.group(2)] = raw
    return values


def settings_from_mapping(values: dict[str, str]) -> dict[str, Any]:
    profile = str(values.get("TABBY_GPU_PROFILE") or "auto").strip().lower()
    if profile not in PROFILES:
        profile = "auto"
    fan_raw = str(values.get("TABBY_GPU_FAN_SPEED") or "").strip()
    power_raw = str(values.get("TABBY_GPU_POWER_LIMIT") or "").strip()
    persist_raw = str(values.get("TABBY_GPU_PERSISTENCE") or "").strip().lower()
    try:
        fan_speed = int(fan_raw) if fan_raw else 0
    except ValueError:
        fan_speed = 0
    try:
        power_limit = int(power_raw) if power_raw else 0
    except ValueError:
        power_limit = 0
    persistence: Optional[bool]
    if persist_raw == "":
        persistence = None
    else:
        persistence = persist_raw in ("1", "true", "yes", "on")
    return {
        "profile": profile,
        "fan_speed": fan_speed,
        "power_limit": power_limit,
        "persistence": persistence,
    }


def settings_from_env(path: Optional[Path] = None) -> dict[str, Any]:
    file_values = parse_env_file(path or DEFAULT_ENV)
    merged: dict[str, str] = {}
    for key in (
        "TABBY_GPU_PROFILE",
        "TABBY_GPU_FAN_SPEED",
        "TABBY_GPU_POWER_LIMIT",
        "TABBY_GPU_PERSISTENCE",
    ):
        if key in os.environ and str(os.environ.get(key, "")).strip() != "":
            merged[key] = str(os.environ.get(key, ""))
        if key in file_values:
            merged[key] = file_values[key]
    return settings_from_mapping(merged)


def _interpolate(points: list[tuple[int, int]], temp: int) -> int:
    if not points:
        return 30
    if temp <= points[0][0]:
        return points[0][1]
    if temp >= points[-1][0]:
        return points[-1][1]
    for index in range(1, len(points)):
        t0, s0 = points[index - 1]
        t1, s1 = points[index]
        if temp <= t1:
            if t1 == t0:
                return s1
            ratio = (temp - t0) / float(t1 - t0)
            return int(round(s0 + ratio * (s1 - s0)))
    return points[-1][1]


def fan_target(profile: str, temp: Optional[int], custom: int, fan_min: int) -> Optional[int]:
    """Percent, or None to leave the driver in auto (idle fan-stop)."""
    if profile == "auto":
        return None
    if profile == "custom":
        if custom <= 0:
            return None
        return max(fan_min, min(100, custom))
    curve = FAN_CURVES.get(profile)
    if not curve or temp is None:
        return None
    auto_below = int(curve.get("auto_below") or 0)
    if auto_below and temp < auto_below:
        return None
    percent = _interpolate(list(curve["points"]), temp)
    return max(fan_min, min(100, percent))


def power_target_w(
    profile: str,
    override: int,
    default_w: Optional[int],
    min_w: Optional[int],
    max_w: Optional[int],
) -> Optional[int]:
    if override and override > 0:
        watts = override
    elif profile in FAN_CURVES:
        frac = float(FAN_CURVES[profile].get("power_frac") or 1.0)
        base = default_w if default_w is not None else max_w
        floor = min_w if min_w is not None else 0
        if base is None:
            return None
        watts = int(round(floor + frac * (base - floor)))
    elif profile == "auto":
        watts = default_w
    else:
        return None
    if watts is None:
        return None
    if min_w is not None:
        watts = max(min_w, watts)
    if max_w is not None:
        watts = min(max_w, watts)
    return watts


def _run_smi(args: list[str]) -> tuple[int, str]:
    import subprocess

    cmd = ["nvidia-smi", *args]
    if os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception as exc:
        return 1, str(exc)
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode, text


def set_persistence(enabled: bool) -> str:
    code, text = _run_smi(["-pm", "1" if enabled else "0"])
    if code != 0:
        raise GpuControlError(text or "nvidia-smi persistence failed")
    return text


def apply(settings: dict[str, Any], *, nvml: Optional[Nvml] = None) -> str:
    """Apply profile. Fan and power writes need root (NVML)."""
    profile = str(settings.get("profile") or "auto").strip().lower()
    if profile not in PROFILES:
        raise GpuControlError(f"Unknown GPU profile {profile}")
    fan_speed = int(settings.get("fan_speed") or 0)
    power_limit = int(settings.get("power_limit") or 0)
    persistence = settings.get("persistence")
    notes: list[str] = []
    if persistence is True or persistence is False:
        try:
            notes.append(set_persistence(bool(persistence)))
        except GpuControlError as exc:
            notes.append(str(exc))
    own = nvml is None
    if nvml is None:
        nvml = Nvml()
    try:
        for index in range(nvml.count()):
            device = nvml.handle(index)
            low, _high = nvml.fan_minmax(device)
            temp = nvml.temperature(device)
            target = fan_target(profile, temp, fan_speed, low)
            if target is None:
                for fan in range(nvml.num_fans(device)):
                    nvml.reset_fan(device, fan)
                notes.append(f"GPU{index} fan auto")
            else:
                for fan in range(nvml.num_fans(device)):
                    nvml.set_fan(device, fan, target)
                notes.append(f"GPU{index} fan {target}%")
            watts = power_target_w(
                profile,
                power_limit,
                _mw_to_w(nvml.power_default_mw(device)),
                _mw_to_w(nvml.power_range_mw(device)[0]),
                _mw_to_w(nvml.power_range_mw(device)[1]),
            )
            if watts is not None:
                nvml.set_power_mw(device, int(watts * 1000))
                notes.append(f"GPU{index} power {watts}W")
    finally:
        if own:
            nvml.close()
    return "; ".join(notes) if notes else "ok"


def apply_as_root(settings: dict[str, Any]) -> str:
    if os.geteuid() == 0:
        return apply(settings)
    import subprocess

    payload = json.dumps(settings)
    result = subprocess.run(
        ["sudo", "-n", sys.executable, str(Path(__file__).resolve()), "apply-json"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=20,
    )
    text = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        raise GpuControlError(text or "GPU apply needs passwordless sudo")
    return text or "ok"


class FanDaemon:
    def __init__(self) -> None:
        self._last: dict[int, tuple[Optional[int], Optional[int]]] = {}
        self._auto_latched: dict[int, bool] = {}
        self._ticks = 0

    def tick(self, nvml: Nvml, settings: dict[str, Any]) -> list[str]:
        profile = str(settings.get("profile") or "auto").strip().lower()
        fan_speed = int(settings.get("fan_speed") or 0)
        power_limit = int(settings.get("power_limit") or 0)
        self._ticks += 1
        force = self._ticks % 15 == 1
        notes: list[str] = []
        for index in range(nvml.count()):
            device = nvml.handle(index)
            low, _high = nvml.fan_minmax(device)
            temp = nvml.temperature(device)
            hysteresis = 4
            curve = FAN_CURVES.get(profile) or {}
            auto_below = int(curve.get("auto_below") or 0)
            latched = self._auto_latched.get(index, True)
            if profile in FAN_CURVES and auto_below and temp is not None:
                if latched and temp >= auto_below:
                    latched = False
                elif not latched and temp <= auto_below - hysteresis:
                    latched = True
                self._auto_latched[index] = latched
                effective_temp = temp if not latched else auto_below - 1
            else:
                effective_temp = temp
                self._auto_latched[index] = True
            target = fan_target(profile, effective_temp, fan_speed, low)
            prev_fan, prev_power = self._last.get(index, (None, None))
            if target != prev_fan or (force and target is not None):
                if target is None:
                    for fan in range(nvml.num_fans(device)):
                        nvml.reset_fan(device, fan)
                    notes.append(f"GPU{index} fan auto")
                else:
                    for fan in range(nvml.num_fans(device)):
                        nvml.set_fan(device, fan, target)
                    if target != prev_fan:
                        notes.append(f"GPU{index} fan {target}%")
            watts = power_target_w(
                profile,
                power_limit,
                _mw_to_w(nvml.power_default_mw(device)),
                _mw_to_w(nvml.power_range_mw(device)[0]),
                _mw_to_w(nvml.power_range_mw(device)[1]),
            )
            if watts is not None and (watts != prev_power or force):
                nvml.set_power_mw(device, int(watts * 1000))
                if watts != prev_power:
                    notes.append(f"GPU{index} power {watts}W")
            self._last[index] = (target, watts)
        return notes


def run_daemon(env_path: Optional[Path] = None) -> int:
    path = env_path or DEFAULT_ENV
    state = FanDaemon()
    persistence_applied: Optional[bool] = None
    nvml: Optional[Nvml] = None
    print(f"tabby-gpu: watching {path}", flush=True)
    while True:
        try:
            settings = settings_from_env(path)
            wanted = settings.get("persistence")
            if wanted is True or wanted is False:
                if wanted != persistence_applied:
                    try:
                        print(set_persistence(bool(wanted)), flush=True)
                        persistence_applied = bool(wanted)
                    except GpuControlError as exc:
                        print(f"tabby-gpu persistence: {exc}", flush=True)
            if nvml is None:
                nvml = Nvml()
            notes = state.tick(nvml, settings)
            for line in notes:
                print(line, flush=True)
        except (OSError, GpuControlError) as exc:
            print(f"tabby-gpu: {exc}", flush=True)
            if nvml is not None:
                nvml.close()
                nvml = None
            state = FanDaemon()
        time.sleep(2.0)


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("status", "-q"):
        print(format_status())
        return 0
    if args[0] == "json":
        print(json.dumps(query(), indent=2))
        return 0
    if args[0] == "apply-json":
        body = json.loads(sys.stdin.read() or "{}")
        print(apply(body if isinstance(body, dict) else {}))
        return 0
    if args[0] == "apply":
        env_path = Path(args[1]) if len(args) > 1 else DEFAULT_ENV
        print(apply(settings_from_env(env_path)))
        return 0
    if args[0] == "daemon":
        env_path = DEFAULT_ENV
        if "--env" in args:
            idx = args.index("--env")
            if idx + 1 < len(args):
                env_path = Path(args[idx + 1])
        elif len(args) > 1 and not args[1].startswith("-"):
            env_path = Path(args[1])
        return run_daemon(env_path)
    print("usage: gpu_control.py status|json|apply|daemon", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GpuControlError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
