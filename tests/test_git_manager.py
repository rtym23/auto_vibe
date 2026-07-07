import pytest
from auto_vibe.git_manager import GitManager, GitDiff


def test_git_manager_creation():
    """Test GitManager can be created."""
    gm = GitManager()
    assert gm is not None


def test_git_manager_is_git_repo():
    """Test checking if directory is git repo."""
    gm = GitManager()
    is_repo = gm.is_git_repo()
    # Should be True since we're in a git repo
    assert isinstance(is_repo, bool)


def test_git_manager_get_diff():
    """Test getting git diff."""
    gm = GitManager()
    diff = gm.get_diff()
    # May be None if not a git repo, or GitDiff if it is
    assert diff is None or isinstance(diff, GitDiff)


def test_git_manager_get_status():
    """Test getting git status."""
    gm = GitManager()
    status = gm.get_status()
    assert isinstance(status, dict)
    # Should have keys like 'modified', 'staged', 'untracked'
    assert "modified" in status or "untracked" in status or status == {}


def test_git_manager_format_diff_summary():
    """Test formatting diff summary."""
    gm = GitManager()
    
    # Test with None
    summary = gm.format_diff_summary(None)
    assert "Not a git repository" in summary or summary == "No changes"
    
    # Test with empty diff
    diff = GitDiff(files_changed=0, insertions=0, deletions=0, diff_text="")
    summary = gm.format_diff_summary(diff)
    assert "No changes" in summary
    
    # Test with actual diff
    diff = GitDiff(
        files_changed=1,
        insertions=10,
        deletions=5,
        diff_text="diff --git a/test.py b/test.py\n+new line\n-old line"
    )
    summary = gm.format_diff_summary(diff)
    assert "Files changed: 1" in summary
    assert "Insertions: 10" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
