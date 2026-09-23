"""SimpleAudit engine integration.

This is the ONLY place in the platform that imports the SimpleAudit engine. It is
imported lazily so the web process, tests, and the worker's import-time do not
require the engine to be installed or reachable — only an actual scenario
execution needs it.

The platform WRAPS the existing engine; it does not reimplement Target ->
Auditor -> Judge semantics. A single scenario is executed by building a
``ModelAuditor`` from the FROZEN endpoint snapshots stored on the AuditRun (never
from live registry rows) and calling ``run_scenario`` once.

Secrets are resolved at execution time from the environment using the
``secret_reference`` identifier stored on each endpoint snapshot. Raw credentials
are never persisted in the database.
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any


class EngineError(RuntimeError):
    """Raised when the SimpleAudit engine cannot be loaded or a scenario fails."""


def _ensure_engine_on_path() -> None:
    """Make the SimpleAudit package importable if it is not already installed.

    The canonical deployment installs ``simpleaudit`` into the worker image. For
    local development the engine may live in a sibling checkout; point
    ``SIMPLEAUDIT_ENGINE_PATH`` at the repo root (the directory containing the
    ``simpleaudit/`` package) to add it to ``sys.path``.
    """
    try:
        import simpleaudit  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    engine_path = os.environ.get("SIMPLEAUDIT_ENGINE_PATH", "").strip()
    if not engine_path:
        raise EngineError(
            "SimpleAudit engine is not installed and SIMPLEAUDIT_ENGINE_PATH is not set. "
            "Install the engine into the worker image or point SIMPLEAUDIT_ENGINE_PATH "
            "at the SimpleAudit repo root."
        )
    if not os.path.isdir(engine_path):
        raise EngineError(f"SIMPLEAUDIT_ENGINE_PATH does not exist: {engine_path}")
    if engine_path not in sys.path:
        sys.path.insert(0, engine_path)


def _resolve_secret(secret_reference: str | None, api_key_direct: str | None = None) -> str | None:
    """Resolve credentials: direct key takes priority, then env var reference."""
    direct = (api_key_direct or "").strip()
    if direct:
        return direct
    ref = (secret_reference or "").strip()
    if not ref:
        return None
    return os.environ.get(ref)


def _validate_secrets(*snapshots: tuple[str, dict]) -> None:
    """Fail fast with a clear EngineError if any endpoint's secret is unresolved.

    ``any_llm`` raises an opaque ``MissingApiKeyError`` at client-construction time
    when no key is present. We surface that as a clean, actionable ``EngineError``
    naming the offending role + secret reference, so the worker records a readable
    failure instead of crashing mid-construction. A snapshot without a
    ``secret_reference`` (e.g. a local server needing no auth) is allowed.
    """
    for role, snap in snapshots:
        direct = (snap.get("api_key_direct") or "").strip()
        ref = (snap.get("secret_reference") or "").strip()
        if direct:
            continue  # direct key present, no need to validate env var
        if not ref:
            continue
        if _resolve_secret(ref) is None:
            raise EngineError(
                f"Secret for {role} endpoint is not set: environment variable "
                f"'{ref}' is missing or empty. Set it in the worker environment."
            )


# Providers that any_llm does not know about are treated as OpenAI-compatible
# gateways/self-hosted servers (the common case for local models and proxies).
_KNOWN_ANYLLM_PROVIDERS = {
    "anthropic", "bedrock", "azure", "azureanthropic", "azureopenai", "cerebras",
    "cohere", "deepseek", "fireworks", "gemini", "github", "groq", "huggingface",
    "llama", "lmstudio", "llamafile", "llamacpp", "meta", "mistral", "moonshot",
    "ollama", "openai", "openrouter", "perplexity", "sambanova", "together",
    "vllm", "xai", "dashscope", "deepinfra", "minimax", "zai",
}


def _normalize_provider(provider: str | None, base_url: str | None) -> str:
    """Return an any_llm provider key.

    A recognised provider is passed through. An unrecognised label (e.g. a
    registry display name such as ``simulachat``) combined with a base URL is
    treated as an OpenAI-compatible endpoint — how self-hosted and gateway
    deployments expose their API.
    """
    p = (provider or "").strip().lower()
    if p in _KNOWN_ANYLLM_PROVIDERS:
        return p
    if base_url:
        return "openai"
    return p or "openai"


def _auditor_kwargs_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Map a frozen endpoint snapshot onto ModelAuditor constructor kwargs.

    Only the fields relevant to a given role are used; the caller picks which
    snapshot feeds target vs auditor vs judge.
    """
    params = dict(snapshot.get("default_parameters") or {})
    base_url = snapshot.get("base_url") or None
    api_key = _resolve_secret(snapshot.get("secret_reference"), snapshot.get("api_key_direct"))
    # any_llm's OpenAI-compatible client requires *some* API key even when the
    # endpoint needs no auth (self-hosted / local servers). A snapshot without a
    # secret_reference means "no auth", so supply a non-secret placeholder — the
    # same convention the engine's own preflight probe uses (api_key="probe").
    if not api_key:
        api_key = "no-auth"
    return {
        "model": snapshot.get("model_id"),
        "provider": _normalize_provider(snapshot.get("provider"), base_url),
        "base_url": base_url,
        "api_key": api_key,
        "kwargs": params or None,
    }


