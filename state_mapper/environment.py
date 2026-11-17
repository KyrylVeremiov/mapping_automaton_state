"""Environment checks, so that the program works on any machine.

ensure_requirements()  reads requirements.txt, checks that every package is installed in a suitable
                       version and installs what is missing with pip.  If a normal installation is not
                       possible (no permission, "externally managed" system Python, ...), the packages
                       are installed into the project folder ``.vendor`` and used from there.
find_dot()             finds the Graphviz ``dot`` program: GRAPHVIZ_DOT, the PATH, and - if it is not on
                       the PATH - the standard install folders (on Windows e.g.
                       C:\\Program Files\\Graphviz\\bin, also versioned folders such as "Graphviz 2.38",
                       C:\\Program Files (x86), %LOCALAPPDATA%\\Programs, Chocolatey, Scoop).
environment_report()   what a person needs to know to fix a problem (printed by --check-env).

Graphviz is a program, not a Python package, so it is only detected, never installed silently:
install_hint() says how to install it on the current system.
"""
from __future__ import annotations

import glob
import importlib
import importlib.metadata
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
VENDOR = ROOT / ".vendor"                 # target of the fallback "pip install --target"
SKIP_ENV = "STATE_MAPPER_SKIP_INSTALL"    # set to 1 to switch automatic installation off
DOT_ENV = "GRAPHVIZ_DOT"                  # full path of dot, overrides the search
MIN_PYTHON = (3, 8)


# ------------------------------------------------------------------ Python packages
@dataclass(frozen=True)
class Requirement:
    name: str
    op: str            # '', '>=', '==', ...
    version: str
    spec: str          # the text given to pip, e.g. 'Pillow>=9.0.0'


_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.\-]*)\s*(?:(>=|<=|==|!=|~=|>|<)\s*([0-9][0-9A-Za-z.\-+*]*))?$")


def parse_requirements(text: str) -> list:
    """Lines like 'Pillow>=9.0.0'; comments, blank lines and pip options (-r, -i, ...) are skipped."""
    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _REQ.match(line.replace(" ", ""))
        if m:
            out.append(Requirement(m.group(1), m.group(2) or "", m.group(3) or "", line.replace(" ", "")))
        else:                                   # something pip understands but we cannot check
            out.append(Requirement(line, "", "", line))
    return out


def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v.split("+")[0]))


