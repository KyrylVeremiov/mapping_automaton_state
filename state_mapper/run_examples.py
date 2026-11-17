#!/usr/bin/env python3
"""Run the examples from the ``examples`` folder.

    python run_examples.py                       # all examples; the default is the same as for map_state.py:
                                                 #   --definition all --policy all --mode explain --visualize
    python run_examples.py 02 07                 # only examples whose folder name starts with / contains this
    python run_examples.py --definition simple --policy strict --mode short   # a quick, compact run
    python run_examples.py --picture grid        # only the 3x2 table picture per example
    python run_examples.py --no-visualize
    python run_examples.py 02 --all-states       # table: strong | simple | existence for every state of A

An example is a folder with  old.<ext>, new.<ext>  (any supported format: .json .dot .jff .fsm .aut)
and  case.json:
    {"title": "...", "description": "...", "state": "<current state of A>",
     "expect": {"strong/strict": "UNIQUE odd", "simple/lenient": "AMBIGUOUS e s2",
                "existence/strict": "AMBIGUOUS e s2", ...}}                                   (expect is optional)

Programmatic use:  run_one_example("02_tricky_ambiguous")     # the same defaults as above
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import environment
from automaton import AutomatonError
from map_state import DEFINITIONS, MODES, PICTURE_KINDS, POLICIES, parse_pictures, solve, solve_all_states
from mapping import INCONSISTENT, TooManyHistories

ROOT = Path(__file__).resolve().parent
EXAMPLES_DIR = ROOT / "examples"
IMAGES_DIR = ROOT / "images"


def list_examples(examples_dir=EXAMPLES_DIR) -> list:
    return sorted(p for p in Path(examples_dir).iterdir() if (p / "case.json").is_file())


def find_example(name, examples_dir=EXAMPLES_DIR) -> Path:
    """Folder path, exact folder name, or a unique prefix / substring of a folder name."""
    p = Path(name)
    if (p / "case.json").is_file():
        return p
    items = list_examples(examples_dir)
    for pred in (lambda d: d.name == name, lambda d: d.name.startswith(name), lambda d: name in d.name):
        hits = [d for d in items if pred(d)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"'{name}' is ambiguous: {', '.join(d.name for d in hits)}")
    raise ValueError(f"no example '{name}' in {examples_dir}")


def _automaton_file(folder: Path, case: dict, key: str) -> Path:
    """case.json may name the file ("old": "x.json"); otherwise the single old.* / new.* file is used."""
    if case.get(key):
        return folder / case[key]
    hits = sorted(p for p in folder.glob(f"{key}.*") if p.suffix.lower() != ".png")
    if len(hits) != 1:
        raise ValueError(f"{folder.name}: expected exactly one file {key}.<ext>, found {len(hits)}")
    return hits[0]


def _norm(expected: str) -> str:
    head, *rest = expected.split()
    return " ".join([head.upper()] + sorted(rest))


def run_one_example(name, definition="all", policy="all", mode="explain", visualize=True,
                    examples_dir=EXAMPLES_DIR, images_dir=IMAGES_DIR, out=print, picture="all",
                    all_states=False) -> dict:
    """Run one example.

    definition: strong | simple | existence | strong_and_simple | all
    policy    : strict | lenient | strict_and_lenient | all
    mode      : short | explain          (visualize: save pictures to images_dir)
    picture   : 'all' or a comma separated list of separate, combined, grid (with several modes:
                one picture per mode / one picture with all modes / one table of pictures)
    all_states: print the table "strong | simple | existence" for every state of A instead of the query
    Returns {"example", "checks": [(combo, signature, expected|None, ok|None)],
             "relations": number of comparisons of the definitions, "inconsistent": how many of them failed}.
    With several definitions "relation" blocks are printed (strong UNIQUE p implies simple UNIQUE p;
    every state a simple history leads to is a candidate of existence; never the other way round).
    """
    folder = find_example(name, examples_dir)
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    state = case["state"]
    out("=" * 78)
    out(f"Example {folder.name}: {case.get('title', '')}")
    if case.get("description"):
        out(f"  {case['description']}")
    old_file, new_file = _automaton_file(folder, case, "old"), _automaton_file(folder, case, "new")
    out(f"  old: {old_file.name}   new: {new_file.name}   current state of A: {state}")
    rels = []
    if all_states:
        solve_all_states(old_file, new_file, policy, mode, out=out, relations=rels)
        return {"example": folder.name, "checks": [], "relations": len(rels),
                "inconsistent": sum(r.kind == INCONSISTENT for r in rels)}
    results = solve(old_file, new_file, state, definition, policy, mode, visualize, images_dir,
                    label=folder.name, title=case.get("title"), out=out, picture=picture, relations=rels)
    checks = []
    for d, p, r, _image in results:
        combo = f"{d}/{p}"
        expected = case.get("expect", {}).get(combo)
        ok = None if expected is None else (_norm(expected) == r.signature())
        checks.append((combo, r.signature(), expected, ok))
        if ok is False:
            out(f"    !! MISMATCH [{combo}]: expected '{_norm(expected)}', got '{r.signature()}'")
    return {"example": folder.name, "checks": checks, "relations": len(rels),
            "inconsistent": sum(r.kind == INCONSISTENT for r in rels)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("examples", nargs="*", help="examples to run (default: all)")
    ap.add_argument("--definition", choices=DEFINITIONS, default="all")
    ap.add_argument("--policy", choices=POLICIES, default="all")
    ap.add_argument("--mode", choices=MODES, default="explain")
    ap.add_argument("--visualize", dest="visualize", action="store_true", default=True)
    ap.add_argument("--no-visualize", dest="visualize", action="store_false")
    ap.add_argument("--picture", type=parse_pictures, default=PICTURE_KINDS, metavar="KINDS",
                    help="all (default) or a comma separated list of: separate, combined, grid")
    ap.add_argument("--all-states", action="store_true",
                    help="for every example: table strong | simple | existence for all states of A (no pictures)")
    ap.add_argument("--no-install", action="store_true",
                    help="do not install missing Python packages automatically")
    ap.add_argument("--examples-dir", default=str(EXAMPLES_DIR))
    ap.add_argument("--images-dir", default=str(IMAGES_DIR))
    args = ap.parse_args(argv)
    if args.visualize and not args.all_states:      # the packages are only needed for pictures
        environment.ensure_requirements(skip=True if args.no_install else None)

    try:
        names = args.examples or [d.name for d in list_examples(args.examples_dir)]
        runs = [run_one_example(n, args.definition, args.policy, args.mode, args.visualize,
                                args.examples_dir, args.images_dir, picture=args.picture,
                                all_states=args.all_states) for n in names]
    except (AutomatonError, ValueError, TooManyHistories) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    checks = [c for run in runs for c in run["checks"] if c[3] is not None]
    bad = [c for c in checks if not c[3]]
    print("=" * 78)
    n_rel, n_bad_rel = sum(r["relations"] for r in runs), sum(r["inconsistent"] for r in runs)
    print(f"{len(runs)} example(s) run; {len(checks) - len(bad)}/{len(checks)} checks against 'expect' passed.")
    if n_rel:
        print(f"relations strong -> simple -> existence: {n_rel - n_bad_rel}/{n_rel} comparisons consistent "
              "(strong UNIQUE p => simple UNIQUE p => p is a candidate of existence).")
    return 1 if (bad or n_bad_rel) else 0


if __name__ == "__main__":
    sys.exit(main())
