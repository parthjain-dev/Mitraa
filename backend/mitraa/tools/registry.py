"""Tool registry. Adding a tool = one Tool subclass + one register() call."""

from __future__ import annotations

from typing import Any

from mitraa.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]


def build_default_registry() -> ToolRegistry:
    from mitraa.tools import files, memory_tools, project_tools, responsibility_tools,text_files

    registry = ToolRegistry()
    for tool in files.ALL_FILE_TOOLS:
        registry.register(tool)
    for tool in text_files.ALL_TEXT_TOOLS:
        registry.register(tool)
    for tool in memory_tools.ALL_MEMORY_TOOLS + project_tools.ALL_PROJECT_TOOLS:
        registry.register(tool)
    for tool in responsibility_tools.ALL_RESPONSIBILITY_TOOLS:
        registry.register(tool)
    return registry
