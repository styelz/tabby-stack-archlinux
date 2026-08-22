"""Rewrite agent image prompts before they hit Comfy.

The coding model often sends "website hero banner" or "header for the site".
Flux/Qwen-Image then paint a finished webpage. This module keeps logos and
real text on Qwen-Image, and turns hero/header photos into Flux scenes.

It also turns a mixed coding+images chat line into a concrete PNG job list
so VS Code/Cursor cannot substitute SVG or CSS art unless the user asked.
"""

from __future__ import annotations

import json
import re

QWEN_PREFIX = re.compile(r"(?is)^\s*qwen-image\s*:\s*(.*)$")
FLUX_PREFIX = re.compile(r"(?is)^\s*flux\s*:\s*(.*)$")
FORCE_FLUX_RE = re.compile(r"(?is)(?:^\s*(?:use\s+)?flux\s*:?\s*|\buse\s+flux\b)")
NAMED_PNG_RE = re.compile(r"(?i)\b([\w.-]+\.png)\b")
RECTANGLE_ASK = re.compile(r"(?is)\brectangl")
LOGO_SLOT = re.compile(
    r"(?is)\b(logo|wordmark|word[-\s]?mark|favicon|brand\s*mark)\b"
)
HERO_SLOT = re.compile(
    r"(?is)\b("
    r"hero|header|banner|masthead|backdrop|cover\s*photo|"
    r"hero\s*image|page\s*photo|section\s*(?:image|photo)"
    r")\b"
)
WEBSITE_NOISE = re.compile(
    r"(?is)\b("
    r"website|web\s*site|web\s*page|webpage|landing\s*page|"
    r"web\s*app|homepage|home\s*page|browser|html|css|"
    r"javascript|responsive|navbar|nav\s*bar|"
    r"hero\s*section|above\s*the\s*fold|call\s*to\s*action|\bcta\b"
    r")\b"
)
UI_SHOT = re.compile(
    r"(?is)\b("
    r"screenshot|wireframe|ui\s*kit|completed\s+website|"
    r"finished\s+website|full\s+page|desktop\s+site|mobile\s+site|"
    r"browser\s*chrome"
    r")\b"
)
EXPLICIT_UI = re.compile(
    r"(?is)\b("
    r"ui\s*mockup|settings\s*screen|login\s*form|sign[-\s]?in\s*form|"
    r"app\s*ui|user\s*interface|dashboard\s*ui"
    r")\b"
)
TEXT_INTENT = re.compile(
    r"(?is)\b("
    r"says?|reads?|lettering|typography|caption|labeled|"
    r"heading|headline|poster|button|sign|label|"
    r"login\s*form|ui\s*mockup"
    r")\b"
    r"|[\"“][^\"”]{1,48}[\"”]"
)
VECTOR_NOISE = re.compile(
    r"(?is)\b("
    r"svgs?|vector\s+art|vector\s+logo|css\s+art|css[- ]generated|"
    r"pure\s+css|inline\s+svg|css\s+(?:shapes?|orbs?|planets?)"
    r")\b"
)
SCENE_TAIL = (
    "wide photographic scene, no text, no letters, no logo, "
    "no user interface, no website, no browser, no mockup"
)
LOGO_TAIL = (
    "isolated logo mark only, centered, simple background, "
    "emblem, no browser chrome, no navigation bar, no page layout"
)
TRANSPARENT_RE = re.compile(r"(?is)\btransparent\b")

