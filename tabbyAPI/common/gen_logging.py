"""
Functions for logging generation events.
"""

from common.logger import xlogger
from typing import Optional

from common.tabby_config import config


def broadcast_status():
    """Broadcasts the current logging status"""
    enabled = []
    if config.logging.log_prompt:
        enabled.append("prompts")

    if getattr(config.logging, "log_image_prompts", True):
        enabled.append("image translator prompts")

    if config.logging.log_generation_params:
        enabled.append("generation params")

    if len(enabled) > 0:
        xlogger.info("Generation logging is enabled for: " + ", ".join(enabled))
    else:
        xlogger.info("Generation logging is disabled")


def tokenizer_bos_id(tokenizer) -> Optional[int]:
    """BOS id, or None if the LLM was already unloaded."""
    if tokenizer is None:
        return None
    return getattr(tokenizer, "bos_token_id", None)


def log_generation_params(**kwargs):
    """Logs generation parameters to console."""
    if config.logging.log_generation_params:
        xlogger.info("Generation options:", kwargs, details=f"{kwargs}\n")


def image_prompt_logging_on() -> bool:
    """True unless logging.log_image_prompts is explicitly false."""
    try:
        value = getattr(config.logging, "log_image_prompts", None)
    except Exception:
        return True
    if value is None:
        return True
    return bool(value)


def _item_dest_and_prompt(item) -> tuple[str, str]:
    if isinstance(item, dict):
        dest = str(item.get("output_path") or item.get("filename") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        return dest, prompt
    dest = str(getattr(item, "output_path", "") or "").strip()
    prompt = str(getattr(item, "prompt", "") or "").strip()
    return dest, prompt


def log_image_translator(
    action: str,
    items=None,
    *,
    source: str = "",
    user_text: str = "",
):
    """Print dest prompts the classifier/rewrite handed to Comfy."""
    if not image_prompt_logging_on():
        return
    rows = list(items or [])
    where = f" ({source})" if source else ""
    header = (
        f"Image translator{where}: action={action or 'unknown'}, "
        f"{len(rows)} dest(s)"
    )
    lines = []
    snippet = (user_text or "").strip().replace("\n", " ")
    if snippet:
        lines.append(f"  user: {snippet[:300]}")
    dests = []
    for item in rows:
        dest, prompt = _item_dest_and_prompt(item)
        dests.append({"output_path": dest, "prompt": prompt})
        lines.append(f"  {dest or '(no dest)'}")
        lines.append(f"    {prompt or '(empty prompt)'}")
    xlogger.info(
        header,
        {"action": action, "source": source, "dests": dests},
        details=("\n" + "\n".join(lines) + "\n") if lines else None,
    )


def log_prompt(prompt: str, request_id: str, negative_prompt: Optional[str] = None):
    """Logs the prompt to console."""
    if config.logging.log_prompt:
        xlogger.info(
            f"Raw prompt (ID: {request_id}):",
            {"prompt": prompt},
            details=f"\n{prompt if prompt else 'Empty'}\n",
        )

        if negative_prompt:
            xlogger.info(
                "Negative Prompt:",
                {"negative_prompt": negative_prompt},
                details=f"\n{negative_prompt}\n",
            )


def log_response(request_id: str, response: str):
    """Logs the response to console."""
    if config.logging.log_prompt:
        xlogger.info(
            f"Response (ID: {request_id}):",
            {"response": response},
            details=f"\n{response if response else 'Empty'}\n",
        )


def log_metrics(
    request_id: str,
    metrics: dict,
    context_len: Optional[int],
    max_seq_len: int,
):
    initial_response = (
        f"Metrics (ID: {request_id}): {metrics.get('gen_tokens')} "
        f"tokens generated in {metrics.get('total_time')} seconds"
    )
    itemization = []
    extra_parts = []

    itemization.append(f"Queue: {metrics.get('queue_time')} s")

    cached_tokens = metrics.get("cached_tokens")
    prompt_tokens = metrics.get("prompt_tokens")

    itemization.append(
        f"Process: {cached_tokens} cached tokens and "
        f"{prompt_tokens - cached_tokens} new tokens at "
        f"{metrics.get('prompt_tokens_per_sec')} T/s"
    )

    itemization.append(f"Generate: {metrics.get('gen_tokens_per_sec')} T/s")

    # Add context (original token count)
    if context_len:
        itemization.append(f"Context: {context_len} tokens")

        if context_len > max_seq_len:
            extra_parts.append("<-- Not accurate (truncated)")

    # Add draft metrics
    if "draft_accept" in metrics:
        accept = metrics.get("draft_accept", 0)
        reject = metrics.get("draft_reject", 0)
        total_draft = accept + reject
        accept_rate = accept / total_draft if total_draft > 0 else 0.0
        itemization.append(
            f"Draft: {accept} / {total_draft} tokens accepted ({accept_rate * 100:.2f}%)"
        )

    # Print output
    xlogger.info(
        initial_response,
        {
            "new_tokens": prompt_tokens - cached_tokens,
            "cached_tokens": cached_tokens,
            "prompt_tokens": prompt_tokens,
            "prompt_tokens_per_second": metrics.get("prompt_tokens_per_sec"),
            "gen_tokens_per_second": metrics.get("gen_tokens_per_sec"),
            "context_len": context_len,
            "max_seq_len": max_seq_len,
        },
        details="(" + ", ".join(itemization) + ") " + " ".join(extra_parts),
    )
