import re
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

from auto_vibe.core.executor import ExecutionResult


class ErrorSeverity(Enum):
    """Error severity level."""
    CRITICAL = "critical"   # Requires immediate fix
    ERROR = "error"         # Execution error
    WARNING = "warning"     # Warning
    INFO = "info"           # Informational


class ErrorCategory(Enum):
    """Error category."""
    SYNTAX = "syntax"           # Syntax error
    RUNTIME = "runtime"         # Runtime error
    LOGIC = "logic"             # Logic error
    SECURITY = "security"       # Security issue
    IMPORT = "import"           # Import error
    TYPE = "type"               # Type error
    RESOURCE = "resource"       # Resource error (file, network)
    UNKNOWN = "unknown"         # Unknown error


class FixComplexity(Enum):
    """Fix complexity."""
    TRIVIAL = 1      # Single change
    SIMPLE = 2       # Few simple changes
    MODERATE = 3     # Requires code understanding
    COMPLEX = 4      # Requires refactoring
    HARD = 5         # Complex rework


# Pattern for Python Traceback - simplified for reliability
_TB_PATTERN = re.compile(r"Traceback \(most recent call last\):", re.MULTILINE)

# Pattern for a single traceback frame
_FRAME_PATTERN = re.compile(
    r'  File "(.*?)", line (\d+)(?:, in (.*?))?\n(.*?)(?=\n  File "|\n\w)',
    re.DOTALL,
)

# Pattern for the final exception line
_EXC_PATTERN = re.compile(r"(\w+(?:Error|Exception|Warning|Failure)): (.*)", re.MULTILINE)

# Pattern for import errors
_IMPORT_PATTERN = re.compile(r"No module named ['\"]([^'\"]+)['\"]")

# Pattern for syntax errors
_SYNTAX_PATTERN = re.compile(r"SyntaxError: (.+)")

# Pattern for attribute errors
_ATTR_PATTERN = re.compile(r"AttributeError: '([^']+)' object has no attribute '([^']+)'")

# Pattern for type errors
_TYPE_PATTERN = re.compile(r"TypeError: (.+)")

# Pattern for name errors (undefined variables)
_NAME_PATTERN = re.compile(r"NameError: name '([^']+)' is not defined")

# Pattern for indentation errors
_INDENT_PATTERN = re.compile(r"IndentationError: (.+)")

# Pattern for module not found
_MODULE_NOT_FOUND_PATTERN = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")


@dataclass
class ErrorAnalysis:
    """Structured error analysis result."""
    error_type: str
    error_message: str
    file_path: Optional[str]
    line_number: Optional[int]
    function_name: Optional[str]
    code_snippet: str
    recommendations: List[str]
    
    # New fields for extended analysis
    severity: ErrorSeverity = ErrorSeverity.ERROR
    category: ErrorCategory = ErrorCategory.UNKNOWN
    fix_complexity: FixComplexity = FixComplexity.SIMPLE
    
    def to_string(self) -> str:
        """Converts analysis to a readable string."""
        severity_label = {
            ErrorSeverity.CRITICAL: "[CRITICAL]",
            ErrorSeverity.ERROR: "[ERROR]",
            ErrorSeverity.WARNING: "[WARN]",
            ErrorSeverity.INFO: "[INFO]",
        }
        
        parts = [
            f"{severity_label.get(self.severity, '[ERR]')} {self.error_type}: {self.error_message}",
            f"   Category: {self.category.value} | Complexity: {self.fix_complexity.name}",
        ]
        
        if self.file_path:
            parts.append(f"   at {self.file_path}:{self.line_number or '?'} in {self.function_name or '?'}")
        
        if self.code_snippet:
            parts.append(f"   -> {self.code_snippet[:200]}")
        
        if self.recommendations:
            parts.append("\nRecommendations:")
            for rec in self.recommendations:
                parts.append(f"  * {rec}")
        
        return "\n".join(parts)
    
    def to_dict(self) -> dict:
        """Converts to dictionary for serialization."""
        return {
            "error_type": self.error_type,
            "error_message": self.error_message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "function_name": self.function_name,
            "severity": self.severity.value,
            "category": self.category.value,
            "fix_complexity": self.fix_complexity.value,
            "recommendations": self.recommendations,
        }


