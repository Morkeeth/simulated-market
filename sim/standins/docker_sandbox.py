"""Sandbox stand-in: Docker. One checkpoint image made with `docker commit`, one fork per user.

The checkpoint is python:3.12-slim plus the vendored wheel of the target and pip set to
install offline from it. The target is staged, not pre-installed, so the user's literal
`pip install python-dotenv` really runs inside the fork. Every fork runs with
`--network none`. A Docker fork time says nothing about a Nebius fork time.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass

from sim.labels import LOCAL

BASE_IMAGE = "python:3.12-slim"
REPO = "simmarket-ckpt"
ENV = [
    "PIP_NO_INDEX=1",
    "PIP_FIND_LINKS=/wheels",
    "PIP_DISABLE_PIP_VERSION_CHECK=1",
    "PIP_ROOT_USER_ACTION=ignore",
    "PIP_PROGRESS_BAR=off",
    "PYTHONDONTWRITEBYTECODE=1",
]


class DockerUnavailable(RuntimeError):
    pass


def _docker(*args, input: bytes | None = None, check: bool = True, timeout: float = 300):
    if shutil.which("docker") is None:
        raise DockerUnavailable("docker is not on PATH. Install Docker Desktop, then run make setup.")
    p = subprocess.run(["docker", *args], input=input, capture_output=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {p.stderr.decode(errors='replace').strip()[:400]}")
    return p


def docker_ok() -> bool:
    try:
        return _docker("info", "--format", "{{.ServerVersion}}", check=False, timeout=20).returncode == 0
    except (DockerUnavailable, subprocess.TimeoutExpired):
        return False


@dataclass
class Fork:
    name: str

    def exec(self, cmd: list[str], stdin: bytes | None = None, timeout: float = 90) -> tuple[int, str]:
        args = ["exec"] + (["-i"] if stdin is not None else []) + ["-w", "/work", self.name] + cmd
        try:
            p = _docker(*args, input=stdin, check=False, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "timed out"
        out = (p.stdout + p.stderr).decode(errors="replace")
        return p.returncode, out

    def close(self) -> None:
        _docker("rm", "-f", self.name, check=False, timeout=60)


class DockerSandbox:
    name = "docker-local"
    label = LOCAL

    def recipe(self, wheel_path, wheel_sha256: str) -> dict:
        base = _docker("image", "inspect", BASE_IMAGE, "--format", "{{.Id}}", check=False)
        if base.returncode != 0:
            raise DockerUnavailable(f"base image {BASE_IMAGE} is not present. Run make setup (needs network once).")
        return {"base_image": BASE_IMAGE, "base_id": base.stdout.decode().strip(),
                "wheel": wheel_path.name, "wheel_sha256": wheel_sha256, "env": ENV, "workdir": "/work"}

    @staticmethod
    def recipe_sha(recipe: dict) -> str:
        return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()

    def checkpoint(self, wheel_path, wheel_sha256: str) -> tuple[str, dict]:
        """Build the checkpoint image once. Reused while the recipe is unchanged."""
        recipe = self.recipe(wheel_path, wheel_sha256)
        tag = f"{REPO}:{self.recipe_sha(recipe)[:12]}"
        if _docker("image", "inspect", tag, check=False).returncode == 0:
            return tag, recipe
        tmp = f"simmarket-build-{self.recipe_sha(recipe)[:12]}"
        _docker("rm", "-f", tmp, check=False)
        _docker("run", "-d", "--name", tmp, "--network", "none", BASE_IMAGE, "sleep", "infinity")
        try:
            _docker("exec", tmp, "mkdir", "-p", "/wheels", "/work")
            _docker("cp", str(wheel_path), f"{tmp}:/wheels/{wheel_path.name}")
            changes = []
            for e in ENV:
                changes += ["--change", f"ENV {e}"]
            changes += ["--change", "WORKDIR /work", "--change", 'CMD ["sleep", "infinity"]']
            _docker("commit", *changes, tmp, tag)
        finally:
            _docker("rm", "-f", tmp, check=False)
        return tag, recipe

    def fork(self, checkpoint: str, name: str) -> Fork:
        _docker("rm", "-f", name, check=False)
        _docker("run", "-d", "--rm", "--network", "none", "--name", name, checkpoint, "sleep", "infinity")
        return Fork(name=name)