PLANET_SCENES: tuple[tuple[str, str], ...] = (
    (
        "mercury",
        "photograph of planet Mercury, cratered gray rocky world closest to "
        "the sun, harsh sunlight, no spacecraft, no text",
    ),
    (
        "venus",
        "photograph of planet Venus, thick yellowish sulfuric clouds, "
        "glowing atmosphere, no text",
    ),
    (
        "earth",
        "photograph of planet Earth from space, blue oceans, white clouds, "
        "continents, no text",
    ),
    (
        "mars",
        "photograph of planet Mars, rusty red deserts and polar ice, thin "
        "atmosphere, no text",
    ),
    (
        "jupiter",
        "photograph of planet Jupiter, banded gas giant, Great Red Spot, "
        "no text",
    ),
    (
        "saturn",
        "photograph of planet Saturn with bright ice rings, pale gold, no text",
    ),
    (
        "uranus",
        "photograph of planet Uranus, pale cyan ice giant, faint rings, no text",
    ),
    (
        "neptune",
        "photograph of planet Neptune, deep blue ice giant, dark storms, no text",
    ),
)
PLANET_NAMES = tuple(name for name, _ in PLANET_SCENES)
PLANET_NAME_RE = re.compile(
    r"(?is)\b(" + "|".join(PLANET_NAMES) + r")\b"
)
HERO_IMAGE_ASK = re.compile(
    r"(?is)\b("
    r"hero\s*image|header\s*image|cover\s*photo|"
    r"(?:hero|header|banner|masthead).{0,24}(?:image|picture|photo|pic)|"
    r"(?:image|picture|photo|pic).{0,24}(?:hero|header|banner|masthead)"
    r")\b"
)
EACH_PLANET_RE = re.compile(
    r"(?is)("
    r"\b(?:each|every|the)\s+planets?\b|"
    r"\bplanets?\b.{0,80}\b(?:image|picture|photo|pic)s?\b|"
    r"\b(?:image|picture|photo|pic)s?\b.{0,80}\b(?:each|every|the)\s+planets?\b|"
    r"\bvisit\s+other\s+plantes?\b|"
    r"\bsolar\s+syst\w*.{0,120}\b(?:planets?|plantes?)\b"
    r")"
)
FOLDER_RE = re.compile(
    r"(?is)\b(?:under|in|into|inside)\s+(?:the\s+)?"
    r"(?:folder|directory|dir)\s+[\"`'“”]?([A-Za-z][A-Za-z0-9._-]*)"
    r"|\b(?:folder|directory)\s+[\"`'“”]?([A-Za-z][A-Za-z0-9._-]*)"
    r"|\b([A-Za-z][A-Za-z0-9._-]{1,40})\s+(?:folder|directory)\b"
    # Bare "under/in/into/inside <name>" with no "folder"/"directory" word
    # ("create a site under pbptours and generate a logo ..."). Only accept
    # it when the name is immediately followed by punctuation/end or by an
    # "and <verb>" clause, so ordinary phrases like "under construction and
    # needs a logo" (no matching verb) do not get misread as a site name.
    r"|\b(?:under|in|into|inside)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9._-]{1,40})\b"
    r"(?:\s*,)?(?:\s+and)?\s*"
    r"(?=(?:generat|creat|mak|build|draw|render|writ|sav|add|includ)\w*\b|[.,]|$)"
)
IMAGES_DIR_RE = re.compile(
    r"(?is)\b([A-Za-z][A-Za-z0-9._-]*/images)\b"
)
COMPANY_RE = re.compile(
    r"(?is)\b(?:company|brand|called|named)\s+[\"“']([^\"”']{2,80})[\"”']"
    r"|\blogo\b.{0,80}(?:says?|called|named)\s+[\"“']([^\"”']{2,80})[\"”']"
    r"|\b(?:company|brand)\s+"
    r"(?-i:([A-Z][A-Za-z0-9&']+(?:\s+[A-Z][A-Za-z0-9&']+){1,6}))"
    r"|\b(?:website|web\s*site|web\s*page|webpage|site|company|brand)"
    r"\s+(?:for|called|named)\s+"
    r"(?:[\"“']([^\"”']{2,80})[\"”']|"
    r"(?-i:([A-Z][A-Za-z0-9&']+(?:\s+[A-Z][A-Za-z0-9&']+){0,6})))"
)
ASKED_SVG_RE = re.compile(
    r"(?is)\b(?:use|using|as|want|need|prefer|make|create|generate)\b"
    r".{0,40}\bsvgs?\b"
    r"|\bsvg\s+(?:logo|icon|image|file|files?)\b"
    r"|\b(?:logo|icon)s?\s+as\s+svgs?\b"
    r"|\.svg\b"
)
REJECTED_SVG_RE = re.compile(
    r"(?is)\b(?:no|not|never|don't|do\s+not|instead\s+of|without|stop|"
    r"don't\s+want|do\s+not\s+want)\b.{0,40}\bsvgs?\b"
    r"|\bsvgs?\b.{0,40}\b(?:instead|wrong|were\s+generated|"
    r"not\s+what|don't\s+want)\b"
)
MAX_PLANNED_IMAGES = 12
MIXED_PLAN_MARK = "Interpreted PNG jobs from the user request"


def _collapse(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "")
    text = re.sub(r"(?:,\s*){2,}", ", ", text)
    return text.strip(" ,.;:-")


def _strip_noise(body: str) -> str:
    cleaned = WEBSITE_NOISE.sub(" ", body)
    cleaned = UI_SHOT.sub(" ", cleaned)
    cleaned = VECTOR_NOISE.sub(" ", cleaned)
    return _collapse(cleaned)


