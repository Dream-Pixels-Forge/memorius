"""
memorius — Universal adapter layer for MemPalace.

Components:
    hooks:       Universal hook lifecycle (any AI agent → MemPalace actions)
    gateway:     HTTP REST gateway wrapping MCP server
    plugin_gen:  Universal plugin manifest → per-agent plugin generator
    normalizers: Additional conversation format importers
"""

__version__ = "0.1.0"
