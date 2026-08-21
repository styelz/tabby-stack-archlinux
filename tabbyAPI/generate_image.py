"""GPU-server CLI: hand the GPU to Comfy, write a PNG, then reload the last LLM.

Remote IDEs should not run this. Use chat (“generate an image of …”) or
POST /v1/images/generations on the API host the client already uses.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from common.gpu_mode import generate_image as comfy_generate
from common.gpu_mode import save_generated_image
from common.switch_times import extra_seconds, format_duration, gpu_label, ready_seconds
from select_model import last_profile
from switch_model import api_base, switch_to_comfy, switch_to_llm


def _image_times_epilog() -> str:
    flux = extra_seconds("comfy", "flux_s")
    qwen_img = extra_seconds("comfy", "qwen_image_s")
    bits = [
        f"Warm {gpu_label()} times: Comfy ready ~{format_duration(ready_seconds('comfy'))}"
    ]
    if flux:
        bits.append(f"first Flux ~{format_duration(flux)}")
    if qwen_img:
        bits.append(f"first Qwen-Image ~{format_duration(qwen_img)}")
    bits.append(f"then reload last LLM ~{format_duration(ready_seconds('llm'))}.")
    return "; ".join(bits)


def run_generate(
    prompt: str,
    output: Path | None = None,
    size: str = "1024x1024",
    seed: int = 0,
    stay_comfy: bool = False,
    qwen_image: bool = False,
) -> dict:
    text = (prompt or "").strip()
    if not text:
        raise SystemExit("prompt is required")
    if qwen_image and not text.lower().lstrip().startswith("qwen-image"):
        text = f"qwen-image: {text}"

    restore_name = last_profile() or "qwen"
    base = api_base()

    started = time.time()
    switch_to_comfy(base)
    ready_s = time.time() - started

    gen_started = time.time()
    raw = comfy_generate(text, size=size, seed=seed)
    saved = save_generated_image(raw)
    dest = saved
    if output is not None:
        dest = Path(output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    generate_s = time.time() - gen_started

    restore_s = 0.0
    if not stay_comfy:
        rest_started = time.time()
        switch_to_llm(restore_name, base=base)
        restore_s = time.time() - rest_started

    return {
        "path": str(dest),
        "saved": str(saved),
        "prompt": text,
        "size": size,
        "ready_s": round(ready_s, 1),
        "generate_s": round(generate_s, 1),
        "restore_s": round(restore_s, 1),
        "stay_comfy": stay_comfy,
        "restored": None if stay_comfy else restore_name,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one PNG via ComfyUI, then reload the last LLM",
        epilog=_image_times_epilog(),
    )
    parser.add_argument("prompt", help="Image description. Prefix qwen-image: for readable text.")
    parser.add_argument("-o", "--output", type=Path, help="Destination PNG (also writes pasted-images/)")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--stay-comfy",
        action="store_true",
        help="Leave the GPU on Comfy; do not reload the LLM",
    )
    parser.add_argument(
        "--qwen-image",
        action="store_true",
        help="Force the Qwen-Image workflow (text / posters / UI)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_generate(
        args.prompt,
        output=args.output,
        size=args.size,
        seed=args.seed,
        stay_comfy=args.stay_comfy,
        qwen_image=args.qwen_image,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
