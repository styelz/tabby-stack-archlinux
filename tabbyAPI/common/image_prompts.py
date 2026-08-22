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
# Flux/Qwen paint a Photoshop checkerboard if the prompt says "transparent",
# and a fixed magenta chroma-key punches holes in any mark that uses that
# color. Ask for a plain studio background; png_alpha floods it (or leftover
# chroma / dark space) to alpha.
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
    r"(?!each\b|every\b|your\s+choice\b|that\s+planet\b)"
    r"([^\n.;]{1,80})"
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
        "that planet",
        "the planet",
        "the planets",
        "each planet",
        "every planet",
        "etc",
        "css",
        "css3",
        "html",
        "html5",
        "javascript",
        "python",
        "react",
        "vue",
        "premium",
        "basic",
        "luxury",
        "png",
        "pngs",
        "file",
        "files",
        "application",
        "deliverables",
        "requirements",
    }
)
_JUNK_SUBJECT_RE = re.compile(
    r"(?is)("
    r"[*`]|html5|css3|\breact\b|\bvue\b|javascript|"
    r"pricing\s+tiers?|deliverables?|technical|"
    r"floating|twinkling|animations?"
    r")"
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
    """True when the user asked for a cutout, or the rewrite already set one.

    Full-bleed hero scenes keep their backdrop even if the user said
    "transparent" — those prompts get SCENE_TAIL, not a studio cutout.
    """
    raw = text or ""
    if SCENE_TAIL in raw and not _already_cutout(raw):
        return False
    if _already_cutout(raw):
        return True
    if CHROMA_HEX.lower() in raw.lower():
        return True
    return bool(TRANSPARENT_RE.search(raw))


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


def listed_image_subjects(text: str) -> list[str]:
    """Names the user wants as content PNGs (planets, products, anything)."""
    raw = text or ""
    found: list[str] = []
    seen: set[str] = set()

    planets = named_planets(raw)
    brand = (company_name(raw) or "").lower()

    def take(name: str) -> None:
        cleaned = _clean_subject(name)
        if not cleaned or len(cleaned) > 48:
            return
        key = cleaned.lower()
        if key in _SKIP_SUBJECTS or key in seen or key == brand:
            return
        if _JUNK_SUBJECT_RE.search(cleaned):
            return
        slug = _subject_slug(cleaned)
        if not slug or slug in {"logo", "header", "banner", "generated"}:
            return
        if slug in seen:
            return
        seen.add(key)
        seen.add(slug)
        found.append(cleaned)

    if len(planets) >= 2:
        for name in planets:
            take(name)
    elif EACH_PLANET_RE.search(raw):
        for name, _scene in PLANET_SCENES:
            take(name)
    for match in IMAGE_OF_RE.finditer(raw):
        chunk = match.group(1) or ""
        chunk = re.split(r"\s+[-–—]\s+", chunk, maxsplit=1)[0]
        parts = re.split(r"\s*(?:,|&|\band\b)\s*", chunk)
        for part in parts:
            take(part)
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
    extra = f", {CUTOUT_TAIL}" if wants_transparent(raw) else ""
    if _is_page_spec(body):
        if brand:
            return (
                f"logo that says {brand}, clean brand mark, readable letters{extra}"
            )
        return f"elegant brand logo, clean readable letters{extra}"
    cleaned = _strip_transparent_words(_strip_noise(body))
    if not cleaned:
        cleaned = "elegant brand logo"
    if extra and not _already_cutout(cleaned):
        cleaned = f"{cleaned}{extra}"
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
    want_alpha = wants_transparent(raw)
    extra = f", {CUTOUT_TAIL}" if want_alpha else ""
    if LOGO_SLOT.search(raw):
        if brand:
            add(
                f"logo that says {brand}, clean brand mark, readable letters{extra}",
                "logo.png",
            )
        else:
            add(f"elegant brand logo, clean readable letters{extra}", "logo.png")

    if HERO_IMAGE_ASK.search(raw):
        place = brand or "a vast landscape"
        add(
            f"wide cinematic photograph of {place}, atmospheric, {SCENE_TAIL}",
            "header.png",
        )

    listed = listed_image_subjects(raw)
    for name in listed:
        add(_subject_prompt(name, chroma=want_alpha), f"{_subject_slug(name)}.png")

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
        "with a local drawing. Transparency is applied on the GPU after Comfy.",
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
