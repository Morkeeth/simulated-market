"""Token Factory model adapter (the real one). Refuses without a key and a model id.

Base URL from the Token Factory docs as cited in the research run:
https://api.tokenfactory.nebius.com/v1/ . The exact Nemotron model id is not pinned
here on purpose: it must come from the environment once the account exists, so this
file never guesses a model name.
"""
from __future__ import annotations

import os
from pathlib import Path

from sim.adapters.openai_compat import ChatClient
from sim.errors import NoKey
from sim.labels import RUNTIME

BASE_URL = "https://api.tokenfactory.nebius.com/v1"
KEY_ENV = "TOKEN_FACTORY_API_KEY"
MODEL_ENV = "TOKEN_FACTORY_MODEL"
KEY_PATH = Path.home() / ".config" / "keys" / "tokenfactory.key"


def load_key() -> str:
    env = os.environ.get(KEY_ENV) or os.environ.get("NEBIUS_API_KEY")
    if env and env.strip():
        return env.strip()
    if KEY_PATH.exists():
        key = KEY_PATH.read_text().strip()
        if key:
            return key
    raise NoKey(
        f"no Token Factory key: set {KEY_ENV} or place it at {KEY_PATH}. "
        "Execution stays off until configured."
    )


def client() -> ChatClient:
    key = load_key()
    model = os.environ.get(MODEL_ENV, "").strip()
    if not model:
        raise NoKey(f"no Token Factory model id: set {MODEL_ENV}. Refusing to guess a model name.")
    return ChatClient(base_url=BASE_URL, model=model, label=RUNTIME, api_key=key)


def model_requirement(model=None):
    """Configuration hint only; neither a runtime receipt nor a licence check."""
    selected = os.environ.get(MODEL_ENV, '').strip() if model is None else model
    candidate = selected.lower().startswith('nvidia/') and 'nemotron' in selected.lower()
    return {'selected_model': selected or None,
            'nvidia_nemotron_candidate': candidate,
            'runtime_verified': False,
            'note': 'The hackathon needs an NVIDIA open-source model. A name is only a candidate; verify its official model card and a matching runtime response.'}