def _strip_vector_noise(body: str) -> str:
    return _collapse(VECTOR_NOISE.sub(" ", body))


def user_asked_for_svg(text: str) -> bool:
    """True only when the user wants SVG as the file format."""
    raw = text or ""
    if REJECTED_SVG_RE.search(raw):
        return False
    return bool(ASKED_SVG_RE.search(raw))


def _quoted_or_group(match: re.Match[str]) -> str:
    for value in match.groups():
        if value:
            return value.strip()
    return ""


def site_folder(text: str) -> str:
    match = FOLDER_RE.search(text or "")
    if not match:
        return ""
    return _quoted_or_group(match).rstrip(".,;:")


def images_folder(text: str, folder: str = "") -> str:
    match = IMAGES_DIR_RE.search(text or "")
    if match:
        return match.group(1).replace("\\", "/").strip("/")
    if folder:
        return f"{folder}/images"
    return "images"


def company_name(text: str) -> str:
    match = COMPANY_RE.search(text or "")
    if not match:
        return ""
    return _quoted_or_group(match)


def named_planets(text: str) -> list[str]:
    """Planet names the user listed, in the order they appear."""
    found: list[str] = []
    seen: set[str] = set()
    for match in PLANET_NAME_RE.finditer(text or ""):
        name = (match.group(1) or "").strip().lower()
        if name and name not in seen:
            seen.add(name)
            found.append(name)
    return found


def _planet_scene(name: str) -> str:
    key = (name or "").strip().lower()
    for planet, scene in PLANET_SCENES:
        if planet == key:
            body = scene
            break
    else:
        body = (
            f"photograph of planet {name}, solar system, cinematic lighting"
        )
    if SCENE_TAIL in body:
        return body
    return f"{body}, {SCENE_TAIL}"


def rewrite_comfy_prompt(prompt: str) -> str:
    """Return the prompt Comfy should actually render."""
    raw = (prompt or "").strip()
    if not raw:
        return raw
    if LOGO_TAIL in raw:
        return raw
    if SCENE_TAIL in raw and not QWEN_PREFIX.match(raw):
        return raw

    flux_prefixed = FLUX_PREFIX.match(raw)
    if flux_prefixed:
        body = _collapse((flux_prefixed.group(1) or "").strip())
        return f"flux: {body}" if body else raw
    wants_flux = bool(FORCE_FLUX_RE.search(raw))
    if wants_flux:
        raw = _collapse(FORCE_FLUX_RE.sub(" ", raw))
    prefixed = QWEN_PREFIX.match(raw)
    body = _collapse((prefixed.group(1) if prefixed else raw) or "")
    body = _strip_vector_noise(body)
    is_logo = bool(LOGO_SLOT.search(body))
    is_hero = bool(HERO_SLOT.search(body)) and not is_logo
    wants_text = bool(TEXT_INTENT.search(body))
    explicit_ui = bool(EXPLICIT_UI.search(body))
    planet = PLANET_NAME_RE.search(body)

    if is_hero and not wants_text and not explicit_ui:
        cleaned = _strip_noise(HERO_SLOT.sub(" ", body))
        cleaned = re.sub(r"(?is)\b(ui|ux|gui|interface)\b", " ", cleaned)
        cleaned = _collapse(cleaned)
        if len(cleaned) < 8:
            cleaned = "wide atmospheric photograph, rich color, cinematic lighting"
        return f"{cleaned}, {SCENE_TAIL}"

    if (
        planet
        and not is_logo
        and not wants_text
        and not explicit_ui
    ):
        return _planet_scene(planet.group(1))

    if UI_SHOT.search(body) and not is_logo and not wants_text and not explicit_ui:
        cleaned = _strip_noise(body)
        if len(cleaned) < 8:
            cleaned = "wide atmospheric photograph, rich color, cinematic lighting"
        return f"{cleaned}, {SCENE_TAIL}"

    if is_logo:
        cleaned = _strip_noise(body)
        if not cleaned:
            cleaned = "elegant brand logo"
        if TRANSPARENT_RE.search(raw) and "transparent" not in cleaned.lower():
            cleaned = f"{cleaned}, transparent background"
        if LOGO_TAIL not in cleaned:
            cleaned = f"{cleaned}, {LOGO_TAIL}"
        if wants_flux:
            return f"flux: {cleaned}"
        if cleaned.lower().startswith("qwen-image"):
            return cleaned
        return f"qwen-image: {cleaned}"

    if prefixed or explicit_ui:
        cleaned = _strip_vector_noise(body)
        return raw if prefixed else f"qwen-image: {cleaned}"

    if WEBSITE_NOISE.search(body):
        cleaned = _strip_noise(body)
        if not cleaned:
            return raw
        if wants_text:
            return cleaned
        return f"{cleaned}, no text, no user interface, no website mockup"

    return raw