class Analyzer:
    """
    Parses execution output and extracts structured error information.
    Provides fix recommendations.
    """

    def __init__(self):
        # Knowledge base of recommendations for typical errors
        self._recommendations_db = {
            "ImportError": [
                "Install missing module: pip install <module_name>",
                "Check module name spelling",
                "Ensure module is installed in the same environment",
            ],
            "ModuleNotFoundError": [
                "Install module: pip install <module_name>",
                "Check virtual environment",
                "Try import from alternative: from alternative import module",
            ],
            "SyntaxError": [
                "Check brackets and quotes",
                "Ensure indentation is correct",
                "Check colons after def, if, for, while",
            ],
            "IndentationError": [
                "Use 4 spaces for indentation (not tabs)",
                "Check indentation consistency in the file",
                "Python 3 does not allow mixing tabs and spaces",
            ],
            "NameError": [
                "Check that variable is defined before use",
                "Check for typos in variable name",
                "Ensure import is correct",
            ],
            "TypeError": [
                "Check function argument types",
                "Use isinstance() for type checking",
                "Add type conversion: int(), str(), float()",
            ],
            "AttributeError": [
                "Check that object has this attribute",
                "Use hasattr() to check for attribute",
                "Check class documentation",
            ],
            "KeyError": [
                "Check if key exists in dictionary",
                "Use dict.get() for safe access",
                "Add key to dictionary before accessing",
            ],
            "ValueError": [
                "Check valid argument values",
                "Add input validation",
                "Use try/except for handling",
            ],
            "FileNotFoundError": [
                "Check file path is correct",
                "Create file if it does not exist",
                "Check file permissions",
            ],
            "PermissionError": [
                "Check file/directory permissions",
                "Run with administrator rights",
                "Check that file is not open in another program",
            ],
            "ZeroDivisionError": [
                "Add divisor zero check before division",
                "Use conditional: if divisor != 0",
            ],
            "IndexError": [
                "Check index is in valid range",
                "Use len() to check length",
                "Use negative indices carefully",
            ],
            "TimeoutError": [
                "Increase execution timeout",
                "Optimize code for speed",
                "Check network connection",
            ],
            "ConnectionError": [
                "Check network connection",
                "Try reconnecting",
                "Check service URL and port",
            ],
        }

    def analyze_error(self, result: ExecutionResult) -> str | None:
        """
        Parse stderr and extract a clean error description.
        Returns a human-readable error string, or None on success.
        """
        if result.exit_code == 0:
            return None

        stderr = result.stderr.strip()
        stdout = result.stdout.strip()

        # Combine both for richer context
        combined = f"{stderr}\n{stdout}" if stdout else stderr

        if not combined:
            return f"Command failed with exit code {result.exit_code} (no output)"

        # Get full error analysis
        analysis = self.analyze_error_detailed(result)
        
        if analysis:
            return analysis.to_string()
        
        # Fallback: return last 500 chars of combined output
        return combined[-500:]

    def analyze_error_detailed(self, result: ExecutionResult) -> Optional[ErrorAnalysis]:
        """
        Performs detailed error analysis and returns structured result.
        """
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        combined = f"{stderr}\n{stdout}" if stdout else stderr
        
        if not combined:
            return None
        
        # Parse traceback
        parsed = self._parse_traceback_detailed(combined)
        if parsed:
            return parsed
        
        # Try simple error parsing
        exc_match = _EXC_PATTERN.search(combined)
        if exc_match:
            error_type = exc_match.group(1)
            error_message = exc_match.group(2)
            
            # Classify error
            category, severity, complexity = self._classify_error(error_type, error_message)
            
            return ErrorAnalysis(
                error_type=error_type,
                error_message=error_message,
                file_path=None,
                line_number=None,
                function_name=None,
                code_snippet="",
                recommendations=self._get_recommendations(error_type, error_message),
                severity=severity,
                category=category,
                fix_complexity=complexity,
            )
        
        return None

    def _parse_traceback_detailed(self, text: str) -> Optional[ErrorAnalysis]:
        """Extracts structured information from Python traceback."""
        tb_match = _TB_PATTERN.search(text)
        
        if not tb_match:
            # Try simple error pattern
            return self._parse_simple_error(text)
        
        # Parse traceback frames
        frames = _FRAME_PATTERN.findall(tb_match.group(0))
        exc_match = _EXC_PATTERN.search(text)
        
        if not exc_match:
            return None
        
        error_type = exc_match.group(1)
        error_message = exc_match.group(2)
        
        # Get last frame for context
        file_path = None
        line_number = None
        function_name = None
        code_snippet = ""
        
        if frames:
            last_frame = frames[-1]
            file_path = last_frame[0]
            line_number = int(last_frame[1]) if last_frame[1].isdigit() else None
            function_name = last_frame[2] if len(last_frame) > 2 else None
            code_snippet = last_frame[3].strip() if len(last_frame) > 3 else ""
        
        # Classify error
        category, severity, complexity = self._classify_error(error_type, error_message)
        
        return ErrorAnalysis(
            error_type=error_type,
            error_message=error_message,
            file_path=file_path,
            line_number=line_number,
            function_name=function_name,
            code_snippet=code_snippet[:200],  # Limit length
            recommendations=self._get_recommendations(error_type, error_message),
            severity=severity,
            category=category,
            fix_complexity=complexity,
        )

    def _parse_simple_error(self, text: str) -> Optional[ErrorAnalysis]:
        """Parses simple errors without traceback."""
        # Import errors
        import_match = _IMPORT_PATTERN.search(text)
        if import_match:
            module_name = import_match.group(1)
            category, severity, complexity = self._classify_error("ImportError", f"No module named '{module_name}'")
            return ErrorAnalysis(
                error_type="ImportError",
                error_message=f"No module named '{module_name}'",
                file_path=None,
                line_number=None,
                function_name=None,
                code_snippet="",
                recommendations=[
                    f"Install module: pip install {module_name}",
                    "Check virtual environment",
                ],
                severity=severity,
                category=category,
                fix_complexity=complexity,
            )
        
        # Module not found
        module_not_found = _MODULE_NOT_FOUND_PATTERN.search(text)
        if module_not_found:
            module_name = module_not_found.group(1)
            category, severity, complexity = self._classify_error("ModuleNotFoundError", f"No module named '{module_name}'")
            return ErrorAnalysis(
                error_type="ModuleNotFoundError",
                error_message=f"No module named '{module_name}'",
                file_path=None,
                line_number=None,
                function_name=None,
                code_snippet="",
                recommendations=[
                    f"Install module: pip install {module_name}",
                    "Check that you are using the correct environment",
                ],
                severity=severity,
                category=category,
                fix_complexity=complexity,
            )
        
        # Syntax errors
        syntax_match = _SYNTAX_PATTERN.search(text)
        if syntax_match:
            category, severity, complexity = self._classify_error("SyntaxError", syntax_match.group(1))
            return ErrorAnalysis(
                error_type="SyntaxError",
                error_message=syntax_match.group(1),
                file_path=None,
                line_number=None,
                function_name=None,
                code_snippet="",
                recommendations=self._recommendations_db.get("SyntaxError", []),
                severity=severity,
                category=category,
                fix_complexity=complexity,
            )
        
        # Indentation errors
        indent_match = _INDENT_PATTERN.search(text)
        if indent_match:
            category, severity, complexity = self._classify_error("IndentationError", indent_match.group(1))
            return ErrorAnalysis(
                error_type="IndentationError",
                error_message=indent_match.group(1),
                file_path=None,
                line_number=None,
                function_name=None,
                code_snippet="",
                recommendations=self._recommendations_db.get("IndentationError", []),
                severity=severity,
                category=category,
                fix_complexity=complexity,
            )
        
        # Name errors
        name_match = _NAME_PATTERN.search(text)
        if name_match:
            var_name = name_match.group(1)
            category, severity, complexity = self._classify_error("NameError", f"name '{var_name}' is not defined")
            return ErrorAnalysis(
                error_type="NameError",
                error_message=f"name '{var_name}' is not defined",
                file_path=None,
                line_number=None,
                function_name=None,
                code_snippet="",
                recommendations=[
                    f"Define variable '{var_name}' before use",
                    "Check for typos in variable name",
                ],
                severity=severity,
                category=category,
                fix_complexity=complexity,
            )
        
        # Type errors
        type_match = _TYPE_PATTERN.search(text)
        if type_match:
            category, severity, complexity = self._classify_error("TypeError", type_match.group(1))
            return ErrorAnalysis(
                error_type="TypeError",
                error_message=type_match.group(1),
                file_path=None,
                line_number=None,
                function_name=None,
                code_snippet="",
                recommendations=self._recommendations_db.get("TypeError", []),
                severity=severity,
                category=category,
                fix_complexity=complexity,
            )
        
        # Attribute errors
        attr_match = _ATTR_PATTERN.search(text)
        if attr_match:
            obj_type = attr_match.group(1)
            attr_name = attr_match.group(2)
            category, severity, complexity = self._classify_error("AttributeError", f"'{obj_type}' object has no attribute '{attr_name}'")
            return ErrorAnalysis(
                error_type="AttributeError",
                error_message=f"'{obj_type}' object has no attribute '{attr_name}'",
                file_path=None,
                line_number=None,
                function_name=None,
                code_snippet="",
                recommendations=[
                    f"Check that object type {obj_type} has attribute {attr_name}",
                    "Maybe need to use different method or attribute",
                ],
                severity=severity,
                category=category,
                fix_complexity=complexity,
            )
        
        return None

    def _get_recommendations(self, error_type: str, error_message: str) -> List[str]:
        """
        Returns fix recommendations based on error type.
        """
        # Base recommendations from knowledge base
        recommendations = self._recommendations_db.get(error_type, [
            "Check documentation for this error",
            "Search for solution online",
        ])
        
        # Specific recommendations based on error message
        error_lower = error_message.lower()
        
        # Additional recommendations for specific cases
        if "pip" in error_lower or "install" in error_lower:
            recommendations.append("Try: pip install --upgrade <package>")
        
        if "none" in error_lower and "none" in error_lower:
            recommendations.append("Check that value is not None before use")
        
        if "string" in error_lower or "str" in error_lower:
            recommendations.append("Use str() to convert to string")
        
        if "int" in error_lower or "integer" in error_lower:
            recommendations.append("Use int() to convert to integer")
        
        return recommendations[:5]  # Limit number of recommendations
    
    def _classify_error(self, error_type: str, error_message: str) -> tuple[ErrorCategory, ErrorSeverity, FixComplexity]:
        """
        Classifies error by category, severity, and fix complexity.
        
        Returns:
            (category, severity, complexity)
        """
        error_lower = error_message.lower()
        
        # Determine category
        if error_type in ("SyntaxError", "IndentationError"):
            category = ErrorCategory.SYNTAX
        elif error_type in ("ImportError", "ModuleNotFoundError"):
            category = ErrorCategory.IMPORT
        elif error_type in ("TypeError", "NameError", "AttributeError"):
            category = ErrorCategory.TYPE
        elif error_type in ("ValueError", "KeyError", "IndexError"):
            category = ErrorCategory.RUNTIME
        elif error_type in ("SecurityError",):
            category = ErrorCategory.SECURITY
        elif error_type in ("FileNotFoundError", "PermissionError", "TimeoutError", "ConnectionError"):
            category = ErrorCategory.RESOURCE
        else:
            category = ErrorCategory.UNKNOWN
        
        # Determine severity
        if error_type in ("SyntaxError", "IndentationError"):
            severity = ErrorSeverity.CRITICAL  # Without fix, code will not run
        elif error_type in ("ModuleNotFoundError", "ImportError"):
            severity = ErrorSeverity.ERROR
        elif error_type in ("SecurityError",):
            severity = ErrorSeverity.CRITICAL
        elif error_type in ("TimeoutError", "ConnectionError"):
            severity = ErrorSeverity.WARNING
        else:
            severity = ErrorSeverity.ERROR
        
        # Determine fix complexity
        if error_type in ("SyntaxError", "IndentationError"):
            complexity = FixComplexity.TRIVIAL
        elif error_type in ("NameError", "KeyError", "IndexError"):
            complexity = FixComplexity.SIMPLE
        elif error_type in ("TypeError", "AttributeError"):
            complexity = FixComplexity.MODERATE
        elif error_type in ("ImportError", "ModuleNotFoundError"):
            complexity = FixComplexity.SIMPLE
        else:
            complexity = FixComplexity.MODERATE
        
        # Adjust by message context
        if "recursive" in error_lower or "infinite" in error_lower:
            complexity = FixComplexity.COMPLEX
            severity = ErrorSeverity.CRITICAL
        
        return category, severity, complexity

    def analyze_output(self, result: ExecutionResult) -> str:
        """
        Analyzes stdout for useful information.
        """
        return result.stdout

    async def search_online(self, error_msg: str, num_results: int = 3) -> List[str]:
        """
        Searches for solutions to error online.
        
        Args:
            error_msg: Error message
            num_results: Number of results
            
        Returns:
            List of found solutions
        """
        try:
            from auto_vibe.integrations.web_search import DuckDuckGoSearcher
            searcher = DuckDuckGoSearcher()
            results = await searcher.search(error_msg, num_results=num_results)
            return [f"{r.title}: {r.snippet}" for r in results]
        except Exception as e:
            return [f"Could not find solutions: {e}"]
