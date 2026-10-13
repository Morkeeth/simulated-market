"""Model stand-in: a small 4-bit instruct model served by mlx_lm.server on this machine.

Same OpenAI-compatible client as Token Factory; only base_url changes. Every reply is
labelled LOCAL-MODEL. This is not Nemotron and nothing it prints may say so.
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.request

from sim import ROOT
from sim.adapters.openai_compat import ChatClient
from sim.labels import LOCAL_MODEL

# 7B, not 1.5B: on 29 Sep the 1.5B model answered RUN for every code block, so its funnel
# measured the model and not the docs. The 7B model varied its choices per block.
MODEL = os.environ.get("SIM_LOCAL_MODEL", "mlx-community/Qwen2.5-7B-Instruct-4bit")
RUNTIME = "mlx_lm.server"
VENV = ROOT / ".venv-model"
SERVER_BIN = VENV / "bin" / "mlx_lm.server"


class LocalModelUnavailable(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


def _up(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


class LocalModel:
    name = f"{RUNTIME} {MODEL}"
    label = LOCAL_MODEL

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.base_url: str | None = None

    def start(self, wait: float = 180) -> None:
        """Always starts its own server on a free port, so it never talks to a foreign one."""
        if not SERVER_BIN.exists():
            raise LocalModelUnavailable(f"{SERVER_BIN} not found. Run make model first.")
        port = _free_port()
        self.base_url = f"http://127.0.0.1:{port}/v1"
        (ROOT / "runs").mkdir(exist_ok=True)
        log = open(ROOT / "runs" / "mlx-server.log", "ab")
        env = dict(os.environ, HF_HUB_OFFLINE="1")  # the model must already be on disk (make model)
        self.proc = subprocess.Popen([str(SERVER_BIN), "--model", MODEL, "--host", "127.0.0.1",
                                      "--port", str(port),
                                      # Determinism: no KV reuse across requests, no batching.
                                      "--prompt-cache-size", "0", "--decode-concurrency", "1",
                                      "--prompt-concurrency", "1"], stdout=log, stderr=log, env=env)
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait:
            if self.proc.poll() is not None:
                raise LocalModelUnavailable("mlx_lm.server exited. See runs/mlx-server.log.")
            if _up(self.base_url):
                return
            time.sleep(1)
        raise LocalModelUnavailable("mlx_lm.server did not come up in time.")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None

    def client(self) -> ChatClient:
        if self.base_url is None:
            raise LocalModelUnavailable("start() the local model first.")
        return ChatClient(base_url=self.base_url, model=MODEL, label=LOCAL_MODEL, timeout=180)
