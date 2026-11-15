# AGENTS.md - vultr/model-provider-hermes

A Hermes Agent model-provider plugin: one `ProviderProfile`, `vultr`, fed by
the live catalog. The repo root is the plugin directory, because
`hermes plugins install` clones a repo into `$HERMES_HOME/plugins/<name>/` and
imports its `__init__.py`. `plugin.yaml` is the manifest; `pyproject.toml` is
how Hermes learns the Python dependency.

Human overview, hook table and install: `README.md`.

## What holds the design up

- **The catalog library does the reading.** `vultr_model_catalog` fetches
  `GET /v1/models`, parses Model Document 2.4 and normalizes it. This repo only
  hands Hermes what it has a place for. A parsing or normalization fix belongs
  in the library, not here
- **Nothing static.** No model id, context window or effort list is written in
  this repo. `fallback_models` stays empty on purpose
- **Never break the host.** Importing the plugin does no network I/O. No
  network and no cache means fewer features, never an exception out of a hook
- **The hot path stays cheap.** `build_api_kwargs_extras`, `get_max_tokens` and
  `supported_reasoning_efforts` run on every request: memory, then the disk
  cache. Only `build_api_kwargs_extras` and `get_max_tokens` may load over the
  network, once, when cold. `supported_reasoning_efforts` never may: that is
  the base class contract
- **Cold must work.** A user who never opened the model picker still gets
  `reasoning_effort` and context windows on the first request. This was a real
  bug; `test_the_first_request_loads_the_catalog_once_even_when_cold` pins it
- **Requests must be accepted by the engine.** Vultr publishes `max_length`
  equal to the context window for most models. Sent as `max_tokens` that is
  always rejected. `get_max_tokens` returns a limit only when it is a real one
- **One internal call, guarded.** `save_provider_context_length` is not plugin
  API. It is imported inside a try and each call is wrapped; if Hermes renames
  it the plugin loses live context windows and nothing else
- **Siblings:** `model-provider-pi`, `-openclaw` and `-opencode` make the same
  decisions in TypeScript. Keep the rules for usable models and for reasoning
  the same across all four

## Validation

Fast (inner loop): the full command below with a narrower selection
- `... pytest -x -k <name>` - one test in `tests/test_provider.py`
- `... pytest --lf -x` - only what failed last run

Full (once, before calling a change complete):
- The tests must pass, against a real Hermes and on its Python:
  `uv run --no-project --python 3.11 --with pytest --with "<the dependency in pyproject.toml>" pytest -q`.
  Without a Hermes install (`HERMES_AGENT_DIR`, default
  `~/.hermes/hermes-agent`) the suite skips, which is not a pass

Heavy (never in the inner loop; run once at the end in the background):
- the install path in a throwaway `HERMES_HOME` (below)

## Working here

- `pyproject.toml` pins `vultr-model-catalog` to a release. Bump the pin on
  purpose, and install it into Hermes's venv before testing
- Hermes's behavior is in the installed tree, not in web summaries:
  `providers/base.py` (the hooks and their contracts),
  `agent/model_metadata.py` (context resolution order),
  `agent/reasoning_effort.py`, `hermes_cli/plugin_python_deps.py`, and
  `plugins/model-providers/*` as worked providers
- To test the install path: `hermes plugins install file://<this tree> --enable`
  in a throwaway `HERMES_HOME`. It clones the last commit. A bare path is read
  as a GitHub `owner/repo` and fails
- Test with a throwaway `HERMES_HOME`, never the user's own. The `hermes`
  launcher ignores `PYTHONPATH`: the library has to be in Hermes's venv
- The Hermes plugin catalog wants a public repo with tagged releases and no
  self-updating code. Fetching a model list at runtime is data, not code
