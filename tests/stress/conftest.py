# tests/stress/conftest.py
"""Shared fixtures for agent loop stress tests.

NOTE: Stress tests use REAL API calls. We override the root hermetic_env
fixture to allow access to ~/.marneo/config.yaml and credentials.
"""
from __future__ import annotations

import ast
import json
import math
import operator
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from marneo.tools.registry import ToolRegistry, tool_result

RESULTS_DIR = Path(__file__).parent / "results"


@pytest.fixture(autouse=True)
def hermetic_env():
    """Override root hermetic_env: stress tests need real config and credentials."""
    from marneo.engine.provider import _pool
    _pool._initialized = False
    _pool._providers.clear()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def stress_registry() -> ToolRegistry:
    """Registry with 3 lightweight tools for stress testing."""
    reg = ToolRegistry()

    reg.register(
        name="get_current_time",
        description="Get the current date and time",
        schema={
            "name": "get_current_time",
            "description": "Get the current date and time",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kw: tool_result(
            time=datetime.now().isoformat(),
            timestamp=time.time(),
        ),
    )

    reg.register(
        name="calculate",
        description="Calculate a math expression safely",
        schema={
            "name": "calculate",
            "description": "Calculate a math expression. Only basic arithmetic and math functions allowed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression to evaluate"},
                },
                "required": ["expression"],
            },
        },
        handler=_safe_calculate,
    )

    reg.register(
        name="search_knowledge",
        description="Search internal knowledge base",
        schema={
            "name": "search_knowledge",
            "description": "Search the internal knowledge base for relevant information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
        handler=_mock_search,
    )

    return reg


@pytest.fixture
def loop_trap_registry() -> ToolRegistry:
    """Registry with a tool that returns ambiguous results to induce loops."""
    reg = ToolRegistry()

    reg.register(
        name="check_status",
        description="Check the status of a process",
        schema={
            "name": "check_status",
            "description": "Check the current status. Returns partial information that may need re-checking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "What to check"},
                },
                "required": ["target"],
            },
        },
        handler=lambda args, **kw: tool_result(
            status="in_progress",
            progress="47%",
            message="Still processing, check again for updated status...",
        ),
    )

    return reg


def _eval_arithmetic(expr: str) -> float:
    """Evaluate a small arithmetic expression without Python eval."""
    if len(expr) > 200:
        raise ValueError("expression too long")
    binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
    }
    unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}
    functions = {
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "abs": abs,
        "pow": pow,
    }
    constants = {"pi": math.pi, "e": math.e}

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in constants:
            return float(constants[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
            left = visit(node.left)
            right = visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ValueError("exponent too large")
            return float(binary_ops[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
            return float(unary_ops[type(node.op)](visit(node.operand)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions:
            if node.keywords:
                raise ValueError("keyword arguments are not allowed")
            args = [visit(arg) for arg in node.args]
            if node.func.id == "pow" and len(args) >= 2 and abs(args[1]) > 8:
                raise ValueError("exponent too large")
            return float(functions[node.func.id](*args))
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    parsed = ast.parse(expr, mode="eval")
    if sum(1 for _ in ast.walk(parsed)) > 50:
        raise ValueError("expression too complex")
    return visit(parsed)


def _safe_calculate(args: dict, **kw: Any) -> str:
    expr = args.get("expression", "")
    try:
        result = _eval_arithmetic(expr)
        return tool_result(expression=expr, result=result)
    except Exception as exc:
        return tool_result(error=str(exc))


def _mock_search(args: dict, **kw: Any) -> str:
    query = args.get("query", "")
    return tool_result(
        query=query,
        results=[
            {"title": "项目管理最佳实践", "snippet": "敏捷开发流程中，sprint 规划是核心环节..."},
            {"title": "技术架构设计", "snippet": "微服务架构的关键在于服务边界划分..."},
            {"title": "团队协作模式", "snippet": "高效团队通常采用异步优先的沟通策略..."},
        ],
        total=3,
    )


class StressReporter:
    """Collects and persists stress test metrics."""

    def __init__(self, test_name: str) -> None:
        self.test_name = test_name
        self.started_at = datetime.now().isoformat()
        self.rounds: list[dict] = []
        self._provider: str = ""

    def record_round(self, **metrics: Any) -> None:
        self.rounds.append(metrics)

    def set_provider(self, provider_id: str, model: str) -> None:
        self._provider = f"{model} ({provider_id})"

    def save(self) -> Path:
        report = {
            "test": self.test_name,
            "provider": self._provider,
            "started_at": self.started_at,
            "finished_at": datetime.now().isoformat(),
            "rounds": self.rounds,
        }
        path = RESULTS_DIR / f"{self.test_name}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def print_progress(self, round_num: int, total: int, **kv: Any) -> None:
        extras = " | ".join(f"{k}={v}" for k, v in kv.items())
        print(f"  [{round_num}/{total}] {extras}")


@pytest.fixture
def reporter(request) -> StressReporter:
    name = request.node.name.replace("test_", "engine_")
    return StressReporter(name)
