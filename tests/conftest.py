"""The plugin imports Hermes (`providers`, `agent`, `hermes_constants`), so the tests run
against an installed Hermes. HERMES_AGENT_DIR points at it; without one the suite skips."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
HERMES = Path(os.environ.get("HERMES_AGENT_DIR") or Path.home() / ".hermes" / "hermes-agent")
SITE_PACKAGES = sorted((HERMES / "venv" / "lib").glob("python3.*/site-packages"))

if not (HERMES / "providers" / "base.py").exists() or not SITE_PACKAGES:
    pytest.skip(f"no Hermes install at {HERMES}", allow_module_level=True)

sys.path[:0] = [str(HERMES), str(SITE_PACKAGES[-1])]


def document(model_id="glm-5.3", *, context=1_048_576, output=1_048_576, reasoning="default", **extra):
    if reasoning == "default":
        reasoning = {"mandatory": False, "supported_efforts": ["ultra", "high", "medium", "low"]}
    text_out = {"type": "text", "supported_parameters": {"tools": {"type": "boolean"}}}
    if output:
        text_out["max_length"] = {"value": output, "unit": "token"}
    text_in = {"type": "text"}
    if context:
        text_in["supported_inputs"] = {"max_context_length": {"value": context, "unit": "token"}}
    return {
        "schema_version": "2.4",
        "id": model_id,
        "name": model_id,
        "input_modalities": [text_in],
        "output_modalities": [text_out],
        "reasoning": reasoning,
        **extra,
    }


PAYLOAD = {
    "data": [
        document(),
        document("small", context=131_072, output=16_384, reasoning=None),
        document("always-thinks", reasoning={"mandatory": True, "supported_efforts": None}),
        document("reranker", output_modalities=[{"type": "rerank", "supported_parameters": {}}]),
        document("unready", is_ready=False),
        document("no-context", context=None),
    ]
}


class Network:
    def __init__(self):
        self.calls = 0
        self.down = False

    def __call__(self, url, headers, timeout):
        self.calls += 1
        if self.down:
            raise OSError("network unreachable")
        return json.dumps(PAYLOAD).encode()


@pytest.fixture
def network():
    return Network()


@pytest.fixture
def plugin(tmp_path, monkeypatch, network):
    """A fresh import of the plugin with an empty HERMES_HOME and a fake network."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("VULTR_INFERENCE_BASE_URL", raising=False)
    spec = importlib.util.spec_from_file_location("vultr_provider_under_test", ROOT / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    real = module.load_catalog
    monkeypatch.setattr(
        module, "load_catalog", lambda **kwargs: real(**{**kwargs, "transport": kwargs.get("transport") or network})
    )
    return module
