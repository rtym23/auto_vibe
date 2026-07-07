"""
Git integration for AutoVibe.

Features:
- Show diff of changes
- Create commits
- Show change history
- Branching
- Semantic Commits (conventional commits)
- PR Preparation
- Automated Rollback
- Checkpoint management
"""

import subprocess
import re
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class CommitType(Enum):
    """Commit types by conventional commits."""
    FEAT = "feat"      # New functionality
    FIX = "fix"        # Bug fix
    DOCS = "docs"      # Documentation
    STYLE = "style"    # Formatting
    REFACTOR = "refactor"  # Refactoring
    TEST = "test"      # Tests
    CHORE = "chore"    # Maintenance
    PERF = "perf"      # Performance
    CI = "ci"          # CI/CD


@dataclass
class GitDiff:
    """Git diff result."""
    files_changed: int
    insertions: int
    deletions: int
    diff_text: str


@dataclass
class BranchInfo:
    """Branch information."""
    name: str
    is_current: bool
    last_commit: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Checkpoint:
    """Checkpoint for rollback."""
    commit_hash: str
    message: str
    timestamp: str
    branch: str
    files: List[str] = field(default_factory=list)


@dataclass
class PRDescription:
    """Pull Request description."""
    title: str
    body: str
    base_branch: str
    head_branch: str
    reviewers: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)


