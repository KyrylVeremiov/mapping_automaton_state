#!/usr/bin/env python3
"""Find the state of the NEW automaton B that corresponds to a state of the OLD automaton A.

    python map_state.py OLD NEW STATE [options]       # one state
    python map_state.py OLD NEW --all-states [options]  # every state of A, strong and weak side by side

Options
  --definition strong|weak|strong_and_weak|all    (default: weak; all = strong_and_weak)
  --policy     strict|lenient|strict_and_lenient|all   (default: strict; all = strict_and_lenient)
  --mode       short|explain                      (default: short)
  --visualize                                     save pictures to --images-dir (default: images)
  --picture    separate|combined|both             several modes: one picture per mode, one picture
                                                  with all modes, or both (default: both)
  --format     auto|aut|json|dot|jff|att          file format of both automata (default: auto-detect)
  --all-states                                    table for all states of A (strong | weak | note);
                                                  shows where weak allows more counterparts than strong

When strong and weak are both requested, a "relation strong -> weak" block is printed: strong UNIQUE p
always implies weak UNIQUE p (never the reverse); weak may find a unique counterpart where strong
sees several endings, and the histories that only strong sees are listed.

Answers: UNIQUE <p> | AMBIGUOUS <candidates> | STUCK | UNREACHABLE
         (+ NO_MATCH, only if the files declare accepting states, see README.md)
Every answer comes with witness words.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import visualize
from automaton import AutomatonError, load_pair
from formats import FORMATS
from mapping import INCONSISTENT, LENIENT, STRICT, STRONG, WEAK, TooManyHistories, analyze, compare_definitions
from report import format_relation, format_result, format_state_table

DEFINITIONS = {"strong": [STRONG], "weak": [WEAK], "strong_and_weak": [STRONG, WEAK], "all": [STRONG, WEAK]}
POLICIES = {"strict": [STRICT], "lenient": [LENIENT], "strict_and_lenient": [STRICT, LENIENT],
            "all": [STRICT, LENIENT]}
MODES = ("short", "explain", "explained")
PICTURES = ("separate", "combined", "both")


def solve(old_path, new_path, state, definition="weak", policy="strict", mode="short",
          visualize_=False, images_dir="images", label=None, title=None, out=print,
          picture="both", fmt="auto", relations=None):
    """Run the requested combinations; print results; return [(def, policy, Result, image|None)].

    If both definitions are requested, the relation strong -> weak is printed for every policy
    (and the Relation objects are appended to ``relations`` if a list is given).

    picture (only with --visualize and several modes): separate = one picture per mode,
    combined = one picture with all modes, both = both."""
    A, B = load_pair(old_path, new_path, fmt)
    combos = [(d, p) for d in DEFINITIONS[definition] for p in POLICIES[policy]]
    label = label or f"{Path(old_path).stem}_to_{Path(new_path).stem}_{state}"
    results, warned = [], False
    for d, p in combos:
        r = analyze(A, B, state, d, p)
        if len(combos) > 1 or mode != "short":
            out(f"--- {d} / {p} " + "-" * 50)
        out(format_result(r, A, B, mode))
        image = None
        if visualize_ and (picture != "combined" or len(combos) == 1):
            path = Path(images_dir) / f"{label}__{d}_{p}.png"
            try:
                image = visualize.render(A, B, r, path, title=title)
                out(f"    image: {image}")
            except (visualize.GraphvizMissing, RuntimeError) as e:
                if not warned:
                    out(f"    [no image] {e}")
                    warned = True
        if mode != "short":
            out("")
        results.append((d, p, r, image))
    by_key = {(d, p): r for d, p, r, _ in results}
    for p in POLICIES[policy]:
        if (STRONG, p) in by_key and (WEAK, p) in by_key:
            rel = compare_definitions(by_key[(STRONG, p)], by_key[(WEAK, p)])
            out(format_relation(rel, mode))
            if mode != "short":
                out("")
            if relations is not None:
                relations.append(rel)
    if visualize_ and len(combos) > 1 and picture in ("combined", "both"):
        path = Path(images_dir) / f"{label}__all.png"
        try:
            visualize.render_combined(A, B, [(d, p, r) for d, p, r, _ in results], path, title=title)
            out(f"all modes on one picture: {path}")
        except (visualize.GraphvizMissing, RuntimeError) as e:
            if not warned:
                out(f"    [no image] {e}")
    return results


def solve_all_states(old_path, new_path, policy="strict", mode="short", out=print, fmt="auto", relations=None):
    """Strong and weak result for EVERY state of A, side by side (one table per policy).

    Shows that weak allows more corresponding states than strong: every state with a unique
    counterpart under strong has the same counterpart under weak, and weak may add more."""
    A, B = load_pair(old_path, new_path, fmt)
    tables = {}
    for p in POLICIES[policy]:
        rows = []
        for q in A.states:
            rs, rw = analyze(A, B, q, STRONG, p), analyze(A, B, q, WEAK, p)
            rows.append((q, rs, rw, compare_definitions(rs, rw)))
        out(format_state_table(rows, p, "A (the old automaton)", mode))
        out("")
        if relations is not None:
            relations += [row[3] for row in rows]
        tables[p] = rows
    return tables


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old", help="file with the old automaton A")
    ap.add_argument("new", help="file with the new automaton B")
    ap.add_argument("state", nargs="?", help="current state of A (not needed with --all-states)")
    ap.add_argument("--definition", choices=DEFINITIONS, default="weak")
    ap.add_argument("--policy", choices=POLICIES, default="strict")
    ap.add_argument("--mode", choices=MODES, default="short")
    ap.add_argument("--visualize", action="store_true", help="save pictures to the images folder")
    ap.add_argument("--images-dir", default="images")
    ap.add_argument("--picture", choices=PICTURES, default="both")
    ap.add_argument("--format", choices=FORMATS, default="auto", dest="fmt")
    ap.add_argument("--all-states", action="store_true",
                    help="table: strong and weak result for every state of A")
    args = ap.parse_args(argv)
    if not args.all_states and args.state is None:
        ap.error("STATE is required (or use --all-states)")
    try:
        if args.all_states:
            if args.visualize:
                print("note: --visualize is ignored with --all-states", file=sys.stderr)
            rels = []
            solve_all_states(args.old, args.new, args.policy, args.mode, fmt=args.fmt, relations=rels)
            return 1 if any(r.kind == INCONSISTENT for r in rels) else 0
        solve(args.old, args.new, args.state, args.definition, args.policy, args.mode,
              args.visualize, args.images_dir, picture=args.picture, fmt=args.fmt)
    except (AutomatonError, ValueError, TooManyHistories) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
