import glob
import os
import re
import subprocess
import sys
import tempfile

OUT_DIR = "self-code-review"
SNAPSHOT_HEAD_BYTES = 4000
SNAPSHOT_RE = re.compile(r'<meta name="scr-snapshot" content="([0-9a-f]{40,64})">')
BASE_CANDIDATES = ("origin/HEAD", "origin/main", "origin/master", "main", "master")
LAST_REPORT = "last"


def git(repo, *args, check=True, env=None):
    result = subprocess.run(["git", "-c", "core.quotepath=false", "-C", repo, *args],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env)
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def has_commits(repo):
    return bool(git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).strip())


def base_tree(repo):
    if has_commits(repo):
        return "HEAD"
    return git(repo, "hash-object", "-t", "tree", os.devnull).strip()


def snapshot_tree(repo, extra_excludes=()):
    with tempfile.TemporaryDirectory() as temp_dir:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(temp_dir, "index")}
        git(repo, "read-tree", base_tree(repo), env=env)
        excludes = [f":(exclude){path}" for path in (OUT_DIR, *extra_excludes)]
        git(repo, "add", "-A", "--", ".", *excludes, env=env)
        return git(repo, "write-tree", env=env).strip()


def detect_base(repo):
    head = git(repo, "rev-parse", "HEAD").strip()
    for ref in BASE_CANDIDATES:
        if not git(repo, "rev-parse", "--verify", "-q", ref, check=False).strip():
            continue
        merge_base = git(repo, "merge-base", ref, "HEAD", check=False).strip()
        if merge_base and merge_base != head:
            return ref
    return None


def latest_report(repo):
    reports = glob.glob(os.path.join(repo, OUT_DIR, "*", "*.html"))
    if not reports:
        sys.exit("--since last: no previous report found.")
    return max(reports, key=os.path.getmtime)


def report_snapshot(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        match = SNAPSHOT_RE.search(handle.read(SNAPSHOT_HEAD_BYTES))
    if not match:
        sys.exit(f"{path} has no snapshot marker; was it made by this tool?")
    return match.group(1)


def resolve_since(repo, since):
    report = latest_report(repo) if since == LAST_REPORT else since
    if os.path.isfile(report):
        return report_snapshot(report), f"changes since {os.path.basename(report)}"

    tree = git(repo, "rev-parse", "--verify", f"{since}^{{tree}}", check=False).strip()
    if not tree:
        sys.exit(f"--since: '{since}' is not 'last', a report file, or a tree-ish.")
    return tree, f"changes since {since}"
