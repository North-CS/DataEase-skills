from __future__ import annotations

from typing import Any


def flatten_tree(nodes: list[dict[str, Any]] | None, *, leaves_only: bool = False) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def visit(items: list[dict[str, Any]], parent_path: list[str]) -> None:
        for item in items:
            current_path = [*parent_path, str(item.get("name") or "")]
            children = item.get("children") or []
            is_leaf = bool(item.get("leaf")) or not children
            if is_leaf or not leaves_only:
                normalized = dict(item)
                normalized["path"] = "/".join(part for part in current_path if part)
                normalized.pop("children", None)
                result.append(normalized)
            if isinstance(children, list):
                visit(children, current_path)

    visit(nodes or [], [])
    return result
