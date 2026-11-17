#!/usr/bin/env python3
"""Find the state of the NEW automaton B that corresponds to a state of the OLD automaton A.

    python map_state.py OLD NEW STATE [options]         # one state
    python map_state.py OLD NEW --all-states [options]  # every state of A, all definitions side by side
    python map_state.py --check-env                     # what is installed (Python, packages, Graphviz)

The default is   --definition all --policy all --mode explain --visualize   i.e.
    python map_state.py old.json new.json current_state_in_old

Options
  --definition strong|simple|existence|strong_and_simple|all   (default: all = strong, simple, existence)
  --policy     strict|lenient|strict_and_lenient|all          (default: all = strict and lenient)
  --mode       short|explain                      (default: explain)
  --visualize / --no-visualize                    save pictures to --images-dir (default: on, folder images)
  --picture    all | separate,combined,grid       which pictures when several modes run (default: all):
                 separate  one picture per mode
                 combined  ONE picture with all modes: A and B drawn once, every arrow labelled with its modes
                 grid      ONE table of pictures: columns = definitions, rows = policies (3x2 for all modes)
  --format     auto|aut|json|dot|jff|att          file format of both automata (default: auto-detect)
  --all-states                                    table for all states of A (strong | simple | existence | note)
  --no-install                                    do not install missing Python packages automatically
  --check-env                                     print the state of the environment and exit

Definitions: strong    - all histories of the state must lead B to the same state
             simple    - the same, but only for simple histories (no repeated state of A)
             existence - EXISTS instead of FOR ALL: lists every state of B that some history can lead to
When several definitions are requested, "relation" blocks are printed: strong UNIQUE p implies simple
UNIQUE p, and every state that a simple history leads to is a candidate of existence (never the other way round).

Answers: UNIQUE <p> | AMBIGUOUS <candidates> | STUCK | UNREACHABLE
         (+ NO_MATCH, only if the files declare accepting states, see README.md)
Every answer comes with witness words.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import environment
import visualize
from automaton import AutomatonError, load_pair
from formats import FORMATS
from mapping import (DEFINITION_NAMES, EXISTENCE, INCONSISTENT, LENIENT, SIMPLE, STRICT, STRONG, TooManyHistories,
                     analyze, compare_all)
from report import format_relation, format_result, format_state_table

DEFINITIONS = {"strong": [STRONG], "simple": [SIMPLE], "existence": [EXISTENCE],
               "strong_and_simple": [STRONG, SIMPLE], "all": [STRONG, SIMPLE, EXISTENCE]}
POLICIES = {"strict": [STRICT], "lenient": [LENIENT], "strict_and_lenient": [STRICT, LENIENT],
            "all": [STRICT, LENIENT]}
MODES = ("short", "explain", "explained")
PICTURE_KINDS = ("separate", "combined", "grid")


def parse_pictures(text) -> tuple:
    """'all' or a comma separated list of separate/combined/grid -> tuple of picture kinds."""
    if not isinstance(text, str):
        text = ",".join(text)
    names = [x.strip() for x in text.split(",") if x.strip()]
    if "all" in names:
        return PICTURE_KINDS
    bad = [n for n in names if n not in PICTURE_KINDS]
    if bad or not names:
        raise argparse.ArgumentTypeError(
            f"invalid picture kind(s) {bad or [text]}; use 'all' or a comma separated list of "
            f"{', '.join(PICTURE_KINDS)}")
    return tuple(k for k in PICTURE_KINDS if k in names)


def _picture_name(label, kind, definition, policy) -> str:
    """File name of a picture; '<label>__all.png' (all paths) and '<label>__grid.png' for every mode."""
    everything = definition == "all" and policy == "all"
    if kind == "combined":
        return f"{label}__all.png" if everything else f"{label}__combined_{definition}_{policy}.png"
    return f"{label}__grid.png" if everything else f"{label}__grid_{definition}_{policy}.png"


def solve(old_path, new_path, state, definition="all", policy="all", mode="explain",
          visualize_=True, images_dir="images", label=None, title=None, out=print,
          picture="all", fmt="auto", relations=None):
    """Run the requested combinations; print results; return [(def, policy, Result, image|None)].

    With several definitions the relations strong -> simple -> existence are printed for every policy
    (and the Relation objects are appended to ``relations`` if a list is given).

    picture (only with visualize_): 'all' or a comma separated list of
      separate = one picture per mode, combined = one picture with all modes (all paths),
      grid = one table of pictures (columns = definitions, rows = policies).
    With a single mode only its own picture is made."""
    A, B = load_pair(old_path, new_path, fmt)
    combos = [(d, p) for d in DEFINITIONS[definition] for p in POLICIES[policy]]
    kinds = parse_pictures(picture)
    multi = len(combos) > 1
    label = label or f"{Path(old_path).stem}_to_{Path(new_path).stem}_{state}"
    results, warned = [], set()

    def warn(key, message):
        if key not in warned:                        # each kind of problem is reported once
            warned.add(key)
            out(f"    [no image] {message}")

    for d, p in combos:
        r = analyze(A, B, state, d, p)
        out(f"--- {d} / {p} " + "-" * 50)
        out(format_result(r, A, B, mode))
        image = None
        if visualize_ and (not multi or "separate" in kinds):
            path = Path(images_dir) / f"{label}__{d}_{p}.png"
            try:
                image = visualize.render(A, B, r, path, title=title)
                out(f"    image: {image}")
            except visualize.GraphvizMissing as e:
                warn("dot", e)
            except RuntimeError as e:
                warn("dot-failed", e)
        if mode != "short":
            out("")
        results.append((d, p, r, image))

    by_key = {(d, p): r for d, p, r, _ in results}
    for pol in POLICIES[policy]:
        for rel in compare_all(by_key, pol):
            text = format_relation(rel, mode)
            if text:
                out(text)
                if mode != "short":
                    out("")
            if relations is not None:
                relations.append(rel)

    triples = [(d, p, r) for d, p, r, _ in results]
    if visualize_ and multi:
        for kind, render, what in (("combined", visualize.render_combined, "all modes on one picture"),
                                   ("grid", visualize.render_grid, None)):
            if kind not in kinds:
                continue
            path = Path(images_dir) / _picture_name(label, kind, definition, policy)
            try:
                render(A, B, triples, path, title=title)
                shape = f"{len(DEFINITIONS[definition])}x{len(POLICIES[policy])}"
                out(f"{what or 'table of pictures (' + shape + ', columns = definitions, rows = policies)'}: {path}")
            except visualize.PillowMissing as e:
                warn("pillow", e)
            except visualize.GraphvizMissing as e:
                warn("dot", e)
            except RuntimeError as e:
                warn("dot-failed", e)
    return results


def solve_all_states(old_path, new_path, policy="all", mode="explain", out=print, fmt="auto", relations=None):
    """All definitions for EVERY state of A, side by side (one table per policy).

    Shows that simple allows more corresponding states than strong, and that existence lists every
    state that some history can lead to: every state with a unique counterpart under strong has the
    same counterpart under simple, and every simple counterpart is a candidate of existence."""
    A, B = load_pair(old_path, new_path, fmt)
    tables = {}
    for p in POLICIES[policy]:
        rows = []
        for q in A.states:
            res = {(d, p): analyze(A, B, q, d, p) for d in DEFINITION_NAMES}
            rels = compare_all(res, p)
            rows.append((q, res[(STRONG, p)], res[(SIMPLE, p)], res[(EXISTENCE, p)], rels))
        out(format_state_table(rows, p, "A (the old automaton)", mode))
        out("")
        if relations is not None:
            for row in rows:
                relations += row[4]
        tables[p] = rows
    return tables


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old", nargs="?", help="file with the old automaton A")
    ap.add_argument("new", nargs="?", help="file with the new automaton B")
    ap.add_argument("state", nargs="?", help="current state of A (not needed with --all-states)")
    ap.add_argument("--definition", choices=DEFINITIONS, default="all")
    ap.add_argument("--policy", choices=POLICIES, default="all")
    ap.add_argument("--mode", choices=MODES, default="explain")
    ap.add_argument("--visualize", dest="visualize", action="store_true", default=None,
                    help="save pictures to the images folder (this is the default)")
    ap.add_argument("--no-visualize", dest="visualize", action="store_false", help="do not save pictures")
    ap.add_argument("--images-dir", default="images")
    ap.add_argument("--picture", type=parse_pictures, default=PICTURE_KINDS, metavar="KINDS",
                    help="all (default) or a comma separated list of: separate, combined, grid")
    ap.add_argument("--format", choices=FORMATS, default="auto", dest="fmt")
    ap.add_argument("--all-states", action="store_true",
                    help="table: every definition for every state of A")
    ap.add_argument("--no-install", action="store_true",
                    help="do not install missing Python packages automatically")
    ap.add_argument("--check-env", action="store_true",
                    help="print the state of the environment (Python, packages, Graphviz) and exit")
    args = ap.parse_args(argv)

    if args.check_env:
        return 0 if environment.environment_report() else 1
    if not args.old or not args.new:
        ap.error("OLD and NEW automaton files are required")
    if not args.all_states and args.state is None:
        ap.error("STATE is required (or use --all-states)")
    make_pictures = (args.visualize is not False) and not args.all_states
    if make_pictures:                       # the packages are only needed for pictures
        environment.ensure_requirements(skip=True if args.no_install else None)
    try:
        if args.all_states:
            if args.visualize:
                print("note: --visualize is ignored with --all-states", file=sys.stderr)
            rels = []
            solve_all_states(args.old, args.new, args.policy, args.mode, fmt=args.fmt, relations=rels)
            return 1 if any(r.kind == INCONSISTENT for r in rels) else 0
        rels = []
        solve(args.old, args.new, args.state, args.definition, args.policy, args.mode, make_pictures,
              args.images_dir, picture=args.picture, fmt=args.fmt, relations=rels)
        return 1 if any(r.kind == INCONSISTENT for r in rels) else 0
    except (AutomatonError, ValueError, TooManyHistories) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
