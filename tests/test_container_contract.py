"""SG-08: the production container contract (issue #100).

The image is built outside CI (a multi-GB torch download), so these checks
pin the parts that must not regress: multi-stage build, non-root UID 10001,
dumb-init as PID 1, a liveness healthcheck, no secrets, and a compose file
that keeps the vault on a volume. The heavier DoD commands are documented in
``dev-notes/subgoals/SG-08-container-hardening.md`` and run by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


class TestDockerfile:
    def test_is_multi_stage(self):
        text = _dockerfile()
        names = re.findall(r"^FROM\s+\S+\s+AS\s+(\w+)\s*$", text, re.MULTILINE | re.IGNORECASE)
        assert "build" in names, f"Dockerfile stages are {names}"
        assert "runtime" in names, f"Dockerfile stages are {names}"

    def test_runtime_is_non_root_10001(self):
        assert re.search(r"^USER\s+10001(?::10001)?\s*$", _dockerfile(), re.MULTILINE), (
            "runtime must run as UID 10001"
        )

    def test_dumb_init_is_the_entrypoint(self):
        assert re.search(
            r'^ENTRYPOINT\s+\["dumb-init",\s*"--"\]', _dockerfile(), re.MULTILINE
        ), "dumb-init must be PID 1"

    def test_dumb_init_is_installed_in_the_runtime_stage(self):
        text = _dockerfile()
        runtime = text[text.upper().index("AS RUNTIME") :]
        assert "dumb-init" in runtime, "dumb-init is not installed in the runtime image"

    def test_healthcheck_uses_the_liveness_probe(self):
        text = _dockerfile()
        health = re.search(r"^HEALTHCHECK.*(?:\n\s+.*)*", text, re.MULTILINE)
        assert health, "Dockerfile has no HEALTHCHECK"
        assert "/health/live" in health.group(0)

    def test_serves_the_rest_api_on_a_fixed_port(self):
        text = _dockerfile()
        assert '"serve-rest"' in text, "container does not start the REST server"
        assert "8912" in text and "EXPOSE 8912" in text

    def test_keeps_the_vault_on_a_volume(self):
        text = _dockerfile()
        assert 'VOLUME ["/data"]' in text
        assert "MEMORIUS_STORAGE_PATH=/data" in text

    def test_bakes_in_no_secrets(self):
        text = _dockerfile()
        assert "COPY .env" not in text
        assert not re.search(r"(?i)^ENV\s+.*(API_KEY|TOKEN|SECRET)\s*=", text, re.MULTILINE)


class TestDockerignore:
    def test_excludes_development_inputs(self):
        if not (ROOT / ".dockerignore").is_file():
            raise AssertionError(".dockerignore is missing")
        lines = {
            line.strip()
            for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        for required in (
            ".git",
            ".github",
            "tests",
            "docs",
            "dev-notes",
            "__pycache__",
            "*.pyc",
            ".env",
            "dist",
            "build",
        ):
            assert required in lines, f".dockerignore does not exclude {required!r}"
        assert "README.md" not in lines, "README.md is needed by pyproject.toml"

    def test_keeps_secret_config_out_of_the_context(self):
        lines = {
            line.strip()
            for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        assert "memorius.yaml" in lines, "a local memorius.yaml could carry secrets"


class TestCompose:
    def _compose(self) -> dict:
        return yaml.safe_load((ROOT / "compose.yml").read_text(encoding="utf-8"))

    def test_runs_the_built_image_with_a_vault_volume(self):
        service = self._compose()["services"]["memorius"]
        assert "build" in service, "compose does not build the image"
        assert any(":/data" in volume for volume in service["volumes"]), (
            "compose does not mount a vault volume at /data"
        )
        assert service["environment"]["MEMORIUS_STORAGE_PATH"] == "/data"

    def test_publishes_the_api_on_loopback_only(self):
        service = self._compose()["services"]["memorius"]
        ports = [str(port) for port in service["ports"]]
        assert ports, "compose publishes no port"
        assert all(port.startswith("127.0.0.1:") for port in ports), (
            "the REST API must not be exposed on all interfaces by default"
        )

    def test_healthcheck_matches_the_image(self):
        service = self._compose()["services"]["memorius"]
        test = " ".join(service["healthcheck"]["test"])
        assert "/health/live" in test


class TestDocs:
    def test_readme_documents_build_and_run(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "docker build -t memorius:prod ." in readme
        assert "docker compose up" in readme
        assert "10001" in readme or "non-root" in readme
