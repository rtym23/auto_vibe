"""
Multi-file context analyzer for AutoVibe.

Analyzes dependencies between project files:
- Imports
- Class/function definitions
- Type hints
- Used for understanding project structure
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class FileSymbol:
    """Symbol (class, function) in a file."""
    name: str
    type: str  # "class", "function", "import"
    line: int
    docstring: Optional[str] = None


@dataclass
class FileContext:
    """Context of a single file."""
    path: str
    symbols: List[FileSymbol] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


class ProjectAnalyzer:
    """
    Project structure analyzer.

    Allows:
    - Finding all Python files in the project
    - Extracting imports and dependencies
    - Finding class and function definitions
    - Building a dependency graph
    """

    def __init__(self, root_path: Optional[str] = None):
        self.root_path = Path(root_path) if root_path else Path.cwd()
        self.file_cache: Dict[str, FileContext] = {}
        self.dependency_graph: Dict[str, Set[str]] = defaultdict(set)

    def find_python_files(self, exclude_dirs: Optional[List[str]] = None) -> List[Path]:
        """Find all Python files in the project."""
        if exclude_dirs is None:
            exclude_dirs = ["__pycache__", ".venv", "venv", ".git", "node_modules", ".pytest_cache"]

        python_files = []
        for path in self.root_path.rglob("*.py"):
            # Check if in excluded directory
            if not any(excl in path.parts for excl in exclude_dirs):
                python_files.append(path)

        return python_files

    def analyze_file(self, file_path: Path) -> FileContext:
        """Analyze a single file."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return FileContext(path=str(file_path))

        context = FileContext(path=str(file_path))

        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            return context

        # Extract symbols
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                docstring = ast.get_docstring(node)
                context.symbols.append(FileSymbol(
                    name=node.name,
                    type="class",
                    line=node.lineno,
                    docstring=docstring
                ))
            elif isinstance(node, ast.FunctionDef):
                docstring = ast.get_docstring(node)
                context.symbols.append(FileSymbol(
                    name=node.name,
                    type="function",
                    line=node.lineno,
                    docstring=docstring
                ))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    context.imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    context.imports.append(node.module)

        return context

    def analyze_project(self) -> Dict[str, FileContext]:
        """Analyze the entire project."""
        python_files = self.find_python_files()

        for file_path in python_files:
            context = self.analyze_file(file_path)
            self.file_cache[str(file_path)] = context

            # Build dependency graph
            for imp in context.imports:
                self.dependency_graph[str(file_path)].add(imp)

        return self.file_cache

    def get_file_dependencies(self, file_path: str) -> List[str]:
        """Get file dependencies."""
        if file_path not in self.file_cache:
            return []
        return self.file_cache[file_path].dependencies

    def find_symbol(self, symbol_name: str) -> List[FileSymbol]:
        """Find a symbol (class/function) by name in all files."""
        results = []

        for context in self.file_cache.values():
            for symbol in context.symbols:
                if symbol.name == symbol_name:
                    results.append(symbol)

        return results

    def get_context_for_file(self, file_path: str, max_files: int = 5) -> str:
        """
        Get context for a file (including dependencies).

        Args:
            file_path: Path to file
            max_files: Maximum number of files to include
        """
        if file_path not in self.file_cache:
            # Analyze file if not yet analyzed
            self.analyze_file(Path(file_path))

        context = self.file_cache.get(file_path)
        if not context:
            return ""

        parts = [f"# File: {file_path}", ""]

        # Add imports
        if context.imports:
            parts.append("# Imports:")
            for imp in context.imports[:10]:  # Limit
                parts.append(f"import {imp}")
            parts.append("")

        # Add definitions
        if context.symbols:
            parts.append("# Definitions:")
            for sym in context.symbols[:20]:  # Limit
                parts.append(f"{sym.type} {sym.name} (line {sym.line})")
            parts.append("")

        # Find dependent files
        related_files = self._find_related_files(file_path, max_files)

        for rel_path in related_files:
            rel_context = self.file_cache.get(rel_path)
            if rel_context and rel_context.symbols:
                parts.append(f"# From {rel_path}:")
                for sym in rel_context.symbols[:5]:
                    parts.append(f"  {sym.type} {sym.name}")

        return "\n".join(parts)

    def _find_related_files(self, file_path: str, max_files: int) -> List[str]:
        """Find related files (using the same modules)."""
        if file_path not in self.file_cache:
            return []

        target_imports = set(self.file_cache[file_path].imports)
        related = []

        for path, context in self.file_cache.items():
            if path == file_path:
                continue

            # Check common imports
            common = set(context.imports) & target_imports
            if common:
                related.append((path, len(common)))

        # Sort by number of common imports
        related.sort(key=lambda x: x[1], reverse=True)

        return [r[0] for r in related[:max_files]]

    def get_project_summary(self) -> str:
        """Get project structure summary."""
        if not self.file_cache:
            self.analyze_project()

        total_files = len(self.file_cache)
        total_classes = sum(
            len([s for s in c.symbols if s.type == "class"])
            for c in self.file_cache.values()
        )
        total_functions = sum(
            len([s for s in c.symbols if s.type == "function"])
            for c in self.file_cache.values()
        )

        lines = [
            f"Project: {self.root_path}",
            f"Files: {total_files}",
            f"Classes: {total_classes}",
            f"Functions: {total_functions}",
            "",
            "Top-level modules:"
        ]

        # Show root modules
        root_modules = set()
        for path in self.file_cache.keys():
            rel = Path(path).relative_to(self.root_path)
            if len(rel.parts) == 1:
                root_modules.add(rel.stem)

        for mod in sorted(root_modules)[:10]:
            lines.append(f"  - {mod}")

        return "\n".join(lines)
