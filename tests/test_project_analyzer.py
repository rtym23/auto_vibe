import pytest
from pathlib import Path
from auto_vibe.project_analyzer import ProjectAnalyzer, FileContext, FileSymbol


def test_project_analyzer_creation():
    """Test ProjectAnalyzer can be created."""
    analyzer = ProjectAnalyzer()
    assert analyzer is not None
    assert analyzer.root_path is not None


def test_project_analyzer_find_python_files():
    """Test finding Python files."""
    analyzer = ProjectAnalyzer()
    files = analyzer.find_python_files()
    
    assert isinstance(files, list)
    # Should find at least some Python files in the project
    assert len(files) > 0
    
    # All should be .py files
    for f in files:
        assert f.suffix == ".py"


def test_project_analyzer_analyze_file():
    """Test analyzing a single file."""
    analyzer = ProjectAnalyzer()
    
    # Find a Python file to analyze
    files = analyzer.find_python_files()
    if not files:
        pytest.skip("No Python files found")
    
    file_path = files[0]
    context = analyzer.analyze_file(file_path)
    
    assert isinstance(context, FileContext)
    assert context.path is not None
    # symbols and imports should be lists
    assert isinstance(context.symbols, list)
    assert isinstance(context.imports, list)


def test_project_analyzer_analyze_project():
    """Test analyzing entire project."""
    analyzer = ProjectAnalyzer()
    cache = analyzer.analyze_project()
    
    assert isinstance(cache, dict)
    assert len(cache) > 0
    
    # Check that dependency graph was built
    assert isinstance(analyzer.dependency_graph, dict)


def test_project_analyzer_find_symbol():
    """Test finding symbols."""
    analyzer = ProjectAnalyzer()
    analyzer.analyze_project()
    
    # Search for a common symbol
    results = analyzer.find_symbol("test")
    assert isinstance(results, list)


def test_project_analyzer_get_project_summary():
    """Test getting project summary."""
    analyzer = ProjectAnalyzer()
    summary = analyzer.get_project_summary()
    
    assert isinstance(summary, str)
    assert "Files:" in summary
    assert "Project:" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