def _cmp(a: tuple, b: tuple) -> int:
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def installed_version(name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def satisfied(req: Requirement) -> bool:
    """Is the package installed in a version that fits the requirement?"""
    have = installed_version(req.name)
    if have is None:
        return False
    if not req.op or not req.version or "*" in req.version:
        return True
    c = _cmp(_vtuple(have), _vtuple(req.version))
    return {">=": c >= 0, "~=": c >= 0, "==": c == 0, "!=": c != 0,
            ">": c > 0, "<=": c <= 0, "<": c < 0}[req.op]


def use_vendor(vendor: Optional[Path] = None) -> None:
    """Make packages installed into .vendor importable (they win over older system copies)."""
    vendor = Path(vendor or VENDOR)
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    importlib.invalidate_caches()


def _run_pip(cmd: list, out=print) -> bool:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        text = (proc.stderr or "") + (proc.stdout or "")
        if "externally-managed" in text or "externally managed" in text:
            out("    (this Python is managed by the operating system, pip refuses to change it - PEP 668)")
        else:
            tail = text.strip().splitlines()[-3:]
            out("    pip said: " + " | ".join(t.strip() for t in tail if t.strip()))
    return proc.returncode == 0


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit("state_mapper needs Python %d.%d or newer (this is %s)"
                         % (MIN_PYTHON + (sys.version.split()[0],)))


def ensure_requirements(requirements=None, *, skip=None, out=print, runner=None, check=satisfied,
                        vendor=None, force_target=False) -> bool:
    """Check requirements.txt and install what is missing.  Returns True if everything is available.

    Never raises because of a failed installation: the core of the program works without the extra
    packages, and the message says how to install them by hand.  ``skip`` (or STATE_MAPPER_SKIP_INSTALL=1)
    switches installation off; ``runner`` / ``check`` exist for tests."""
    check_python()
    requirements = Path(requirements or REQUIREMENTS)
    vendor = Path(vendor or VENDOR)
    use_vendor(vendor)
    try:
        reqs = parse_requirements(requirements.read_text(encoding="utf-8"))
    except OSError:
        out(f"warning: {requirements} not found, the requirements are not checked")
        return True
    missing = [r for r in reqs if not check(r)]
    if not missing:
        return True
    specs = [r.spec for r in missing]
    by_hand = f"python -m pip install -r {requirements.name}"
    if skip is None:
        skip = os.environ.get(SKIP_ENV, "") not in ("", "0")
    if skip:
        out(f"warning: missing or outdated packages: {', '.join(specs)} (automatic installation is off; "
            f"install them with: {by_hand})")
        return False

    out(f"Installing missing packages: {', '.join(specs)} ...")
    run = runner or (lambda cmd: _run_pip(cmd, out))
    if runner is None and importlib.util.find_spec("pip") is None:
        out("  pip is not available, trying ensurepip ...")
        run([sys.executable, "-m", "ensurepip", "--upgrade"])
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    ok = False if force_target else run(base + specs)
    if not ok:
        if not force_target:
            out(f"  normal installation failed; installing into {vendor} instead ...")
        ok = run(base + ["--target", str(vendor)] + specs)
    use_vendor(vendor)
    still = [r.spec for r in reqs if not check(r)]
    if ok and not still:
        out("  done.")
        return True
    out(f"warning: could not install {', '.join(still or specs)}. Pictures that need it will be skipped; "
        f"install it by hand with: {by_hand}")
    return False


# ------------------------------------------------------------------------ Graphviz
def _dot_rank(path: str) -> tuple:
    """Sort key: the unversioned folder 'Graphviz' (what the current installers use) first, then versioned
    folders ('Graphviz 2.38', 'Graphviz2.38') from the newest to the oldest.  The digits of the rest of the
    path play no role."""
    folder = next((part for part in reversed(re.split(r"[\\/]", path)) if part.lower().startswith("graphviz")), "")
    digits = tuple(int(x) for x in re.findall(r"\d+", folder))
    return (0, ()) if not digits else (1, tuple(-d for d in digits))


def _candidate_dots(environ, platform) -> list:
    """Existing dot executables in the places where installers put Graphviz (newest version first)."""
    patterns = []
    if platform.startswith("win"):
        roots = [environ.get(k) for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
        roots += [r"C:\Program Files", r"C:\Program Files (x86)"]
        local = environ.get("LOCALAPPDATA")
        if local:
            roots.append(os.path.join(local, "Programs"))
        for root in [r for r in roots if r]:
            patterns += [os.path.join(root, "Graphviz*", "bin", "dot.exe"),
                         os.path.join(root, "Graphviz*", "dot.exe")]
        home = environ.get("USERPROFILE")
        if home:
            patterns.append(os.path.join(home, "scoop", "apps", "graphviz", "current", "bin", "dot.exe"))
        for choco in (environ.get("ChocolateyInstall"), r"C:\ProgramData\chocolatey"):
            if choco:
                patterns.append(os.path.join(choco, "bin", "dot.exe"))
    else:
        patterns += ["/opt/homebrew/bin/dot", "/usr/local/bin/dot", "/opt/local/bin/dot", "/usr/bin/dot"]
    found = []
    for pat in patterns:
        found += [p for p in glob.glob(pat) if os.path.isfile(p)]
    return sorted(dict.fromkeys(found), key=_dot_rank)       # stable: the order of the patterns is kept


def find_dot(environ=None, platform=None, which=None) -> Optional[str]:
    """Path of the Graphviz ``dot`` program, or None.  Order: GRAPHVIZ_DOT, PATH, standard install folders."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    which = shutil.which if which is None else which
    override = environ.get(DOT_ENV)
    if override and os.path.isfile(override):
        return override
    on_path = which("dot")
    if on_path:
        return on_path
    found = _candidate_dots(environ, platform)
    return found[0] if found else None


def dot_environment(exe: str) -> dict:
    """Environment for running a dot that is not on the PATH: its folder first (Windows needs the DLLs there)."""
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(os.path.abspath(exe)) + os.pathsep + env.get("PATH", "")
    return env


def install_hint(platform=None) -> str:
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        how = ("run the installer from https://graphviz.org/download/ (tick 'Add Graphviz to the system PATH'), "
               "or: winget install Graphviz.Graphviz   (or: choco install graphviz)")
    elif platform == "darwin":
        how = "brew install graphviz"
    else:
        how = "sudo apt install graphviz   (Debian/Ubuntu)  or  sudo dnf install graphviz   (Fedora)"
    return (f"Graphviz was not found. Install it ({how}), then run again. "
            f"If it is installed in an unusual place, set {DOT_ENV} to the full path of dot.")


def graphviz_version(exe: str) -> str:
    try:
        proc = subprocess.run([exe, "-V"], capture_output=True, text=True, env=dot_environment(exe))
        return (proc.stderr or proc.stdout).strip()          # dot prints its version to stderr
    except OSError as e:
        return f"cannot run: {e}"


def environment_report(out=print) -> bool:
    """Print what is installed; returns True if everything needed for all features is there."""
    check_python()
    out(f"Python   : {sys.version.split()[0]} ({sys.executable})")
    use_vendor(VENDOR)
    ok = True
    try:
        reqs = parse_requirements(REQUIREMENTS.read_text(encoding="utf-8"))
    except OSError:
        reqs = []
    for r in reqs:
        have = installed_version(r.name)
        good = satisfied(r)
        ok &= good
        out(f"package  : {r.spec:<16} " + (f"OK (installed {have})" if good else
                                          f"MISSING or too old (installed: {have or 'no'})"))
    exe = find_dot()
    if exe:
        out(f"Graphviz : OK, {exe}")
        out(f"           {graphviz_version(exe)}")
    else:
        ok = False
        out("Graphviz : NOT FOUND")
        out("           " + install_hint())
    return ok
