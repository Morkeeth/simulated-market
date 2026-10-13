"""One OpenAI-compatible chat client. Only base_url, key and model name change between backends.

Token Factory and the local mlx_lm.server both speak /v1/chat/completions, so the same
class drives both. The label of the backend travels with every reply so a caller can
never mistake a LOCAL reply for a runtime Token Factory reply.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatReply:
    text: str
    model: str | None
    label: str
    usage: dict
    finish_reason: str | None = None


class ChatClient:
    def __init__(self, *, base_url: str, model: str, label: str, api_key: str | None = None,
                 timeout: float = 120.0, record=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.label = label
        self._api_key = api_key
        self.timeout = timeout
        self.record = record or (lambda row: None)
        self._identity_failure = None

    def require_verified_identity(self):
        if self._identity_failure:
            raise ValueError(self._identity_failure)

    def chat(self, messages: list[dict], *, temperature: float = 0.0, seed: int = 0,
             max_tokens: int = 256, chat_template_kwargs: dict | None = None,
             response_format: dict | None = None) -> ChatReply:
        self.require_verified_identity()
        request = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "seed": seed,
            "max_tokens": max_tokens,
        }
        if chat_template_kwargs is not None:
            request['chat_template_kwargs'] = chat_template_kwargs
        if response_format is not None:
            request['response_format'] = response_format
        body = json.dumps(request).encode()
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body,
                                     method="POST", headers=headers)
        self.record({'service': 'chat_request', 'event': 'attempted',
                     'requested_model': self.model, 'backend_label': self.label})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.load(r)
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                error_payload = json.load(e)
                error_obj = error_payload.get('error', error_payload)
                detail = json.dumps(error_obj, ensure_ascii=False)[:600]
                if self._api_key:
                    detail = detail.replace(self._api_key, '[credential removed]')
            except Exception:
                pass
            self.record({'service': 'chat_request', 'event': 'failed',
                         'requested_model': self.model, 'error_type': 'HTTPError',
                         'http_status': e.code, 'provider_error': detail, 'billing_status': 'unknown'})
            raise RuntimeError(f"chat call failed: HTTP {e.code}") from None
        except Exception as e:
            self.record({'service': 'chat_request', 'event': 'failed',
                         'requested_model': self.model, 'error_type': type(e).__name__,
                         'billing_status': 'unknown'})
            raise RuntimeError('chat call failed: ' + type(e).__name__) from None
        observed = payload.get("model")
        identity = ('unverified' if not isinstance(observed, str) or not observed
                    else 'matched' if observed == self.model else 'mismatch')
        self.record({"service": "chat", "request_id": payload.get("id"),
                     "model": observed, "requested_model": self.model,
                     "observed_model": observed, "identity_status": identity,
                     "usage": payload.get("usage") or {},
                     "finish_reason": (payload.get("choices") or [{}])[0].get("finish_reason")})
        if self.label == "RUNTIME" and identity != 'matched':
            self._identity_failure = (
                "Sponsor response model identity " + identity +
                "; no action or quote accepted. Inspect requested_model and observed_model "
                "in services.jsonl. Select an exact provider-returned model ID and prepare "
                "a new preview; missing identity requires provider support. Aliases are not accepted.")
            self.require_verified_identity()
        text = payload["choices"][0]["message"]["content"] or ""
        return ChatReply(text=text, model=observed, label=self.label,
                         usage=payload.get("usage") or {},
                         finish_reason=payload["choices"][0].get("finish_reason"))
