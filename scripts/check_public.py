#!/usr/bin/env python3
"""Privacy check for this public repo, run by the hooks in scripts/hooks. Enable them once per clone:
`git config core.hooksPath scripts/hooks` (only in the public clone, never in the private repo).

Blocks a commit or push that would publish:
- an author or committer email that is not a GitHub noreply address;
- anything under private/ (personal notes, tracked only in the private repo);
- an email address (other than noreply ones) or an absolute home or drive path, in added lines,
  file names or commit messages;
- a match from private/denylist.txt (one case-insensitive regex per line) or a source file name
  from batkol/sources_local.py.
Lines that mention the user are listed for a second look, not blocked.

  python3 scripts/check_public.py pre-commit
  python3 scripts/check_public.py commit-msg MSG_FILE
  python3 scripts/check_public.py pre-push REMOTE [URL] < refs     (as git calls it)
  python3 scripts/check_public.py scan [--history]                 (every tracked file; every commit)
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

ZERO = "0" * 40
AUTHOR_OK = re.compile(r"@users\.noreply\.github\.com$", re.I)
EMAIL_OK = re.compile(r"@users\.noreply\.github\.com$|^noreply@(anthropic|github)\.com$", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PATH = re.compile(r"/home/\w|/Users/\w|/mnt/[a-z]/\w|\b[A-Za-z]:\\[\w .-]+\\|\b[A-Za-z]:/[\w .-]+/")
USER = re.compile(r"\bthe user\b|\buser's\b", re.I)
MEDIA = re.compile(r".+\.(?:opus|m4b|m4a|mp3|wav|flac|ogg|aac|epub)", re.I)


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


ROOT = Path(git("rev-parse", "--show-toplevel").strip())


def private_patterns():
    """private/denylist.txt, plus the file names of the sources (string constants in sources_local.py),
    except generic ones that the public sources_local.example.py also uses."""
    pats, notes = [], []
    deny = ROOT / "private" / "denylist.txt"
    if deny.exists():
        for line in deny.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                pats.append(re.compile(line.strip(), re.I))
    else:
        notes.append("no private/denylist.txt in this clone: only the generic checks ran")
    src, example = ROOT / "batkol" / "sources_local.py", ROOT / "batkol" / "sources_local.example.py"
    public = example.read_text(encoding="utf-8").lower() if example.exists() else ""
    if src.exists():
        for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                name = re.split(r"[/\\]", node.value)[-1].strip()
                if MEDIA.fullmatch(name) and name.lower() not in public:
                    pats.append(re.compile(re.escape(name), re.I))
    return pats, notes


class Check:
    def __init__(self):
        self.deny, self.notes = private_patterns()
        self.hits, self.review = [], []

    def text(self, where, s):
        for m in EMAIL.finditer(s):
            if not EMAIL_OK.search(m.group()):
                self.hits.append(f"{where}: email address {m.group()}")
        if PATH.search(s):
            self.hits.append(f"{where}: absolute home or drive path: {s.strip()[:100]}")
        if any(p.search(s) for p in self.deny):
            self.hits.append(f"{where}: private detail (denylist or source file name): {s.strip()[:100]}")
        if USER.search(s):
            self.review.append(f"{where}: {s.strip()[:100]}")

    def path(self, where, p):
        if p == "private" or p.startswith("private/"):
            self.hits.append(f"{where}{p}: private/ stays out of this repo")
        self.text(f"{where}{p} (file name)", p)

    def identity(self, where, author, committer):
        if not AUTHOR_OK.search(author):
            self.hits.append(f"{where}author email {author}: use the GitHub noreply address")
        if not (AUTHOR_OK.search(committer) or committer.lower() == "noreply@github.com"):
            self.hits.append(f"{where}committer email {committer}: use the GitHub noreply address")

    def diff(self, where, patch):
        f, n = "?", 0
        for line in patch.splitlines():
            if line.startswith("+++ "):
                f = line[6:] if line.startswith("+++ b/") else line[4:]
            elif line.startswith("@@"):
                n = int(re.search(r"\+(\d+)", line).group(1)) - 1
            elif line.startswith("+"):
                n += 1
                self.text(f"{where}{f}:{n}", line[1:])

    def commit(self, c):
        author, committer, msg = git("log", "-1", "--format=%ae%x00%ce%x00%B", c).split("\x00", 2)
        where = f"commit {c[:7]}: "
        self.identity(where, author, committer)
        for i, line in enumerate(msg.splitlines(), 1):
            self.text(f"{where}message:{i}", line)
        for p in git("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", c).splitlines():
            self.path(where, p)
        self.diff(where, git("show", "--format=", "-U0", "--no-color", "--no-ext-diff", c))

    def report(self, what):
        for n in self.notes:
            print(f"privacy check: {n}", file=sys.stderr)
        if self.review:
            print("privacy check: lines that mention the user (not blocked; have a second look):", file=sys.stderr)
            for r in self.review[:20]:
                print(f"  {r}", file=sys.stderr)
        if not self.hits:
            return 0
        print(f"privacy check: {what} BLOCKED", file=sys.stderr)
        for h in self.hits:
            print(f"  {h}", file=sys.stderr)
        print("Move personal details to private/ (or fix the identity), or ask the user. Never bypass this hook.",
              file=sys.stderr)
        return 1


def main(argv):
    mode = argv[1] if len(argv) > 1 else "scan"
    ck = Check()
    if mode == "pre-commit":
        ident = [re.search(r"<([^>]*)>", git("var", v)).group(1) for v in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT")]
        ck.identity("", *ident)
        for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines():
            ck.path("staged ", p)
        ck.diff("", git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff"))
        return ck.report("commit")
    if mode == "commit-msg":
        for i, line in enumerate(Path(argv[2]).read_text(encoding="utf-8").splitlines(), 1):
            if not line.startswith("#"):
                ck.text(f"commit message:{i}", line)
        return ck.report("commit")
    if mode == "pre-push":
        remote = argv[2] if len(argv) > 2 else "origin"
        for line in sys.stdin:
            parts = line.split()
            if len(parts) != 4 or parts[1] == ZERO:
                continue
            local, theirs = parts[1], parts[3]
            known = theirs != ZERO and subprocess.run(["git", "cat-file", "-e", f"{theirs}^{{commit}}"],
                                                      capture_output=True).returncode == 0
            rng = [f"{theirs}..{local}"] if known else [local, "--not", f"--remotes={remote}"]
            for c in git("rev-list", *rng).split():
                ck.commit(c)
        return ck.report("push")
    if mode == "scan":
        for p in git("ls-files").splitlines():
            ck.path("", p)
            f = ROOT / p
            if f.is_file() and not f.is_symlink():
                try:
                    lines = f.read_text(encoding="utf-8").splitlines()
                except UnicodeDecodeError:
                    continue
                for i, line in enumerate(lines, 1):
                    ck.text(f"{p}:{i}", line)
        if "--history" in argv:
            for c in git("rev-list", "--all").split():
                ck.commit(c)
        return ck.report("scan")
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