class GitManager:
    """
    Git operations manager.

    Features:
    - Branch creation for each task
    - Semantic Commits
    - PR Preparation
    - Automated Rollback
    """

    def __init__(self, repo_path: Optional[str] = None):
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()
        self._checkpoints: List[Checkpoint] = []

    def _run_git(self, args: List[str], timeout: int = 30) -> tuple[str, str, int]:
        """Execute a git command."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        except FileNotFoundError:
            return "", "git not found", 1
        except subprocess.TimeoutExpired:
            return "", "git command timed out", 1
        except Exception as e:
            return "", str(e), 1

    def is_git_repo(self) -> bool:
        """Check if directory is a git repository."""
        _, _, code = self._run_git(["rev-parse", "--git-dir"])
        return code == 0

    # === Branch Management ===

    def get_current_branch(self) -> Optional[str]:
        """Get current branch."""
        stdout, _, code = self._run_git(["branch", "--show-current"])
        return stdout.strip() if code == 0 else None

    def get_all_branches(self) -> List[BranchInfo]:
        """Get all branches."""
        stdout, _, code = self._run_git(["branch", "-a"])
        if code != 0:
            return []

        branches = []

        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            is_current = line.startswith("*")
            name = line.lstrip("* ").strip()

            if name and not name.startswith("remotes/"):
                branches.append(BranchInfo(
                    name=name,
                    is_current=is_current,
                ))

        return branches

    def create_branch(self, branch_name: str, switch: bool = True) -> bool:
        """
        Create a new branch.

        Args:
            branch_name: Branch name
            switch: Switch to branch after creation

        Returns:
            True if successful
        """
        # Check that branch does not exist
        existing = self.get_all_branches()
        if any(b.name == branch_name for b in existing):
            # Branch already exists
            if switch:
                stdout, _, code = self._run_git(["checkout", branch_name])
                return code == 0
            return True

        # Create branch
        stdout, stderr, code = self._run_git(["checkout", "-b", branch_name])
        return code == 0

    def switch_branch(self, branch_name: str) -> bool:
        """Switch to a branch."""
        stdout, _, code = self._run_git(["checkout", branch_name])
        return code == 0

    def delete_branch(self, branch_name: str, force: bool = False) -> bool:
        """Delete a branch."""
        flag = "-D" if force else "-d"
        stdout, _, code = self._run_git(["branch", flag, branch_name])
        return code == 0

    def create_task_branch(self, task_name: str) -> str:
        """
        Create a branch for a task with an auto-generated name.

        Args:
            task_name: Task name

        Returns:
            Name of the created branch
        """
        # Format branch name
        sanitized = re.sub(r'[^\w-]', '-', task_name.lower())
        sanitized = re.sub(r'-+', '-', sanitized).strip('-')
        branch_name = f"feature/{sanitized}"

        # Create branch
        self.create_branch(branch_name, switch=True)

        return branch_name

    # === Diff & Status ===

    def get_diff(self, staged: bool = False, file_path: Optional[str] = None) -> Optional[GitDiff]:
        """
        Get diff of changes.

        Args:
            staged: Show staged changes
            file_path: Path to specific file
        """
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file_path:
            args.append("--")
            args.append(file_path)

        stdout, stderr, code = self._run_git(args)

        if code != 0 and "not a git repository" in stderr.lower():
            return None

        # Count changes
        files_changed = len([line for line in stdout.split("\n") if line.startswith("diff ")])
        insertions = stdout.count("+") - stdout.count("++")
        deletions = stdout.count("-") - stdout.count("--")

        return GitDiff(
            files_changed=max(files_changed, 1) if stdout else 0,
            insertions=insertions,
            deletions=deletions,
            diff_text=stdout
        )

    def get_status(self) -> Dict[str, List[str]]:
        """Get git status."""
        stdout, _, code = self._run_git(["status", "--porcelain"])

        if code != 0:
            return {}

        status = {"modified": [], "staged": [], "untracked": []}
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            status_code = line[:2]
            file_path = line[3:]

            if status_code[0] == "?":
                status["untracked"].append(file_path)
            elif status_code[0] == "M":
                status["modified"].append(file_path)
            if status_code[1] == "M":
                status["staged"].append(file_path)

        return status

    # === Staging & Committing ===

    def add_file(self, file_path: str) -> bool:
        """Add file to staging."""
        stdout, stderr, code = self._run_git(["add", file_path])
        return code == 0

    def add_all(self) -> bool:
        """Add all changes to staging."""
        stdout, stderr, code = self._run_git(["add", "-A"])
        return code == 0

    def commit(self, message: str) -> bool:
        """Create a commit."""
        stdout, stderr, code = self._run_git(["commit", "-m", message])
        return code == 0

    def create_semantic_commit(
        self,
        commit_type: CommitType,
        message: str,
        scope: Optional[str] = None,
        breaking: bool = False,
    ) -> bool:
        """
        Create a commit following conventional commits.

        Args:
            commit_type: Commit type (feat, fix, etc.)
            message: Commit message
            scope: Scope (optional)
            breaking: Breaking change

        Returns:
            True if successful
        """
        scope_part = f"({scope})" if scope else ""
        breaking_part = "!" if breaking else ""

        full_message = f"{commit_type.value}{scope_part}{breaking_part}: {message}"

        return self.commit(full_message)

    def auto_commit_changes(self, task_description: str) -> bool:
        """
        Automatically determines commit type and creates it.

        Args:
            task_description: Task description

        Returns:
            True if successful
        """
        status = self.get_status()

        total_changes = (
            len(status.get("modified", [])) +
            len(status.get("untracked", []))
        )
        if total_changes == 0:
            return False

        commit_type = CommitType.CHORE

        all_files = status.get("modified", []) + status.get("untracked", [])

        if any("test" in f.lower() for f in all_files):
            commit_type = CommitType.TEST
        elif any(f.endswith(".md") for f in all_files):
            commit_type = CommitType.DOCS
        elif any("fix" in task_description.lower() or "bug" in task_description.lower() for _ in all_files):
            commit_type = CommitType.FIX
        elif any("refactor" in task_description.lower() for _ in all_files):
            commit_type = CommitType.REFACTOR
        else:
            commit_type = CommitType.FEAT

        return self.create_semantic_commit(commit_type, task_description)

    # === Checkpoints & Rollback ===

    def create_checkpoint(self, message: str) -> Optional[Checkpoint]:
        """
        Creates a checkpoint for possible rollback.

        Args:
            message: Checkpoint description

        Returns:
            Checkpoint information
        """
        stdout, _, code = self._run_git(["rev-parse", "HEAD"])
        if code != 0:
            return None

        commit_hash = stdout.strip()
        branch = self.get_current_branch() or "unknown"

        status = self.get_status()
        files = status.get("modified", []) + status.get("untracked", [])

        checkpoint = Checkpoint(
            commit_hash=commit_hash,
            message=message,
            timestamp=datetime.now().isoformat(),
            branch=branch,
            files=files,
        )

        self._checkpoints.append(checkpoint)
        return checkpoint

    def rollback_to_checkpoint(self, checkpoint: Checkpoint) -> bool:
        """
        Rolls back to a checkpoint.

        Args:
            checkpoint: Checkpoint to roll back to

        Returns:
            True if successful
        """
        if checkpoint.branch != self.get_current_branch():
            if not self.switch_branch(checkpoint.branch):
                return False

        stdout, _, code = self._run_git(["reset", "--hard", checkpoint.commit_hash])
        return code == 0

    def rollback_last_commit(self) -> bool:
        """Roll back the last commit."""
        stdout, _, code = self._run_git(["reset", "--hard", "HEAD~1"])
        return code == 0

    def get_last_commit(self) -> Optional[Dict[str, str]]:
        """Get information about the last commit."""
        stdout, _, code = self._run_git(["log", "-1", "--format=%H|%s|%an|%ad", "--date=short"])

        if code != 0 or not stdout:
            return None

        parts = stdout.strip().split("|")
        if len(parts) >= 4:
            return {
                "hash": parts[0],
                "message": parts[1],
                "author": parts[2],
                "date": parts[3]
            }
        return None

    # === PR Preparation ===

    def prepare_pr(
        self,
        title: str,
        description: str,
        base_branch: str = "main",
    ) -> PRDescription:
        """
        Prepares a Pull Request description.

        Args:
            title: PR title
            description: Change description
            base_branch: Branch to merge into

        Returns:
            PRDescription with prepared text
        """
        head_branch = self.get_current_branch()

        diff = self.get_diff()

        body_parts = [
            description,
            "",
            "---",
            "",
            "### Changes",
        ]

        if diff:
            body_parts.append(f"- Files changed: {diff.files_changed}")
            body_parts.append(f"- Insertions: +{diff.insertions}")
            body_parts.append(f"- Deletions: -{diff.deletions}")

        body_parts.extend([
            "",
            "### Summary",
            self._generate_summary(),
        ])

        return PRDescription(
            title=title,
            body="\n".join(body_parts),
            base_branch=base_branch,
            head_branch=head_branch or "",
        )

    def _generate_summary(self) -> str:
        """Generates a brief summary of changes."""
        status = self.get_status()

        parts = []

        if status.get("modified"):
            parts.append(f"Modified: {', '.join(status['modified'][:5])}")
        if status.get("untracked"):
            parts.append(f"Added: {', '.join(status['untracked'][:5])}")

        return "\n".join(parts) if parts else "No files changed"

    def get_pr_command(self, pr_description: PRDescription) -> str:
        """
        Returns command to create a PR (gh CLI).

        Args:
            pr_description: Prepared PR description

        Returns:
            Command to create PR
        """
        title_escaped = pr_description.title.replace('"', '\\"')
        body_escaped = pr_description.body.replace('"', '\\"').replace('\n', '\\n')

        return (
            f'gh pr create --title "{title_escaped}" '
            f'--body "{body_escaped}" '
            f'--base {pr_description.base_branch}'
        )

    # === Utility Methods ===

    def format_diff_summary(self, diff: Optional[GitDiff]) -> str:
        """Format diff summary."""
        if diff is None:
            return "Not a git repository"

        if diff.files_changed == 0:
            return "No changes"

        lines = [
            f"Files changed: {diff.files_changed}",
            f"Insertions: {diff.insertions}",
            f"Deletions: {diff.deletions}",
            "",
            "--- Diff ---",
            diff.diff_text[:2000] + ("..." if len(diff.diff_text) > 2000 else "")
        ]

        return "\n".join(lines)

    def get_commit_history(self, count: int = 10) -> List[Dict[str, str]]:
        """Get commit history."""
        stdout, _, code = self._run_git([
            "log",
            f"-n{count}",
            "--format=%H|%s|%an|%ad",
            "--date=short"
        ])

        if code != 0:
            return []

        commits = []
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "date": parts[3]
                })

        return commits


# === Convenience Functions ===

def create_task_branch_and_commit(
    task_name: str,
    commit_message: str,
    repo_path: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Creates a branch, makes a commit and returns the result.

    Args:
        task_name: Task name
        commit_message: Commit message
        repo_path: Repository path

    Returns:
        (success, branch_name)
    """
    gm = GitManager(repo_path)

    branch_name = gm.create_task_branch(task_name)

    gm.add_all()

    success = gm.commit(commit_message)

    return success, branch_name
