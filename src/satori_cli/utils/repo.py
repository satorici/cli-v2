import re

REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
# git@github.com:owner/repo.git, ssh://git@github.com/owner/repo, https://github.com/owner/repo/
_GITHUB_REMOTE_RE = re.compile(
    r"^(?:(?:https?|ssh|git)://(?:[^@/]+@)?github\.com(?::\d+)?/|(?:[^@/]+@)?github\.com:)"
    r"(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
# Remote scans of every repository of an owner are capped server side
MAX_WILDCARD_REPOSITORIES = 100


def is_github_repo(name: str) -> bool:
    return bool(REPO_RE.fullmatch(name))


def parse_github_remote(url: str) -> str | None:
    """The `owner/repo` of a github.com git remote URL, else None."""
    match = _GITHUB_REMOTE_RE.match(url.strip())
    if not match or not is_github_repo(match["repo"]):
        return None
    return match["repo"]


def wildcard_owner(name: str) -> str | None:
    """The owner of `owner` or `owner/*` (every repository of `owner`), else None."""
    value = name.strip().rstrip("/")
    if value.endswith("/*"):
        value = value[:-2]
    elif "/" in value:
        return None
    return value if OWNER_RE.fullmatch(value) else None


def normalize_repo_target(name: str) -> str:
    """`owner/repo` unchanged; `owner` and `owner/*` both become `owner/*`."""
    if owner := wildcard_owner(name):
        return f"{owner}/*"
    return name


def is_wildcard_repo(name: str | None) -> bool:
    return bool(name) and name.endswith("/*")