def plan_mixed_images(text: str) -> list[dict[str, str]]:
    """Turn a page+images ask into concrete PNG dests and Comfy prompts."""
    raw = text or ""
    if not raw.strip():
        return []
    folder = site_folder(raw)
    dest_dir = images_folder(raw, folder)
    items: list[dict[str, str]] = []

    def add(prompt: str, filename: str) -> None:
        if len(items) >= MAX_PLANNED_IMAGES:
            return
        name = filename if filename.endswith(".png") else f"{filename}.png"
        path = f"{dest_dir}/{name}".replace("//", "/")
        items.append(
            {
                "prompt": rewrite_comfy_prompt(prompt),
                "output_path": path,
            }
        )

    brand = company_name(raw)
    if LOGO_SLOT.search(raw):
        extra = ", transparent background" if TRANSPARENT_RE.search(raw) else ""
        if brand:
            add(
                f"logo that says {brand}, clean brand mark, readable letters{extra}",
                "logo.png",
            )
        else:
            add(f"elegant brand logo, clean readable letters{extra}", "logo.png")

    if HERO_IMAGE_ASK.search(raw):
        scene = brand or folder or "the destination"
        add(
            f"wide cinematic photograph for {scene}, atmospheric, "
            "no website, no user interface",
            "header.png",
        )

    listed = named_planets(raw)
    if len(listed) >= 2:
        scenes = {name: scene for name, scene in PLANET_SCENES}
        for name in listed:
            add(scenes.get(name) or f"photograph of planet {name}", f"{name}.png")
    elif EACH_PLANET_RE.search(raw):
        for name, scene in PLANET_SCENES:
            add(scene, f"{name}.png")

    return items


def plan_image_redo(text: str, site: str = "") -> list[dict[str, str]]:
    """One PNG dest from a follow-up like 'improve the logo' or 'use flux…'."""
    raw = text or ""
    if not raw.strip():
        return []
    folder = site or site_folder(raw)
    dest_dir = images_folder(raw, folder)
    named = NAMED_PNG_RE.search(raw)
    if named and named.group(1).lower() not in {"image.png", "picture.png"}:
        filename = named.group(1)
        if not filename.lower().endswith(".png"):
            filename = f"{filename}.png"
    elif LOGO_SLOT.search(raw):
        filename = "logo.png"
    elif HERO_SLOT.search(raw):
        filename = "header.png"
    else:
        filename = "generated.png"
    path = f"{dest_dir}/{filename}".replace("//", "/")
    item = {
        "prompt": rewrite_comfy_prompt(raw),
        "output_path": path,
    }
    if RECTANGLE_ASK.search(raw):
        item["size"] = "1536x768"
    return [item]


def format_mixed_image_plan(
    items: list[dict[str, str]],
    asked_for_svg: bool = False,
    has_generate_image: bool = False,
) -> str:
    """Dest list for the coding model after the server has queued the PNGs."""
    if not items:
        return ""
    payload = [{"prompt": row["prompt"], "output_path": row["output_path"]} for row in items]
    lines = [
        f"{MIXED_PLAN_MARK} ({len(items)} PNG files). "
        "Write HTML/CSS/JS under the site folder; do not switch the project to React/Vite. "
        "Create raster PNG files, not .svg, CSS planet art, or Pillow/PIL drawings.",
        "Do not write generate_images.py. Do not convert SVG to PNG. "
        "Do not overwrite a GPU PNG with a local drawing.",
        "Do not use generate_image. The server already queued this batch.",
        "Write the page after those files exist on disk.",
    ]
    if not asked_for_svg:
        paths = ", ".join(row["output_path"] for row in items)
        lines.append(
            f"Point every img src at these exact paths (include the images/ folder): {paths}"
        )
    lines.append(json.dumps({"images": payload}, ensure_ascii=False))
    return "\n".join(lines)


def mixed_image_plan_text(
    text: str, *, has_generate_image: bool = False
) -> str:
    items = plan_mixed_images(text)
    if not items:
        return ""
    return format_mixed_image_plan(
        items,
        asked_for_svg=user_asked_for_svg(text),
        has_generate_image=has_generate_image,
    )
