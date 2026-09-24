from providers import get_provider_profile


def test_the_profile_registers_under_its_name_and_alias(plugin):
    assert get_provider_profile("vultr") is plugin.vultr
    assert get_provider_profile("vultr-inference") is plugin.vultr
    assert plugin.vultr.base_url == "https://api.vultrinference.com/v1"
    assert plugin.vultr.env_vars[0] == "VULTR_INFERENCE_API_KEY"


def test_fetch_models_offers_ready_chat_models_with_a_context_window(plugin):
    assert plugin.vultr.fetch_models() == ["glm-5.3", "small", "always-thinks"]


def test_fetch_models_returns_none_without_network_or_cache(plugin, network):
    network.down = True
    assert plugin.vultr.fetch_models() is None


def test_fetch_models_serves_the_last_good_catalog_when_the_network_fails(plugin, network):
    plugin.vultr.fetch_models()
    network.down = True
    assert plugin.vultr.fetch_models() == ["glm-5.3", "small", "always-thinks"]


def test_context_windows_reach_hermes_own_resolver(plugin):
    from agent.model_metadata import get_model_context_length

    plugin.vultr.fetch_models()
    base_url = plugin.vultr.base_url
    assert get_model_context_length("glm-5.3", base_url=base_url, provider="vultr") == 1_048_576
    assert get_model_context_length("small", base_url=base_url, provider="vultr") == 131_072


def test_reasoning_effort_is_sent_top_level_and_clamped(plugin):
    extras = lambda config, model="glm-5.3": plugin.vultr.build_api_kwargs_extras(reasoning_config=config, model=model)
    assert extras({"enabled": True, "effort": "high"}) == ({}, {"reasoning_effort": "high"})
    assert extras({"enabled": True, "effort": "ultra"}) == ({}, {"reasoning_effort": "ultra"})
    # Not in the model's list: the nearest weaker level, never a stronger one.
    assert extras({"enabled": True, "effort": "max"}) == ({}, {"reasoning_effort": "high"})
    assert extras({"enabled": False}) == ({}, {"reasoning_effort": "none"})
    assert extras(None) == ({}, {})
    # A model that cannot reason gets no reasoning fields at all.
    assert extras({"enabled": True, "effort": "high"}, "small") == ({}, {})
    # Mandatory reasoning has no off switch; no allowlist passes the request through.
    assert extras({"enabled": False}, "always-thinks") == ({}, {})
    assert extras({"enabled": True, "effort": "max"}, "always-thinks") == ({}, {"reasoning_effort": "max"})
    assert extras({"enabled": True, "effort": "high"}, "unknown-model") == ({}, {})


def test_the_first_request_loads_the_catalog_once_even_when_cold(plugin, network):
    assert plugin.vultr.build_api_kwargs_extras(reasoning_config={"effort": "low"}, model="glm-5.3") == (
        {},
        {"reasoning_effort": "low"},
    )
    plugin.vultr.build_api_kwargs_extras(reasoning_config={"effort": "low"}, model="glm-5.3")
    assert network.calls == 1


def test_a_failed_cold_load_is_not_retried_on_every_request(plugin, network):
    network.down = True
    for _ in range(3):
        assert plugin.vultr.build_api_kwargs_extras(reasoning_config={"effort": "low"}, model="glm-5.3") == ({}, {})
    assert network.calls == 1


def test_supported_reasoning_efforts_never_touches_the_network(plugin, network):
    assert plugin.vultr.supported_reasoning_efforts("glm-5.3") is None
    assert network.calls == 0

    plugin.vultr.fetch_models()
    assert plugin.vultr.supported_reasoning_efforts("glm-5.3") == ("ultra", "high", "medium", "low")
    assert plugin.vultr.supported_reasoning_efforts("small") == ()
    assert plugin.vultr.supported_reasoning_efforts("always-thinks") is None
    assert plugin.vultr.supported_reasoning_efforts("unknown-model") is None


def test_max_tokens_is_only_a_real_output_limit(plugin):
    plugin.vultr.fetch_models()
    # Published limit equals the context window: not an output limit, leave it to the server.
    assert plugin.vultr.get_max_tokens("glm-5.3") is None
    assert plugin.vultr.get_max_tokens("small") == 16_384
    assert plugin.vultr.get_max_tokens("unknown-model") is None
