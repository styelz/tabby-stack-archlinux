"""Auto alpha punch is disabled.

Flux and Qwen-Image only emit RGB. Asking them for "transparent" used to
run a studio/chroma cutout that punched holes in subjects. Cutouts stayed
off; Code's Make transparent tool is the manual replacement.
"""


def apply_requested_alpha(raw: bytes, *, wanted: bool) -> bytes:
    """Return PNG bytes unchanged. Alpha punch is disabled."""
    return raw
