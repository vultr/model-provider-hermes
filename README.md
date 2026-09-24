# vultr-provider for Hermes Agent

Vultr Inference as a model provider plugin for
[Hermes Agent](https://hermes-agent.nousresearch.com). The model list, context
windows, output limits and reasoning efforts come from the live
`GET /v1/models` catalog.

Hermes cannot read that endpoint on its own. It serves OpenRouter provider
Model Documents (schema 2.4), where limits and prices are nested under
modalities; Hermes looks for flat fields and finds model ids only.

## Install

```bash
hermes plugins install https://github.com/vultr/model-provider-hermes.git --enable
hermes chat --provider vultr -m glm-5.3 --reasoning high
```

Hermes reads `pyproject.toml` and installs `vultr-model-catalog` into its own
venv. `VULTR_INFERENCE_API_KEY` is asked for on install and kept in `~/.hermes/.env`.

A local checkout installs through a `file://` URL. Hermes clones it, so it
gets the last commit, not uncommitted changes. A bare path does not work:
Hermes reads it as a GitHub `owner/repo`.

```bash
hermes plugins install file://$HOME/src/vultr/model-provider-hermes --enable
```

For development, link the working tree as a user plugin:

```bash
ln -s "$PWD" ~/.hermes/plugins/model-providers/vultr
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python \
  "vultr-model-catalog @ git+https://github.com/vultr/model-catalog-python.git"
```

## How it works

`__init__.py` registers a `ProviderProfile` named `vultr` (alias
`vultr-inference`), `chat_completions` mode.

| Hook | What it does |
| --- | --- |
| `fetch_models` | The ids of usable models: text output, `is_ready`, a context window. The catalog is public, so no key is sent |
| `build_api_kwargs_extras` | Top-level `reasoning_effort`, clamped to the model's `supported_efforts` with Hermes's own `clamp_effort` (nearest weaker level). Reasoning disabled sends `none`, unless reasoning is mandatory. A model without a `reasoning` block gets no reasoning fields |
| `supported_reasoning_efforts` | The model's list; `()` for a model that cannot reason; `None` without an allowlist or while cold. Never touches the network, as the base class requires |
| `get_max_tokens` | The published output limit, only when it is below the context window |

`ProviderProfile` has no hook for context windows. Hermes resolves a window
from its persistent cache before anything else, so the plugin writes the live
values there (`agent.model_metadata.save_provider_context_length`) whenever it
loads the catalog. That function is internal to Hermes; the call is guarded,
and without it Hermes falls back to its own resolution.

Vultr publishes `max_length` equal to the context window for most models.
Sent as `max_tokens` that is always rejected (prompt + max_tokens > context),
so for those models `get_max_tokens` returns nothing and the server uses the
context that is left.

The catalog is held in memory, then in
`$HERMES_HOME/cache/vultr-model-catalog.json`. The first request of a cold
install loads it once over the network (3 s timeout); a failure is not retried
for 60 s. With no network and no cache the provider still works, without
reasoning fields or live context windows.

Prices are not mapped: Hermes has no per-provider pricing hook, and its
generic `/models` pricing parser does not read this schema.

## Environment

| Variable | Meaning |
| --- | --- |
| `VULTR_INFERENCE_API_KEY` | The provider credential |
| `VULTR_INFERENCE_BASE_URL` | Overrides `https://api.vultrinference.com/v1`. Read once, at import |

## Development

The plugin imports Hermes, so the tests run against an installed Hermes
(`HERMES_AGENT_DIR`, default `~/.hermes/hermes-agent`) and skip without one.
Python must match Hermes's venv:

```bash
uv run --no-project --python 3.11 --with pytest \
  --with "vultr-model-catalog @ git+https://github.com/vultr/model-catalog-python.git" \
  pytest -q
```

Verifying against the real CLI needs no API key: serve
`model-catalog-python/fixtures/vultr-catalog.json` at `/v1/models` from a local
server that records `POST /v1/chat/completions` and answers with a short SSE
stream. Point `VULTR_INFERENCE_BASE_URL` at it, use a throwaway `HERMES_HOME`
with this tree linked under `plugins/model-providers/vultr`, and run
`hermes chat -Q -q "say ok" --provider vultr -m glm-5.3 --reasoning high`.
