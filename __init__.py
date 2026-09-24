"""Vultr Inference provider profile.

Hermes cannot read Vultr's /v1/models on its own: the endpoint serves OpenRouter
provider Model Documents (schema 2.4), where limits and prices are nested under
modalities, and Hermes expects flat fields. This profile reads the catalog through
vultr_model_catalog and hands Hermes what it has a place for: the model list, context
windows, output limits and reasoning efforts.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any

from agent.reasoning_effort import clamp_effort, requested_effort
from hermes_constants import get_hermes_home
from providers import register_provider
from providers.base import ProviderProfile
from vultr_model_catalog import DEFAULT_BASE_URL, Catalog, CatalogError, CatalogModel, load_catalog

logger = logging.getLogger(__name__)

API_KEY_ENV = "VULTR_INFERENCE_API_KEY"
BASE_URL_ENV = "VULTR_INFERENCE_BASE_URL"
COLD_TIMEOUT = 3.0
RETRY_SECONDS = 60.0


def _offline(url: str, headers: Any, timeout: float) -> bytes:
    raise OSError("cache only")


def is_usable(model: CatalogModel) -> bool:
    return model.is_chat and model.is_ready and model.context_window is not None


class VultrProfile(ProviderProfile):
    """Vultr Inference: OpenAI-compatible chat completions, top-level reasoning_effort."""

    def _cache_path(self) -> Path:
        return Path(get_hermes_home()) / "cache" / "vultr-model-catalog.json"

    def _load(self, *, base_url: str, timeout: float, offline: bool = False) -> Catalog | None:
        try:
            return load_catalog(
                base_url=base_url,
                timeout=timeout,
                cache_path=self._cache_path(),
                # Offline: any cached catalog is fresh enough and the network is never tried.
                max_age=float("inf") if offline else 0,
                transport=_offline if offline else None,
            )
        except CatalogError as error:
            logger.debug("vultr catalog unavailable: %s", error)
            return None

    def _remember(self, catalog: Catalog, base_url: str) -> None:
        usable = [model for model in catalog.models if is_usable(model)]
        if base_url == self.base_url:
            self._models = {model.id: model for model in usable}
        self._publish_context_windows(usable, base_url)

    def _model(self, model: str | None, *, network: bool = True) -> CatalogModel | None:
        """Called on every request. Memory first, then the disk cache. With neither, one
        network load with a short timeout; a failure is not retried for RETRY_SECONDS."""
        if getattr(self, "_models", None) is None:
            catalog = self._load(base_url=self.base_url, timeout=0, offline=True)
            if catalog is None and network and time.monotonic() >= getattr(self, "_retry_at", 0.0):
                catalog = self._load(base_url=self.base_url, timeout=COLD_TIMEOUT)
                self._retry_at = time.monotonic() + RETRY_SECONDS
            if catalog is None:
                return None
            self._remember(catalog, self.base_url)
        return self._models.get((model or "").strip())

    def fetch_models(
        self, *, api_key: str | None = None, base_url: str | None = None, timeout: float = 8.0
    ) -> list[str] | None:
        # The catalog is public, so api_key is not sent.
        effective = (base_url or "").strip().rstrip("/") or self.base_url
        catalog = self._load(base_url=effective, timeout=timeout)
        if catalog is None:
            return None
        self._remember(catalog, effective)
        return [model.id for model in catalog.models if is_usable(model)]

    def _publish_context_windows(self, models: list[CatalogModel], base_url: str) -> None:
        """ProviderProfile has no context-window hook. Hermes resolves a window from its
        persistent cache first, so the live values go there."""
        try:
            from agent.model_metadata import save_provider_context_length
        except ImportError:
            return
        for model in models:
            try:
                save_provider_context_length(model.id, base_url, model.context_window, self.name)
            except Exception as error:  # noqa: BLE001 - a metadata cache must never break listing
                logger.debug("vultr: could not cache context window for %s: %s", model.id, error)

    def get_max_tokens(self, model: str | None) -> int | None:
        """Vultr publishes max_length equal to the context window for most models. Sent as
        max_tokens that is always rejected (prompt + max_tokens > context), so only a real
        limit is returned; otherwise the server uses the context that is left."""
        found = self._model(model)
        if found is None or found.max_output_tokens is None:
            return self.default_max_tokens
        if found.context_window is not None and found.max_output_tokens >= found.context_window:
            return self.default_max_tokens
        return found.max_output_tokens

    def supported_reasoning_efforts(self, model: str | None) -> tuple[str, ...] | None:
        # The base class contract: never block on the network here, answer None while cold.
        found = self._model(model, network=False)
        if found is None:
            return None
        if found.reasoning is None:
            return ()
        efforts = found.reasoning.supported_efforts
        return tuple(efforts) if efforts else None

    def build_api_kwargs_extras(
        self, *, reasoning_config: dict | None = None, model: str | None = None, **context: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        found = self._model(model)
        if found is None or found.reasoning is None:
            return {}, {}
        if isinstance(reasoning_config, dict) and reasoning_config.get("enabled") is False:
            return {}, ({} if found.reasoning.mandatory else {"reasoning_effort": "none"})
        effort = requested_effort(reasoning_config)
        if not effort:
            return {}, {}
        return {}, {"reasoning_effort": clamp_effort(effort, found.reasoning.supported_efforts)}


vultr = VultrProfile(
    name="vultr",
    aliases=("vultr-inference",),
    env_vars=(API_KEY_ENV, BASE_URL_ENV),
    display_name="Vultr",
    description="Vultr Inference - live model catalog",
    signup_url="https://console.vultr.com/inference/",
    base_url=(os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/"),
    supports_vision=True,
)

register_provider(vultr)
