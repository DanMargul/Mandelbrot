#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import io
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

PYTHON_SUFFIXES = frozenset({".py"})
CPP_SUFFIXES = frozenset({".cpp", ".cc", ".cxx", ".hpp", ".h", ".ipp"})
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "build",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "vcpkg_installed",
        "node_modules",
        "data",
    }
)
ALLOWED_COMMENT_PREFIXES = ("# noqa", "# type:", "# pragma", "# SPDX", "#!")


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    kind: str
    text: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.text}"


def is_allowed_python_comment(text: str) -> bool:
    return any(text.startswith(prefix) for prefix in ALLOWED_COMMENT_PREFIXES)


def find_python_comment_violations(path: Path, source: str) -> list[Violation]:
    violations: list[Violation] = []
    readline = io.StringIO(source).readline
    for token in tokenize.generate_tokens(readline):
        if token.type != tokenize.COMMENT:
            continue
        text = token.string.strip()
        if is_allowed_python_comment(text):
            continue
        violations.append(Violation(path, token.start[0], "comment", text))
    return violations


DocumentableNode = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


def docstring_nodes(tree: ast.Module) -> list[DocumentableNode]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def find_python_docstring_violations(path: Path, source: str) -> list[Violation]:
    tree = ast.parse(source)
    violations: list[Violation] = []
    for node in docstring_nodes(tree):
        docstring = ast.get_docstring(node, clean=False)
        if docstring is None:
            continue
        first = node.body[0]
        name = getattr(node, "name", "module")
        violations.append(Violation(path, first.lineno, "docstring", name))
    return violations


def strip_cpp_string_and_char_literals(source: str) -> str:
    result: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        character = source[index]
        if character in ('"', "'"):
            result.append(" ")
            index += 1
            while index < length and source[index] != character:
                index += 2 if source[index] == "\\" else 1
            index += 1
            continue
        result.append(character)
        index += 1
    return "".join(result)


def find_cpp_comment_violations(path: Path, source: str) -> list[Violation]:
    stripped = strip_cpp_string_and_char_literals(source)
    violations: list[Violation] = []
    for line_number, line in enumerate(stripped.splitlines(), start=1):
        if "//" in line or "/*" in line:
            violations.append(Violation(path, line_number, "comment", line.strip()))
    return violations


def find_violations_in_file(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8")
    if path.suffix in PYTHON_SUFFIXES:
        return find_python_comment_violations(path, source) + find_python_docstring_violations(path, source)
    return find_cpp_comment_violations(path, source)


def collect_source_files(root: Path) -> list[Path]:
    checked_suffixes = PYTHON_SUFFIXES | CPP_SUFFIXES
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in checked_suffixes:
            continue
        if any(part in IGNORED_DIRECTORY_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".", type=Path)
    arguments = parser.parse_args()

    violations: list[Violation] = []
    for path in collect_source_files(arguments.root):
        violations.extend(find_violations_in_file(path))

    for violation in violations:
        print(violation.render(), file=sys.stderr)

    if violations:
        print(f"\n{len(violations)} convention violation(s); see docs/conventions.md", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
