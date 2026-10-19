import re

REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def is_github_repo(name: str) -> bool:
    return bool(REPO_RE.fullmatch(name))
