"""Rewrite agent image prompts before they hit Comfy.

The coding model often sends "website hero banner" or "header for the site".
Flux/Qwen-Image then paint a finished webpage. This module keeps logos and
real text on Qwen-Image, and turns hero/header photos into Flux scenes.

It also turns a mixed coding+images chat line into a concrete PNG job list
so VS Code/Cursor cannot substitute SVG or CSS art unless the user asked.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections import OrderedDict

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
# Flux/Qwen paint a Photoshop checkerboard if the prompt says "transparent".
# Strip that word. Do not punch alpha; PNGs stay opaque.
CHROMA_HEX = "#FF00FF"
CHROMA_TAIL = (
    "solid even white background, even lighting, no floor, no wall"
)
CUTOUT_TAIL = (
    "solid even white background, subject fully inside the frame, "
    "even lighting, no floor, no wall, no gradient"
)
TRANSPARENT_RE = re.compile(r"(?is)\btransparent\b")
TRANSPARENT_PHRASE_RE = re.compile(
    r"(?is)\btransparent(?:\s+pngs?)?(?:\s+(?:files?|images?|background))?\b"
)
CHECKER_WORD_RE = re.compile(r"(?is)\bcheckerboards?\b|\bcheckered\b")
# A mixed coding+images chat line mentions "logo" but is still a site spec.
# Qwen-Image then paints a finished webpage. Collapse those to a short mark.
PAGE_SPEC_RE = re.compile(
    r"(?is)\b("
    r"single[- ]page(?:\s+application)?|production[- ]ready|"
    r"pillow|\bpil\b|html5|css3|\breact\b|\bvue\b|"
    r"contact form|booking system|pricing tiers?|"
    r"deliverables?|technical requirements?|"
    r"python script|generate_images|"
    r"content structure|visual design|"
    r"complete html|package section"
    r")\b"
)
PAGE_SPEC_MAX_LOGO_CHARS = 400

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
LLM_PLAN_TIMEOUT_S = 25
MIXED_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "images": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "subject": {"type": "string"},
                },
                "required": ["filename", "subject"],
            },
        }
    },
    "required": ["images"],
}
EXTRACT_PLAN_SYSTEM = (
    "List every raster PNG the webpage needs. JSON only, no markdown. "
    "Include a logo if they asked for a logo. Include a header if they asked "
    "for a hero/header/banner image. Include one file per named picture "
    "subject (products, places, people, planets, cabins, food, anything they "
    "named). Do not invent a whole category — 'each planet' with no names is "
    "not eight planets. Skip CSS, HTML, JavaScript, React, Vue, pricing "
    "tiers, and etc. filename is a basename like logo.png or oak.png. "
    "subject is a short photo or logo prompt with no website mockup."
)
_PLAN_CACHE: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
_PLAN_CACHE_MAX = 24
# Specs often say "create them using Python with PIL/Pillow". The 9B obeys
# that line and never waits for Comfy. Replace it before the coding model sees
# the user query.
PILLOW_ORDER_RE = re.compile(
    r"(?is)"
    r"(?:create|generate|make|draw)\s+them\s+using\s+python(?:3)?\s+with\s+"
    r"pil(?:low)?"
    r"|using\s+python(?:3)?\s+with\s+pil(?:low)?"
    r"|python(?:3)?\s+(?:drawing\s+)?script\s+to\s+generate"
    r"|python(?:3)?\s+(?:drawing\s+)?script.{0,80}"
    r"(?:pil(?:low)?|generate_images)"
    r"|generate_images\.py"
    r"|(?:from\s+PIL\s+import|import\s+PIL\b)"
)
GPU_PNG_NOTE = (
    "PNG files are generated on the GPU (not with Python, Pillow, or "
    "generate_images.py)"
)
IMAGE_OF_RE = re.compile(
    r"(?is)\b(?:generated\s+)?"
    r"(?:(?:transparent\s+)?png\s+images?|(?:transparent\s+)?pngs?|"
    r"images?|pictures?|photos?|pics?)\s+of\s+"
    r"(?!each\b|every\b|your\s+choice\b|that\s+\w+\b)"
    r"([^\n.;(]{1,80})"
)
# Named things in parentheses: (Oak, Pine, Lake) or (Mars, Jupiter, Saturn).
PAREN_NAME_LIST_RE = re.compile(r"\(([^)]{3,200})\)")
# Skip paren lists that are tech/pricing, not picture subjects.
_NOT_SUBJECT_LIST = re.compile(
    r"(?is)\b("
    r"pricing|tiers?|html5?|css3?|javascript|react|vue|"
    r"deliverables?|requirements?|technical|stack"
    r")\b"
)
_SUBJECT_ARTICLES = re.compile(r"(?is)^(an?|the)\s+")
_SUBJECT_TRAIL = re.compile(
    r"(?is)\s+\b(?:for the|on the|to use|that will|which will|etc|"
    r"under the|into the|inside the|put files)\b.*$"
)
_SKIP_SUBJECTS = frozenset(
    {
        "choice",
        "your choice",
        "it",
        "them",
        "those",
        "these",
        "this",
        "that",
        "logo",
        "header",
        "banner",
        "icon",
        "icons",
        "favicon",
        "the logo",
        "the header",
        "each",
        "every",
        "other",
        "some",
        "page",
        "site",
        "website",
        "planet",
        "planets",
        "etc",
        "png",
        "pngs",
        "file",
        "files",
    }
)
# API URL paths that look like site/images dirs (".../openai/v1/images/generated-...").
_API_IMAGES_DIRS = frozenset({"v1/images", "openai/v1/images", "api/images"})
_RESERVED_SITE_FOLDERS = frozenset(
    {
        "v1",
        "openai",
        "api",
        "http",
        "https",
        "www",
        "localhost",
        "images",
        "image",
        "img",
        "the",
        "a",
        "an",
    }
)


def _collapse(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "")
    text = re.sub(r"(?:,\s*){2,}", ", ", text)
    return text.strip(" ,.;:-")


def _already_cutout(text: str) -> bool:
    return CUTOUT_TAIL in (text or "") or CHROMA_TAIL in (text or "")


def wants_transparent(text: str) -> bool:
    """Always false. Cutouts looked bad; PNGs stay opaque RGB from Comfy."""
    return False


def _strip_transparent_words(text: str) -> str:
    cleaned = TRANSPARENT_PHRASE_RE.sub(" ", text or "")
    # Do not eat "no checkerboard" inside a cutout/chroma tail on a rewrite.
    if (
        CUTOUT_TAIL not in cleaned
        and CHROMA_TAIL not in cleaned
        and CHROMA_HEX.lower() not in cleaned.lower()
    ):
        cleaned = CHECKER_WORD_RE.sub(" ", cleaned)
    return _collapse(cleaned)


def _logo_tail(*, chroma: bool) -> str:
    if not chroma:
        return LOGO_TAIL
    return LOGO_TAIL.replace("simple background", CUTOUT_TAIL)


def _with_logo_tail(cleaned: str, *, chroma: bool) -> str:
    if "isolated logo mark only" in cleaned:
        return cleaned
    tail = _logo_tail(chroma=chroma)
    if chroma and _already_cutout(cleaned):
        tail = LOGO_TAIL.replace(", simple background", "")
    return f"{cleaned}, {tail}"


def _with_chroma(text: str, *, chroma: bool) -> str:
    cleaned = _strip_transparent_words(text)
    if not chroma:
        return cleaned
    if _already_cutout(cleaned) or CHROMA_HEX.lower() in cleaned.lower():
        return cleaned
    return f"{cleaned}, {CUTOUT_TAIL}" if cleaned else CUTOUT_TAIL


def _strip_noise(body: str) -> str:
    cleaned = WEBSITE_NOISE.sub(" ", body)
    cleaned = UI_SHOT.sub(" ", cleaned)
    cleaned = VECTOR_NOISE.sub(" ", cleaned)
    return _collapse(cleaned)


def _strip_vector_noise(body: str) -> str:
    return _collapse(VECTOR_NOISE.sub(" ", body))


def neutralize_local_image_script(text: str) -> str:
    """Drop PIL/Pillow orders so the 9B cannot treat them as the image path."""
    raw = text or ""
    if not PILLOW_ORDER_RE.search(raw):
        return raw
    return PILLOW_ORDER_RE.sub(GPU_PNG_NOTE, raw)


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
    for match in FOLDER_RE.finditer(text or ""):
        name = _quoted_or_group(match).rstrip(".,;:")
        if name and name.lower() not in _RESERVED_SITE_FOLDERS:
            return name
    return ""


def images_folder(text: str, folder: str = "") -> str:
    for match in IMAGES_DIR_RE.finditer(text or ""):
        rel = match.group(1).replace("\\", "/").strip("/")
        parent = (rel.split("/")[0] or "").lower()
        if rel.lower() in _API_IMAGES_DIRS or parent in _RESERVED_SITE_FOLDERS:
            continue
        return rel
    if folder and folder.lower() not in _RESERVED_SITE_FOLDERS:
        return f"{folder}/images"
    return "images"


def company_name(text: str) -> str:
    match = COMPANY_RE.search(text or "")
    if not match:
        return ""
    return _quoted_or_group(match).rstrip(".,;:")


def _subject_slug(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    if not words:
        return ""
    return "-".join(words)[:40].strip("-")


def _clean_subject(item: str) -> str:
    text = _SUBJECT_TRAIL.sub("", item or "")
    text = _collapse(_SUBJECT_ARTICLES.sub("", text))
    text = re.sub(r"(?is)^planet\s+", "", text).strip(" ,;:-")
    return text


def _list_parts(blob: str) -> list[str]:
    blob = re.split(r"\s+[-–—]\s+", blob or "", maxsplit=1)[0]
    return [part.strip() for part in re.split(r"\s*(?:,|&|\band\b)\s*", blob) if part.strip()]


def listed_image_subjects(text: str) -> list[str]:
    """Names the user wrote as picture subjects — any domain, no category tables.

    Two sources only:
    - "images of A, B, and C"
    - a parenthetical name list with 2+ items, unless that list sits next to
      pricing/tech wording
    """
    raw = text or ""
    found: list[str] = []
    seen: set[str] = set()
    brand = (company_name(raw) or "").lower()

    def accept(name: str) -> str:
        cleaned = _clean_subject(name)
        if not cleaned or len(cleaned) > 48:
            return ""
        key = cleaned.lower()
        if key in _SKIP_SUBJECTS or key in seen or key == brand:
            return ""
        slug = _subject_slug(cleaned)
        if not slug or slug in {"logo", "header", "banner", "generated"}:
            return ""
        if slug in seen:
            return ""
        return cleaned

    def take(name: str) -> None:
        cleaned = accept(name)
        if not cleaned:
            return
        seen.add(cleaned.lower())
        seen.add(_subject_slug(cleaned))
        found.append(cleaned)

    for match in IMAGE_OF_RE.finditer(raw):
        # "photos of the cabins (Oak, Pine, Lake)" — names are in the parens.
        if (raw[match.end() : match.end() + 1] or "").startswith("("):
            continue
        for part in _list_parts(match.group(1) or ""):
            take(part)
    for match in PAREN_NAME_LIST_RE.finditer(raw):
        start = max(0, match.start() - 48)
        if _NOT_SUBJECT_LIST.search(raw[start : match.end()]):
            continue
        candidates = [accept(part) for part in _list_parts(match.group(1) or "")]
        names = [name for name in candidates if name]
        if len(names) < 2:
            continue
        for name in names:
            take(name)
    return found


def _subject_prompt(name: str, *, chroma: bool) -> str:
    key = (name or "").strip().lower()
    if key in PLANET_NAMES:
        return _planet_chroma(key) if chroma else _planet_scene(key)
    body = f"photograph of {name.strip()}, isolated object"
    return _with_chroma(body, chroma=chroma)


def _planet_title(name: str) -> str:
    key = (name or "").strip().lower()
    for planet, _scene in PLANET_SCENES:
        if planet == key:
            return planet.title()
    return (name or "a planet").strip() or "a planet"


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


def _planet_chroma(name: str) -> str:
    titled = _planet_title(name)
    return (
        f"photograph of planet {titled} as an isolated sphere, {CUTOUT_TAIL}"
    )


def _is_page_spec(body: str) -> bool:
    raw = body or ""
    if PAGE_SPEC_RE.search(raw):
        return True
    return len(_strip_noise(raw)) > PAGE_SPEC_MAX_LOGO_CHARS


def _isolated_logo_prompt(raw: str, body: str) -> str:
    """Short Qwen mark. Drop leftover HTML/SPA instructions."""
    brand = company_name(raw)
    if _is_page_spec(body):
        if brand:
            return f"logo that says {brand}, clean brand mark, readable letters"
        return "elegant brand logo, clean readable letters"
    cleaned = _strip_transparent_words(_strip_noise(body))
    if not cleaned:
        cleaned = "elegant brand logo"
    return cleaned


def rewrite_comfy_prompt(prompt: str) -> str:
    """Return the prompt Comfy should actually render."""
    original = (prompt or "").strip()
    raw = original
    if not raw:
        return raw
    if _already_cutout(raw) and not LOGO_SLOT.search(raw):
        return raw
    if _already_cutout(raw) and (
        "isolated logo mark only" in raw or "isolated sphere" in raw
    ):
        return raw
    if LOGO_TAIL in raw or "isolated logo mark only" in raw:
        return raw
    if SCENE_TAIL in raw and not QWEN_PREFIX.match(raw):
        return raw

    chroma = wants_transparent(original)
    flux_prefixed = FLUX_PREFIX.match(raw)
    if flux_prefixed:
        body = _collapse((flux_prefixed.group(1) or "").strip())
        body = _with_chroma(body, chroma=chroma)
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
        cleaned = _strip_transparent_words(_collapse(cleaned))
        if len(cleaned) < 8:
            cleaned = "wide atmospheric photograph, rich color, cinematic lighting"
        return f"{cleaned}, {SCENE_TAIL}"

    if (
        planet
        and not is_logo
        and not wants_text
        and not explicit_ui
    ):
        if chroma:
            return _planet_chroma(planet.group(1))
        return _planet_scene(planet.group(1))

    if UI_SHOT.search(body) and not is_logo and not wants_text and not explicit_ui:
        cleaned = _strip_noise(body)
        if len(cleaned) < 8:
            cleaned = "wide atmospheric photograph, rich color, cinematic lighting"
        return f"{cleaned}, {SCENE_TAIL}"

    if is_logo:
        cleaned = _isolated_logo_prompt(original, body)
        cleaned = _with_logo_tail(cleaned, chroma=chroma)
        if wants_flux:
            return f"flux: {cleaned}"
        if cleaned.lower().startswith("qwen-image"):
            return cleaned
        return f"qwen-image: {cleaned}"

    if prefixed or explicit_ui:
        cleaned = _strip_vector_noise(body)
        result = original if prefixed else f"qwen-image: {cleaned}"
        return _with_chroma(result, chroma=chroma)

    if WEBSITE_NOISE.search(body):
        cleaned = _strip_noise(body)
        if not cleaned:
            return _with_chroma(original, chroma=chroma)
        if wants_text:
            return _with_chroma(cleaned, chroma=chroma)
        return _with_chroma(
            f"{cleaned}, no text, no user interface, no website mockup",
            chroma=chroma,
        )

    return _with_chroma(original, chroma=chroma)


def _spec_key(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode()).hexdigest()


def remember_mixed_plan(text: str, items: list[dict[str, str]]) -> None:
    key = _spec_key(text)
    if key in _PLAN_CACHE:
        _PLAN_CACHE.move_to_end(key)
    _PLAN_CACHE[key] = [dict(row) for row in items]
    while len(_PLAN_CACHE) > _PLAN_CACHE_MAX:
        _PLAN_CACHE.popitem(last=False)


def recalled_mixed_plan(text: str) -> list[dict[str, str]]:
    key = _spec_key(text)
    items = _PLAN_CACHE.get(key)
    if not items:
        return []
    _PLAN_CACHE.move_to_end(key)
    return [dict(row) for row in items]


def parse_mixed_plan_json(raw: str) -> list[dict[str, str]]:
    """Pull {filename, subject} rows from a model JSON reply."""
    text = re.sub(r"(?is)<think>.*?</think>", " ", raw or "")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    blob = fenced.group(1) if fenced else ""
    if not blob:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            blob = text[start : end + 1]
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    rows = data.get("images") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    found: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        filename = str(row.get("filename") or row.get("output_path") or "").strip()
        subject = str(row.get("subject") or row.get("prompt") or "").strip()
        if filename or subject:
            found.append({"filename": filename, "subject": subject})
    return found


def plan_from_extracted(text: str, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Turn extracted filename/subject rows into Comfy dests for this spec."""
    raw = text or ""
    dest_dir = images_folder(raw, site_folder(raw))
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows or []:
        if len(items) >= MAX_PLANNED_IMAGES:
            break
        filename = str(row.get("filename") or "").replace("\\", "/")
        filename = filename.split("/")[-1].strip()
        slug = _subject_slug(filename.rsplit(".", 1)[0] if filename else "")
        if not slug:
            slug = _subject_slug(str(row.get("subject") or ""))
        if not slug or slug in seen:
            continue
        if slug in {"etc", "css", "css3", "html", "html5"}:
            continue
        name = "logo.png" if slug == "logo" else f"{slug}.png"
        if slug == "header" or slug == "banner":
            name = "header.png"
        subject = str(row.get("subject") or slug).strip() or slug
        seen.add(slug)
        items.append(
            {
                "prompt": rewrite_comfy_prompt(subject),
                "output_path": f"{dest_dir}/{name}".replace("//", "/"),
            }
        )
    return items


