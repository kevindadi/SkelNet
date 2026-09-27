"""Channel and model registry for multi-model experiments.

One place that answers: *which model, over which transport, with which key,
and is it actually available?* The registry is data, not policy: it records
discovered model IDs and explicit blocked reasons; it never silently falls
back, substitutes a model, or routes through ``auto``.

Transports:

- ``direct-api`` — the provider's own OpenAI-compatible endpoint (DeepSeek,
  DashScope/Qwen). Never routed through Cursor or OpenCode.
- ``cursor`` — Cursor agent sessions only (Composer). Requires ``cursor_sdk``.
- ``opencode`` — the OpenCode Go gateway, used for the remaining models.

Discovered IDs come from a live ``models.list`` probe, not from the display
name. A display name is never assumed to be a valid API ID.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class TransportError(RuntimeError):
    """Base class for transport/identity control errors."""


class ModelIdentityError(TransportError):
    """The response model is not the requested model; the result must not be
    attributed to the requested model."""


@dataclass(frozen=True)
class Channel:
    name: str
    transport: str          # direct-api | cursor | opencode
    provider: str
    api_key_env: str
    base_url: str | None = None
    surface: str = "chat"   # chat | responses | cursor-sdk
    notes: str = ""


@dataclass(frozen=True)
class ModelSpec:
    display_name: str
    provider: str
    channel: str
    model_id: str | None
    role: str = "compare"   # main | compare | diagnostic
    surface: str = "chat"   # chat | responses
    aliases: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()  # discovered alternatives (unresolved ID)
    status: str = "available"        # available | blocked | unknown
    blocked_reason: str | None = None
    discovered: bool = False         # model_id observed in a live model list


# Channels are keyed by name; the API key env var is a *name* only. The value
# is read at runtime and never stored, printed, or written to an artifact.
CHANNELS: dict[str, Channel] = {
    "deepseek-direct": Channel(
        name="deepseek-direct", transport="direct-api", provider="deepseek",
        api_key_env="DEEPSEEK_API_KEY", base_url="https://api.deepseek.com",
        surface="chat"),
    "dashscope-direct": Channel(
        name="dashscope-direct", transport="direct-api", provider="qwen",
        api_key_env="DASHSCOPE_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        surface="responses"),
    "cursor": Channel(
        name="cursor", transport="cursor", provider="cursor",
        api_key_env="CURSOR_API_KEY", surface="cursor-sdk",
        notes="Cursor agent sessions only; Composer only."),
    "opencode-go": Channel(
        name="opencode-go", transport="opencode", provider="opencode",
        api_key_env="OPENCODE_API_KEY",
        base_url="https://opencode.ai/zen/go/v1", surface="chat"),
}


# Discovered on 2026-09-26 via a live models.list probe (see the manifest for
# the raw list). DeepSeek direct exposed ``deepseek-flash`` and
# ``deepseek-v4-pro``; OpenCode Go exposed 35 IDs including the ones below.
DISCOVERED_MODELS: dict[str, list[str]] = {
    "deepseek-direct": ["deepseek-flash", "deepseek-v4-pro"],
    "opencode-go": [
        "deepseek-v4-flash", "deepseek-v4.1-flash", "deepseek-v4-pro",
        "glm-5.1", "glm-5.2", "glm-5.3", "glm-5.3-flash",
        "grok-4.6", "grok-4.7",
        "gpt-5.6-luna", "gpt-6-luna",
        "kimi-k2.6", "kimi-k2.7-code", "kimi-k3",
        "mimo-v2.5", "mimo-v2.5-pro", "mimo-v2.6-flash", "mimo-v2.6-pro",
        "minimax-m2.5", "minimax-m2.7", "minimax-m3",
        "qwen3.6-plus", "qwen3.7-max", "qwen3.7-plus",
        "qwen3.8-flash", "qwen3.8-max",
        "longcat-2.0", "hy3", "hy4-preview", "omen-alpha",
        "muse-spark-1.2-contributor", "muse-spark-1.3-contributor",
        "space-bunny-free", "deepseek-v4-flash-vision-exp",
    ],
    "dashscope-direct": ["qwen3.8-flash", "qwen3.8-max", "qwen3.7-flash",
                         "qwen3.8-27b", "qwen3.8-omni-flash"],
    "cursor": ["composer-2.5", "gpt-5.6-sol-high", "claude-opus-5-thinking-high",
               "cursor-grok-4.5-high", "gemini-3.1-pro"],
}


def build_registry() -> list[ModelSpec]:
    """Return the protocol model registry with discovered IDs and blockers.

    Blocked entries are recorded, not hidden; the run continues with the
    remaining models.
    """

    specs = [
        ModelSpec("DeepSeek Flash", "deepseek", "deepseek-direct",
                  "deepseek-flash", role="main",
                  discovered="deepseek-flash" in DISCOVERED_MODELS["deepseek-direct"]),
        ModelSpec("Qwen", "qwen", "dashscope-direct", "qwen3.8-flash",
                  role="compare",
                  candidates=("qwen3.8-flash", "qwen3.8-max", "qwen3.7-flash"),
                  discovered="qwen3.8-flash" in DISCOVERED_MODELS["dashscope-direct"]),
        ModelSpec("Composer 2.5", "cursor", "cursor", "composer-2.5",
                  role="diagnostic", status="blocked",
                  blocked_reason="Cursor agent accumulates large, partly "
                                 "unobservable context (150-180k input "
                                 "tokens/call) and cannot be reduced to a "
                                 "stateless chat call; not comparable to direct APIs",
                  discovered="composer-2.5" in DISCOVERED_MODELS["cursor"]),
        ModelSpec("Kimi", "moonshot", "opencode-go", "kimi-k3", role="compare",
                  aliases=("kimi-k2.7-code",),
                  discovered="kimi-k3" in DISCOVERED_MODELS["opencode-go"]),
        ModelSpec("GLM", "zhipu", "opencode-go", "glm-5.3-flash", role="compare",
                  aliases=("glm-5.3",),
                  discovered="glm-5.3-flash" in DISCOVERED_MODELS["opencode-go"]),
        ModelSpec("GPT 6 Luna", "openai", "opencode-go", "gpt-6-luna",
                  role="compare", surface="responses",
                  discovered="gpt-6-luna" in DISCOVERED_MODELS["opencode-go"]),
        ModelSpec("Grok 4.7", "xai", "opencode-go", "grok-4.7", role="compare",
                  surface="responses",
                  discovered="grok-4.7" in DISCOVERED_MODELS["opencode-go"]),
        ModelSpec("Mimo", "xiaomi", "opencode-go", "mimo-v2.5", role="compare",
                  discovered="mimo-v2.5" in DISCOVERED_MODELS["opencode-go"]),
    ]
    return specs


def available_models(specs: list[ModelSpec] | None = None) -> list[ModelSpec]:
    specs = specs or build_registry()
    return [s for s in specs if s.status == "available" and s.model_id]


def blocked_models(specs: list[ModelSpec] | None = None) -> list[ModelSpec]:
    specs = specs or build_registry()
    return [s for s in specs if s.status == "blocked"]


def resolve_model(specs: list[ModelSpec], display_or_id: str) -> ModelSpec:
    for s in specs:
        if display_or_id in (s.display_name, s.model_id) or display_or_id in s.aliases:
            return s
    raise KeyError(f"unknown model {display_or_id!r}; not in the registry")


def verify_identity(requested: str, returned: str | None) -> bool:
    """Return whether the response is the requested model.

    ``None`` (provider did not report a model) is treated as *unconfirmed*, not
    as a match. A mismatch raises :class:`ModelIdentityError` so the result is
    never attributed to the requested model.
    """

    if returned is None:
        return False
    if returned != requested:
        raise ModelIdentityError(
            f"response model {returned!r} is not the requested {requested!r}; "
            "results must not be attributed to the requested model")
    return True
