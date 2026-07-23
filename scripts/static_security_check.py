"""AST-check Minerva runtime code for prohibited execution and egress surfaces."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

NETWORK_MODULES = {
    "aiohttp",
    "boto3",
    "botocore",
    "ftplib",
    "grpc",
    "http.client",
    "httpx",
    "imaplib",
    "poplib",
    "requests",
    "smtplib",
    "socket",
    "telnetlib",
    "urllib.request",
    "urllib3",
    "websockets",
    "xmlrpc.client",
}
MODEL_MODULES = {
    "anthropic",
    "google.genai",
    "google.generativeai",
    "langchain",
    "langchain_core",
    "litellm",
    "llama_index",
    "mlx",
    "ollama",
    "openai",
    "pydantic_ai",
    "sentence_transformers",
    "tensorflow",
    "torch",
    "transformers",
}
PLUGIN_MODULES = {"entrypoints", "pluggy", "stevedore"}
PROCESS_MODULES = {"commands", "subprocess"}

NETWORK_CALLS = {
    "asyncio.open_connection",
    "http.client.HTTPConnection",
    "http.client.HTTPSConnection",
    "httpx.delete",
    "httpx.get",
    "httpx.head",
    "httpx.options",
    "httpx.patch",
    "httpx.post",
    "httpx.put",
    "httpx.request",
    "httpx.stream",
    "socket.create_connection",
    "urllib.request.urlopen",
}
NETWORK_METHODS = {"create_connection", "create_datagram_endpoint"}
HTTPX_CLIENT_METHODS = {
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "request",
    "send",
    "stream",
}
PROCESS_CALLS = {
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execlpe",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "os.popen",
    "os.spawnl",
    "os.spawnle",
    "os.spawnlp",
    "os.spawnlpe",
    "os.spawnv",
    "os.spawnve",
    "os.spawnvp",
    "os.spawnvpe",
    "os.startfile",
    "os.system",
    "posix.system",
    "pty.spawn",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
    "subprocess.run",
}
DYNAMIC_LOADING_CALLS = {
    "__import__",
    "ctypes.CDLL",
    "ctypes.PyDLL",
    "importlib.__import__",
    "importlib.import_module",
    "importlib.metadata.entry_points",
    "importlib.util.module_from_spec",
    "importlib.util.spec_from_file_location",
    "pkgutil.iter_modules",
    "pkgutil.walk_packages",
    "runpy.run_module",
    "runpy.run_path",
}
DYNAMIC_LOADING_IMPORTS = {
    "importlib.import_module",
    "importlib.metadata.entry_points",
    "importlib.util.module_from_spec",
    "importlib.util.spec_from_file_location",
    "pkgutil.iter_modules",
    "pkgutil.walk_packages",
    "runpy",
}
DYNAMIC_CODE_CALLS = {
    "builtins.compile",
    "builtins.eval",
    "builtins.exec",
    "compile",
    "eval",
    "exec",
}

PROVIDER_IMPORT_ALLOWLIST = {
    "integrations/ai/openai.py": frozenset({"httpx", "openai"}),
    "integrations/ai/anthropic.py": frozenset({"anthropic", "httpx"}),
}


@dataclass(frozen=True, slots=True)
class Violation:
    path: Path
    line: int
    column: int
    code: str
    message: str


def _matches_module(module: str, prohibited: Iterable[str]) -> str | None:
    for candidate in prohibited:
        if module == candidate or module.startswith(f"{candidate}."):
            return candidate
    return None


class PolicyVisitor(ast.NodeVisitor):
    """Resolve imported aliases and inspect exact qualified call targets."""

    def __init__(self, path: Path, *, allowed_imports: Iterable[str] = ()) -> None:
        self.path = path
        self.allowed_imports = frozenset(allowed_imports)
        self.aliases: dict[str, str] = {"__builtins__": "builtins"}
        self.violations: list[Violation] = []
        self._seen: set[tuple[int, int, str, str]] = set()

    def _add(self, node: ast.AST, code: str, message: str) -> None:
        key = (getattr(node, "lineno", 1), getattr(node, "col_offset", 0), code, message)
        if key in self._seen:
            return
        self._seen.add(key)
        self.violations.append(
            Violation(
                path=self.path,
                line=key[0],
                column=key[1] + 1,
                code=code,
                message=message,
            )
        )

    def _check_import(self, node: ast.AST, qualified_name: str) -> None:
        policies = (
            (NETWORK_MODULES, "MIN001", "network client import"),
            (PROCESS_MODULES, "MIN002", "process execution import"),
            (MODEL_MODULES, "MIN004", "model provider/runtime import"),
            (PLUGIN_MODULES, "MIN005", "plugin framework import"),
            (DYNAMIC_LOADING_IMPORTS, "MIN005", "dynamic loading import"),
        )
        for modules, code, label in policies:
            match = _matches_module(qualified_name, modules)
            if match is not None:
                if match in self.allowed_imports:
                    continue
                self._add(node, code, f"{label} is prohibited: {qualified_name}")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(node, alias.name)
            bound_name = alias.asname or alias.name.split(".", maxsplit=1)[0]
            self.aliases[bound_name] = alias.name if alias.asname else bound_name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level or node.module is None:
            return
        self._check_import(node, node.module)
        for alias in node.names:
            if alias.name == "*":
                continue
            qualified_name = f"{node.module}.{alias.name}"
            self._check_import(node, qualified_name)
            self.aliases[alias.asname or alias.name] = qualified_name

    def _qualified_name(self, expression: ast.expr) -> str | None:
        if isinstance(expression, ast.Name):
            return self.aliases.get(expression.id, expression.id)
        if isinstance(expression, ast.Attribute):
            parent = self._qualified_name(expression.value)
            return f"{parent}.{expression.attr}" if parent is not None else None
        if isinstance(expression, ast.Call):
            constructor = self._qualified_name(expression.func)
            if constructor in {"httpx.Client", "httpx.AsyncClient"}:
                return f"{constructor}.instance"
        return None

    def _bind_alias(self, target: ast.expr, value: ast.expr | None) -> None:
        if not isinstance(target, ast.Name):
            return
        if isinstance(value, ast.Call):
            constructor = self._qualified_name(value.func)
            if constructor in {"httpx.Client", "httpx.AsyncClient"}:
                self.aliases[target.id] = f"{constructor}.instance"
                return
        qualified_name = self._qualified_name(value) if value is not None else None
        if qualified_name is None:
            self.aliases.pop(target.id, None)
        else:
            self.aliases[target.id] = qualified_name

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._bind_alias(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._bind_alias(node.target, node.value)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._bind_alias(item.optional_vars, item.context_expr)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._bind_alias(item.optional_vars, item.context_expr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        qualified_name = self._qualified_name(node.func)
        network_method = (
            qualified_name.rsplit(".", maxsplit=1)[-1] if qualified_name is not None else None
        )
        if qualified_name in NETWORK_CALLS or network_method in NETWORK_METHODS:
            self._add(node, "MIN001", f"network client call is prohibited: {qualified_name}")
        if (
            qualified_name is not None
            and qualified_name.startswith(("httpx.Client.instance.", "httpx.AsyncClient.instance."))
            and network_method in HTTPX_CLIENT_METHODS
        ):
            self._add(node, "MIN001", f"direct HTTP client call is prohibited: {qualified_name}")
        if qualified_name in PROCESS_CALLS:
            self._add(node, "MIN002", f"process execution call is prohibited: {qualified_name}")
        if qualified_name in DYNAMIC_CODE_CALLS:
            self._add(node, "MIN003", f"dynamic code execution is prohibited: {qualified_name}")
        if qualified_name in DYNAMIC_LOADING_CALLS:
            self._add(node, "MIN005", f"dynamic loading call is prohibited: {qualified_name}")
        self.generic_visit(node)


def scan_tree(source_root: Path) -> list[Violation]:
    """Return all policy violations in Python files beneath *source_root*."""
    source_root = source_root.resolve()
    if not source_root.is_dir():
        return [Violation(source_root, 1, 1, "MIN000", "runtime source directory is missing")]

    python_files = sorted(source_root.rglob("*.py"))
    if not python_files:
        return [Violation(source_root, 1, 1, "MIN000", "runtime source tree has no Python files")]

    violations: list[Violation] = []
    for path in python_files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            violations.append(Violation(path, 1, 1, "MIN000", f"unable to parse source: {exc}"))
            continue
        relative_path = path.relative_to(source_root).as_posix()
        visitor = PolicyVisitor(
            path,
            allowed_imports=PROVIDER_IMPORT_ALLOWLIST.get(relative_path, ()),
        )
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return sorted(
        violations,
        key=lambda item: (str(item.path), item.line, item.column, item.code, item.message),
    )


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _parser() -> argparse.ArgumentParser:
    default_root = Path(__file__).resolve().parents[1] / "src" / "minerva"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source_root",
        nargs="?",
        type=Path,
        default=default_root,
        help="runtime source tree to inspect (default: src/minerva)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    violations = scan_tree(args.source_root)
    if violations:
        for violation in violations:
            print(
                f"{_display_path(violation.path)}:{violation.line}:{violation.column}: "
                f"{violation.code} {violation.message}",
                file=sys.stderr,
            )
        print(f"static security check failed with {len(violations)} violation(s)", file=sys.stderr)
        return 1

    file_count = len(list(args.source_root.resolve().rglob("*.py")))
    print(f"static security check passed for {file_count} Python file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
