"""MUNagent 入口:最小化 LLM tool calling 样例."""

from __future__ import annotations

import ast
import asyncio
import json
import operator
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_EXPR_BINOPS: dict[type, object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_EXPR_UNARYOPS: dict[type, object] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def _eval_python_expr(expression: str) -> float | int:
    """仅允许加减乘除、整除、取模、幂与括号的算术表达式."""
    tree = ast.parse(expression, mode="eval")

    def _eval(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp):
            op = _EXPR_BINOPS.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
            return op(_eval(node.left), _eval(node.right))  # type: ignore[operator]
        if isinstance(node, ast.UnaryOp):
            op = _EXPR_UNARYOPS.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")
            return op(_eval(node.operand))  # type: ignore[operator]
        raise ValueError(f"不支持的表达式节点: {type(node).__name__}")

    return _eval(tree)


def _python_expr_tool():
    from llm import ToolSpec

    return ToolSpec(
        name="python_expr",
        description="用 Python 算术求值一个表达式,只支持 + - * / // % ** 与括号.",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "合法算术表达式,例如 ((123+456)*789-1011)/13",
                }
            },
            "required": ["expression"],
        },
    )


async def _demo_llm_tools_async() -> None:
    from llm import (
        ChatMessage,
        LLM,
        TextDelta,
        ThinkDelta,
        ToolCallDelta,
        ToolCallsDelta,
        UsageDelta,
    )

    question = (
        "请精确计算下面这个式子的值,不要心算,必须调用 python_expr 工具:"
        " ((123 + 456) * 789 - 1011) / 13 + 2**10 - (88 // 5)"
    )
    expected = _eval_python_expr(
        "((123 + 456) * 789 - 1011) / 13 + 2**10 - (88 // 5)"
    )

    _section("LLM tools 最小化样例: python_expr")
    print(f"  问题: {question}")
    print(f"  本地参考答案: {expected}")

    llm = LLM(thinking=False)
    tools = [_python_expr_tool()]
    messages: list[ChatMessage] = [
        ChatMessage(
            role="system",
            content=(
                "你是计算助手.凡涉及多步算术,必须调用 python_expr 工具求值,"
                "根据工具返回结果用一两句话给出最终答案."
            ),
        ),
        ChatMessage(role="user", content=question),
    ]

    def on_delta(delta) -> None:
        if isinstance(delta, ThinkDelta):
            sys.stdout.write(f"\033[2m{delta.text}\033[0m")
        elif isinstance(delta, TextDelta):
            sys.stdout.write(delta.text)
        elif isinstance(delta, ToolCallDelta) and delta.name:
            sys.stdout.write(f"\n  → tool {delta.name}#{delta.id or '?'}")
        elif isinstance(delta, UsageDelta):
            sys.stdout.write(
                f"\n  [usage prompt={delta.prompt_tokens} "
                f"completion={delta.completion_tokens} finish={delta.finish_reason}]\n"
            )
        sys.stdout.flush()

    for round_no in range(1, 4):
        print(f"\n--- round {round_no} ---")
        tool_calls = None
        async for delta in llm.stream(
            messages,
            tools=tools,
            tool_choice="auto",
            on_delta=on_delta,
        ):
            if isinstance(delta, ToolCallsDelta):
                tool_calls = delta.calls
        print()
        if not tool_calls:
            break

        messages.append(
            ChatMessage(role="assistant", content="", tool_calls=list(tool_calls))
        )
        for call in tool_calls:
            args = json.loads(call.arguments or "{}")
            expression = str(args.get("expression", "")).strip()
            print(f"  执行 python_expr({expression!r})")
            try:
                result = _eval_python_expr(expression)
                payload = json.dumps({"ok": True, "result": result}, ensure_ascii=False)
            except Exception as exc:
                payload = json.dumps(
                    {"ok": False, "error": str(exc)}, ensure_ascii=False
                )
            print(f"  结果: {payload}")
            messages.append(
                ChatMessage(
                    role="tool",
                    content=payload,
                    tool_call_id=call.id,
                    name=call.name,
                )
            )

    print("\n演示结束.")


def main() -> None:
    asyncio.run(_demo_llm_tools_async())


if __name__ == "__main__":
    main()