async def llm_plan_mixed_images(text: str) -> list[dict[str, str]]:
    """Ask the loaded coding model for dests. Empty if it cannot run."""
    raw = (text or "").strip()
    if not raw:
        return []
    try:
        from common import model as model_mod
        from endpoints.OAI.types.chat_completion import (
            ChatCompletionMessage,
            ChatCompletionRequest,
        )
        from endpoints.OAI.utils.chat_completion import apply_chat_template
    except Exception:
        return []
    container = getattr(model_mod, "container", None)
    if not container or not getattr(container, "loaded", False):
        return []
    if getattr(container, "prompt_template", None) is None:
        return []
    request = ChatCompletionRequest(
        messages=[
            ChatCompletionMessage(role="system", content=EXTRACT_PLAN_SYSTEM),
            ChatCompletionMessage(role="user", content=raw[:6000]),
        ],
        max_tokens=500,
        temperature=0.1,
        json_schema=MIXED_PLAN_SCHEMA,
    )
    try:
        prompt, embeddings = await apply_chat_template(request)
        result = await asyncio.wait_for(
            container.generate(
                f"mixed-plan-{uuid.uuid4().hex[:12]}",
                prompt,
                request,
                mm_embeddings=embeddings,
            ),
            timeout=LLM_PLAN_TIMEOUT_S,
        )
    except Exception as exc:
        from common.logger import xlogger

        xlogger.warning(f"Mixed dest extract failed: {exc}")
        return []
    blob = ""
    if isinstance(result, dict):
        blob = str(result.get("text") or result.get("content") or "")
    return plan_from_extracted(raw, parse_mixed_plan_json(blob))


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
        if brand:
            add(
                f"logo that says {brand}, clean brand mark, readable letters",
                "logo.png",
            )
        else:
            add("elegant brand logo, clean readable letters", "logo.png")

    if HERO_IMAGE_ASK.search(raw):
        place = brand or "a vast landscape"
        add(
            f"wide cinematic photograph of {place}, atmospheric, {SCENE_TAIL}",
            "header.png",
        )

    listed = listed_image_subjects(raw)
    for name in listed:
        add(_subject_prompt(name, chroma=False), f"{_subject_slug(name)}.png")

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
        "Create raster PNG files, not .svg, CSS art, or Pillow/PIL drawings.",
        "Do not write generate_images.py, even if the spec asked for a Python "
        "image script. Do not convert SVG to PNG. Do not overwrite a GPU PNG "
        "with a local drawing. Images are opaque PNGs from Comfy, not cutouts.",
        "Do not use generate_image. The server already queued this batch.",
        "Write the page after those files exist on disk. Use only these dests; "
        "do not invent extra PNG filenames or generated-*.png URLs.",
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
    items = recalled_mixed_plan(text) or plan_mixed_images(text)
    if not items:
        return ""
    return format_mixed_image_plan(
        items,
        asked_for_svg=user_asked_for_svg(text),
        has_generate_image=has_generate_image,
    )
