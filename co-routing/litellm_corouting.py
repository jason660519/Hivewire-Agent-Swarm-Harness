"""A2 — bind a model tier's egress to the same proxy pool web_fetch uses.

This makes "co-routing" literal: the *model call itself* (not just browsing)
goes out through a chosen region's IPs, bound to a model tier.

CORRECTION (verified against LiteLLM docs, June 2026 — design.md §A2 assumed
otherwise): LiteLLM has NO per-deployment HTTP-proxy field in litellm_params.
Proxy binding is process-global, via either HTTP(S)_PROXY env vars or the
global ``litellm.aclient_session`` / ``litellm.client_session`` httpx client
(refs: docs.litellm.ai/docs/guides/security_settings,
docs.litellm.ai/docs/completion/http_handler_config, BerriAI/litellm#6538).
Per-call ``client=`` is inconsistent across providers, so it isn't used here.

Consequence: one model tier -> one region's egress is bound PER PROCESS. For
concurrent multi-region routing, run one router/process per region. The
``model_list`` builder is still per-tier so a single router can serve several
tiers — they just share whatever egress is globally bound.

Dependency split: building the model_list and the egress client needs only
httpx (a core dep), so config can be generated and unit-tested without litellm.
Only ``bind_global_egress`` imports litellm (install: ``uv sync --extra litellm``).
"""
from __future__ import annotations

import httpx
from pydantic import BaseModel

from server import PoolConfig, RouteProfile, _session_id_for, resolve_proxy_url


class TierBinding(BaseModel):
    """One model tier wired to a model id and an egress pool."""

    model_tier: str  # "smart" | "cheap" | ...
    model: str  # litellm model id, e.g. "anthropic/claude-opus-4-8"
    egress_pool: str  # pool name whose proxy this tier's model calls go through


def build_model_list(bindings: list[TierBinding]) -> list[dict]:
    """A LiteLLM Router ``model_list``: each tier becomes a ``model_name``.

    The egress binding is applied separately (process-global, see module
    docstring) — it can't be expressed inside ``litellm_params``.
    """
    return [
        {"model_name": b.model_tier, "litellm_params": {"model": b.model}}
        for b in bindings
    ]


def egress_async_client(proxy_url: str | None) -> httpx.AsyncClient:
    """An httpx.AsyncClient routing all traffic through ``proxy_url`` via httpx
    mounts, or a direct client when ``proxy_url`` is None (mock pool)."""
    if proxy_url is None:
        return httpx.AsyncClient()
    transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
    return httpx.AsyncClient(mounts={"all://": transport})


def build_egress_client(pool: PoolConfig, route: RouteProfile) -> httpx.AsyncClient:
    """Resolve ``route`` against ``pool`` (region + session_policy) and return an
    httpx client bound to the resulting proxy — the same resolution web_fetch
    uses, so the model call and the browse call egress identically."""
    session_id = _session_id_for(route.egress_pool, route.region, route.session_policy)
    proxy_url = resolve_proxy_url(pool, route, session_id)
    return egress_async_client(proxy_url)


def bind_global_egress(client: httpx.AsyncClient) -> None:
    """Bind ``client`` as LiteLLM's process-global async session, so every
    ``litellm.acompletion`` egresses through it. Per-process, not per-deployment
    (module docstring). Requires litellm: ``uv sync --extra litellm``."""
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "litellm not installed; install with: uv sync --extra litellm"
        ) from exc
    litellm.aclient_session = client
