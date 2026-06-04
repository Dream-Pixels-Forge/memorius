"""Tests for memorius.plugin_gen — manifest generation and listing."""

import json
import os
import tempfile
import pytest
from memorius.plugin_gen.cli import cmd_list, cmd_init, cmd_generate


class TestPluginGenList:
    """Listing known agent targets."""

    def test_list_returns_nonempty(self):
        """List should print known agent targets and return successfully."""
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            result = cmd_list([])
        output = f.getvalue()
        # Returns None but should print to stdout
        assert len(output) > 0
        # Should mention common agents
        assert "claude" in output.lower() or "codex" in output.lower()


class TestPluginGenInit:
    """Creating skeleton manifest."""

    def test_init_creates_file(self, tmp_path):
        """Init should write universal-manifest.yaml to current dir."""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = cmd_init([])
            manifest_path = tmp_path / "universal-manifest.yaml"
            assert manifest_path.exists()
            content = manifest_path.read_text()
            assert "name:" in content
            assert "mcp:" in content
        finally:
            os.chdir(original_cwd)

    def test_init_idempotent(self, tmp_path):
        """Running init twice should warn but not overwrite."""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            cmd_init([])
            # Second call should warn and return non-zero or just not overwrite
            cmd_init([])
            files = list(tmp_path.glob("*.yaml"))
            assert len(files) == 1
        finally:
            os.chdir(original_cwd)


class TestPluginGenGenerate:
    """Generating plugins from manifest."""

    def test_generate_from_manifest(self, tmp_path):
        """Generate should create plugin directories from a valid manifest."""
        # Create a minimal manifest
        manifest = tmp_path / "universal-manifest.yaml"
        manifest.write_text("""name: test-memorius
version: "0.1.0"
description: Test manifest
author: Test
license: MIT
repository: "https://github.com/test/test"
mcp:
  command: test-mcp
  args: []
agents:
  claude-code:
    hooks:
      stop:
        timeout: 30
      precompact:
        timeout: 30
  codex:
    hooks:
      stop:
        timeout: 30
""")
        # Create output dir
        output = tmp_path / "generated"
        output.mkdir()

        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            result = cmd_generate(["--manifest", str(manifest), "--output", str(output)])
        output_text = f.getvalue()
        # Should have created some plugin files
        generated_files = list(output.rglob("*"))
        assert len(generated_files) > 0
        # Should mention which plugins were generated
        assert "claude-code" in output_text.lower()
        assert "codex" in output_text.lower()