def build_model_auditor(*, target: dict, auditor: dict, judge: dict, generation: dict | None = None):
    """Construct a ModelAuditor from three frozen endpoint snapshots.

    Returns the configured ``ModelAuditor`` instance. Raises ``EngineError`` if
    the engine cannot be imported.
    """
    _ensure_engine_on_path()
    try:
        from simpleaudit.model_auditor import ModelAuditor
    except Exception as exc:  # noqa: BLE001 - surface any import failure uniformly
        raise EngineError(f"Failed to import SimpleAudit ModelAuditor: {exc}") from exc

    gen = dict(generation or {})
    target_cfg = _auditor_kwargs_from_snapshot(target)
    auditor_cfg = _auditor_kwargs_from_snapshot(auditor)
    judge_cfg = _auditor_kwargs_from_snapshot(judge)

    # Fail fast with a clear, actionable error if a required secret is unset,
    # rather than letting any_llm raise an opaque MissingApiKeyError below.
    _validate_secrets(
        ("target", target), ("auditor", auditor), ("judge", judge)
    )

    # Generation parameters come from the frozen audit profile snapshot.
    max_turns = int(gen.get("max_turns") or 5)
    language = gen.get("language") or "English"
    max_retries = int(gen.get("max_retries") or 2)
    retry_backoff = float(gen.get("retry_backoff") or 0.5)
    system_prompt = gen.get("system_prompt") or None
    probe_prompt = gen.get("probe_prompt") or None
    judge_prompt = gen.get("judge_prompt") or None

    # The engine forwards target/auditor/judge kwargs to the provider client
    # CONSTRUCTOR (e.g. AsyncOpenAI.__init__). Per-request generation params
    # (temperature, top_p, max_tokens, etc.) are NOT valid constructor args and
    # would crash. We use a denylist of known per-request-only params to filter
    # them out, while passing through anything else (timeout, max_retries,
    # default_headers, organization, base_url overrides, etc.).
    _CONSTRUCTOR_DENYLIST = {
        "temperature", "top_p", "max_tokens", "frequency_penalty",
        "presence_penalty", "stop", "seed", "logprobs", "top_logprobs",
        "n", "logit_bias", "user", "response_format", "tools",
        "tool_choice", "functions", "function_call",
    }

    def _role_kwargs(cfg: dict[str, Any], gen_override: dict | None = None) -> dict[str, Any] | None:
        raw = dict(cfg.get("kwargs") or {})
        if gen_override:
            raw.update(gen_override)
        filtered = {k: v for k, v in raw.items() if k not in _CONSTRUCTOR_DENYLIST}
        return filtered or None

    # Extract per-role kwargs overrides from generation config
    target_gen_kwargs = gen.get("target_kwargs") or None
    auditor_gen_kwargs = gen.get("auditor_kwargs") or None
    judge_gen_kwargs = gen.get("judge_kwargs") or None

    try:
        instance = ModelAuditor(
            model=target_cfg["model"],
            provider=target_cfg["provider"],
            base_url=target_cfg["base_url"],
            api_key=target_cfg["api_key"],
            target_kwargs=_role_kwargs(target_cfg, target_gen_kwargs),
            auditor_model=auditor_cfg["model"],
            auditor_provider=auditor_cfg["provider"],
            auditor_base_url=auditor_cfg["base_url"],
            auditor_api_key=auditor_cfg["api_key"],
            auditor_kwargs=_role_kwargs(auditor_cfg, auditor_gen_kwargs),
            judge_model=judge_cfg["model"],
            judge_provider=judge_cfg["provider"],
            judge_base_url=judge_cfg["base_url"],
            judge_api_key=judge_cfg["api_key"],
            judge_kwargs=_role_kwargs(judge_cfg, judge_gen_kwargs),
            max_turns=max_turns,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            system_prompt=system_prompt,
            probe_prompt=probe_prompt,
            judge_prompt=judge_prompt,
            show_progress=False,
            verbose=False,
        )
    except EngineError:
        raise
    except Exception as exc:  # noqa: BLE001 - any construction failure (bad base_url, provider, etc.)
        raise EngineError(f"Failed to construct ModelAuditor: {type(exc).__name__}: {exc}") from exc
    return instance, language


def run_scenario(
    *,
    name: str,
    description: str,
    expected_behavior: list[str] | None,
    test_prompt: str | None,
    target: dict,
    auditor: dict,
    judge: dict,
    generation: dict | None = None,
) -> dict[str, Any]:
    """Execute one scenario through the real engine and return a serializable result.

    Runs the async ``ModelAuditor.run_scenario`` to completion and returns
    ``AuditResult.to_dict()`` plus the language used. Raises ``EngineError`` on
    load failure; a mid-conversation/judging failure is captured by the engine
    itself as a severity of ``ERROR`` in the returned dict (not raised), matching
    the engine's own error-handling contract.
    """
    auditor_instance, language = build_model_auditor(
        target=target, auditor=auditor, judge=judge, generation=generation
    )
    try:
        result = asyncio.run(
            auditor_instance.run_scenario(
                name=name,
                description=description,
                expected_behavior=expected_behavior,
                test_prompt=test_prompt,
                language=language,
            )
        )
    except EngineError:
        raise
    except Exception as exc:  # noqa: BLE001 - unexpected engine crash
        raise EngineError(f"Scenario execution crashed: {type(exc).__name__}: {exc}") from exc

    payload = result.to_dict()
    payload["_language"] = language
    return payload
