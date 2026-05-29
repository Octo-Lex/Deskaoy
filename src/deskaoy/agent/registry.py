"""ToolRegistry — thread-safe tool registration with AST auto-discovery."""

from __future__ import annotations

import ast
import inspect
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type_name: str
    required: bool
    default: str | None = None
    description: str = ""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: tuple[ToolParameter, ...]
    handler: Any = field(repr=False, compare=False)
    toolsets: tuple[str, ...] = ()
    max_result_chars: int = 50_000
    security_level: str = "sensitive"
    action_class: str = "sensitive"
    impact_level: str = "medium"
    cost_estimate: float = 0.0

    def to_json_schema(self) -> dict:
        properties: dict[str, dict] = {}
        required: list[str] = []
        for p in self.parameters:
            schema_type = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}.get(p.type_name, "string")
            prop: dict[str, Any] = {"type": schema_type}
            if p.description:
                prop["description"] = p.description
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def to_prompt_description(self) -> str:
        params = ", ".join(
            f"{p.name}: {p.type_name}" + (f" = {p.default}" if p.default is not None else "")
            for p in self.parameters
        )
        doc = self.description or ""
        return f"def {self.name}({params}) -> ActionResult:\n    {repr(doc)}"


@dataclass(frozen=True)
class Toolset:
    name: str
    description: str
    tool_names: frozenset[str]


class ToolRegistry:

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._toolsets: dict[str, Toolset] = {}
        self._lock = threading.RLock()

    def register(
        self,
        func: Callable,
        *,
        toolsets: tuple[str, ...] = (),
        max_result_chars: int = 50_000,
        security_level: str | None = None,  # C4: None = read from decorator
        action_class: str | None = None,
        impact_level: str | None = None,
        cost_estimate: float | None = None,
    ) -> None:
        sig = inspect.signature(func)
        params: list[ToolParameter] = []
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            type_name = "str"
            if param.annotation != inspect.Parameter.empty:
                ann = param.annotation
                if hasattr(ann, "__name__"):
                    type_name = ann.__name__
                else:
                    type_name = str(ann)
            required = param.default is inspect.Parameter.empty
            default = repr(param.default) if param.default is not inspect.Parameter.empty else None
            params.append(ToolParameter(name=name, type_name=type_name, required=required, default=default))

        # C4: read security_level from decorator if not explicitly provided
        if security_level is None:
            security_level = getattr(func, 'security_level', 'sensitive')
        if action_class is None:
            action_class = getattr(func, 'action_class', 'sensitive')
        if impact_level is None:
            impact_level = getattr(func, 'impact_level', 'medium')
        if cost_estimate is None:
            cost_estimate = getattr(func, 'cost_estimate', 0.0)

        desc = inspect.getdoc(func) or ""
        tool_def = ToolDefinition(
            name=func.__name__,
            description=desc,
            parameters=tuple(params),
            toolsets=toolsets,
            handler=func,
            max_result_chars=max_result_chars,
            security_level=security_level,
            action_class=action_class,
            impact_level=impact_level,
            cost_estimate=cost_estimate,
        )
        with self._lock:
            self._tools[func.__name__] = tool_def

    def register_definition(self, tool_def: ToolDefinition) -> None:
        """Register a pre-built ToolDefinition directly.

        Use this when you need full control over the tool name, description,
        and parameters — e.g. wrapping SurfaceAdapter methods as agent tools.
        """
        with self._lock:
            self._tools[tool_def.name] = tool_def

    def register_module(self, module_path: Path) -> int:
        try:
            source = module_path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Cannot read module: %s", module_path)
            return 0
        names = self._scan_module_ast(source, str(module_path))
        count = 0
        for func_name in names:
            placeholder = _placeholder_function(func_name)
            self.register(placeholder, toolsets=())
            count += 1
        return count

    def register_package(self, package_dir: Path) -> int:
        total = 0
        for py_file in sorted(package_dir.rglob("*.py")):
            total += self.register_module(py_file)
        return total

    def define_toolset(self, name: str, description: str, tool_names: set[str]) -> None:
        with self._lock:
            self._toolsets[name] = Toolset(name=name, description=description, tool_names=frozenset(tool_names))

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def snapshot(self, *, toolset: str | None = None) -> dict[str, ToolDefinition]:
        if toolset is None:
            return dict(self._tools)
        ts = self._toolsets.get(toolset)
        if ts is None:
            return {}
        return {n: t for n, t in self._tools.items() if n in ts.tool_names}

    def list_tools(self, *, toolset: str | None = None) -> list[ToolDefinition]:
        return list(self.snapshot(toolset=toolset).values())

    def list_toolsets(self) -> list[Toolset]:
        return list(self._toolsets.values())

    def build_tool_api_description(self, *, toolset: str | None = None) -> str:
        tools = self.snapshot(toolset=toolset)
        if not tools:
            return "No tools registered."
        lines = ["Available tools:\n"]
        for name in sorted(tools):
            lines.append(tools[name].to_prompt_description())
            lines.append("")
        return "\n".join(lines)

    def build_tool_schemas(self, *, toolset: str | None = None) -> list[dict]:
        tools = self.snapshot(toolset=toolset)
        return [tools[n].to_json_schema() for n in sorted(tools)]

    def _scan_module_ast(self, source: str, filename: str) -> list[str]:
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError:
            logger.warning("Syntax error in %s", filename)
            return []
        decorated = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if self._is_agent_action_decorator(decorator):
                        decorated.append(node.name)
        return decorated

    @staticmethod
    def _is_agent_action_decorator(decorator: ast.expr) -> bool:
        if isinstance(decorator, ast.Name) and decorator.id == "agent_action":
            return True
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name) and func.id == "agent_action":
                return True
        return False

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def toolset_count(self) -> int:
        return len(self._toolsets)


def _placeholder_function(name: str) -> Callable:
    """Create a placeholder function for AST-discovered tools."""
    def placeholder(**kwargs: Any) -> Any:
        raise NotImplementedError(f"Tool '{name}' discovered via AST but not loaded")
    placeholder.__name__ = name
    placeholder.__qualname__ = name
    placeholder.__doc__ = f"Auto-discovered tool: {name}"
    placeholder.is_agent_action = True
    return placeholder
