#!/usr/bin/env python3
"""
build_gallery - generate the pictures and EXAMPLES.md from the cases in examples.py.

    python build_gallery.py                 # images/*.png + EXAMPLES.md next to this script
    python build_gallery.py --no-images     # only EXAMPLES.md (no Graphviz needed)
    python build_gallery.py --outdir DIR --dpi 100

Everything in EXAMPLES.md is computed by running the real algorithm on the
cases, so the document cannot drift away from the program: if a case does not
produce its expected result, the build stops with an error.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Tuple

from examples import CASES, HARD, PAIRS, SIMPLE, VERY_SIMPLE, Case, evaluate
from state_mapper import (DFA, MappingResult, Status, fmt_word, format_table,
                          map_all)

LEVELS = [VERY_SIMPLE, SIMPLE, HARD]
ICON = {Status.UNIQUE: "✅", Status.AMBIGUOUS: "❓", Status.STUCK: "❌",
        Status.UNREACHABLE: "🚫"}

# "What differs in B" -> typical outcome.  (change, outcome label, allowed statuses, case ids)
CHEATSHEET: List[Tuple[str, str, Tuple[Status, ...], List[str]]] = [
    ("B is a copy of A or differs only in state names",
     "✅ UNIQUE", (Status.UNIQUE,), ["L1-01", "L1-02", "L1-07"]),
    ("B adds events or states that are not on any path to `q`",
     "✅ UNIQUE", (Status.UNIQUE,), ["L1-03"]),
    ("B changes only what happens **after** `q` (the future)",
     "✅ UNIQUE", (Status.UNIQUE,), ["L1-08", "L2-10", "L3-01"]),
    ("B drops branches that do not lead to `q`",
     "✅ UNIQUE", (Status.UNIQUE,), ["L1-04"]),
    ("Infinitely many histories (loops) that all end in one B state",
     "✅ UNIQUE", (Status.UNIQUE,), ["L2-03"]),
    ("B merges histories like A does, or splits them temporarily and merges again before `q`",
     "✅ UNIQUE", (Status.UNIQUE,), ["L2-01", "L2-10", "L3-06"]),
    ("B forgets more than A (coarser, a quotient of A)",
     "✅ UNIQUE", (Status.UNIQUE,), ["L3-04"]),
    ("Lenient mode: histories B cannot replay are tolerated, the rest agree",
     "✅ UNIQUE + warning", (Status.UNIQUE,), ["L2-06", "L3-10"]),
    ("B no longer allows an event on the path to `q` (removed event, dropped loop)",
     "❌ STUCK", (Status.STUCK,), ["L1-05", "L2-05", "L2-08", "L3-02"]),
    ("An event is renamed in B",
     "❌ STUCK", (Status.STUCK,), ["L1-09"]),
    ("B demands a new mandatory step (at the start or in the middle)",
     "❌ STUCK", (Status.STUCK,), ["L1-10", "L3-02", "L3-07"]),
    ("B limits what A allows (e.g. a retry limit)",
     "❌ STUCK (❓ AMBIGUOUS at the same time for some states)",
     (Status.STUCK, Status.AMBIGUOUS), ["L3-09", "L3-08"]),
    ("B keeps apart paths that A merged (path memory)",
     "❓ AMBIGUOUS", (Status.AMBIGUOUS,), ["L2-02", "L2-11", "L3-14"]),
    ("B remembers the order of events that A forgot",
     "❓ AMBIGUOUS", (Status.AMBIGUOUS,), ["L2-09"]),
    ("B unrolls a loop (first iteration, 'reopened' flag)",
     "❓ AMBIGUOUS", (Status.AMBIGUOUS,), ["L2-04", "L3-03"]),
    ("B counts finer than A (mod 2 -> mod 4 / mod 6)",
     "❓ AMBIGUOUS", (Status.AMBIGUOUS,), ["L3-05", "L3-11"]),
    ("An early split in B is never merged back",
     "❓ AMBIGUOUS for every later state", (Status.AMBIGUOUS,), ["L3-13"]),
    ("Ambiguous by history, but the candidates have the same future in B",
     "❓ AMBIGUOUS (harmless if only the future matters)", (Status.AMBIGUOUS,),
     ["L2-07", "L3-12"]),
    ("`q` cannot be reached from A's start",
     "🚫 UNREACHABLE", (Status.UNREACHABLE,), ["L1-06"]),
]


# --------------------------------------------------------------------------
# Running the cases
# --------------------------------------------------------------------------
def compute_results() -> Dict[str, MappingResult]:
    """Run every case; stop with an error if one does not match its expectation."""
    results: Dict[str, MappingResult] = {}
    for case in CASES:
        result, problems = evaluate(case)
        if problems:
            raise SystemExit(f"case {case.id} does not match its expectation: "
                             + "; ".join(problems))
        results[case.id] = result
    return results


def _case(case_id: str) -> Case:
    return next(c for c in CASES if c.id == case_id)


def _title(case: Case) -> str:
    return f"[{case.id}] {case.title}" + (" (lenient mode)" if case.lenient else "")


# --------------------------------------------------------------------------
# Markdown helpers
# --------------------------------------------------------------------------
def badge(case: Case, result: MappingResult) -> str:
    text = f"{ICON[result.status]} {result.status.value}"
    if case.lenient and result.status is Status.UNIQUE:
        text += " (lenient)"
    return text


def result_text(case: Case, result: MappingResult) -> str:
    q = case.current
    if result.status is Status.UNIQUE:
        extra = " + warning" if result.stuck is not None else ""
        return f"`{q}` → `{result.answer}`{extra}"
    if result.status is Status.AMBIGUOUS:
        names = ", ".join(f"`{c}`" for c in result.candidates)
        extra = " (+ unreplayable history)" if result.stuck is not None else ""
        return f"`{q}` → {names}{extra}"
    if result.status is Status.STUCK:
        s = result.stuck
        assert s is not None
        return f"B rejects `{fmt_word(s.history)}` at `{s.event}`"
    return f"`{q}` has no history"


def _overview_table(cases: List[Case], results: Dict[str, MappingResult]) -> List[str]:
    lines = ["| ID | Level | Scenario | Result | Pattern |", "|---|---|---|---|---|"]
    for c in cases:
        lines.append(f"| [{c.id}](#{c.id.lower()}) | {c.level} | {c.title} | "
                     f"{result_text(c, results[c.id])} | {c.reason} |")
    return lines


def _pair_cell(case: Case, result: MappingResult) -> str:
    return (f'<td valign="top" width="50%"><b>{case.id}: {badge(case, result)}</b><br>'
            f'{case.reason}<br><a href="images/{case.id}.png">'
            f'<img src="images/{case.id}.png" width="100%" alt="{case.id}"></a></td>')


def build_markdown(results: Dict[str, MappingResult]) -> str:
    ids = {c.id for c in CASES}
    for change, _, allowed, case_ids in CHEATSHEET:
        for cid in case_ids:
            assert cid in ids, f"cheat sheet mentions unknown case {cid}"
            assert _case(cid).expect in allowed, (
                f"cheat sheet row '{change}' lists {cid} with status "
                f"{_case(cid).expect.value}")
    for pid, (_, members) in PAIRS.items():
        for cid in members:
            assert _case(cid).pair == pid, f"case {cid} is not marked as pair {pid}"

    by_status = {st: [c for c in CASES if results[c.id].status is st] for st in Status}
    possible = by_status[Status.UNIQUE]
    n_levels = {lv: sum(1 for c in CASES if c.level == lv) for lv in LEVELS}

    L: List[str] = []
    add = L.append
    add("# When can a state be mapped? A gallery of examples")
    add("")
    add("<!-- Generated by build_gallery.py from examples.py. Do not edit by hand. -->")
    add("")
    add(f"{len(CASES)} examples ({n_levels[VERY_SIMPLE]} very simple, {n_levels[SIMPLE]} simple, "
        f"{n_levels[HARD]} hard). Every example shows the old automaton **A** with its current "
        "state, the new automaton **B**, and what the program answers and why.")
    add("")
    add(f"- ✅ **UNIQUE**: the state can be mapped ({len(possible)} examples)")
    add(f"- ❌ **STUCK**: impossible, B cannot replay some history ({len(by_status[Status.STUCK])})")
    add(f"- ❓ **AMBIGUOUS**: impossible, B separates histories that A merged "
        f"({len(by_status[Status.AMBIGUOUS])})")
    add(f"- 🚫 **UNREACHABLE**: the question is meaningless, the state has no history "
        f"({len(by_status[Status.UNREACHABLE])})")
    add("")

    # ------------------------------------------------------------------ 1
    add("## 1. The rule in 30 seconds")
    add("")
    add("The current state `q` of the old automaton A can be mapped **by history** to a state `p` of the "
        "new automaton B if and only if, for *every* event sequence that can bring A from its start to `q`:")
    add("")
    add("1. `q` has at least one such sequence (it is reachable), otherwise → 🚫 UNREACHABLE;")
    add("2. B can replay **every** such sequence (no event on the way is forbidden in B), "
        "otherwise → ❌ STUCK;")
    add("3. all of them end in the **same** state of B, otherwise → ❓ AMBIGUOUS.")
    add("")
    add("If all three hold, the answer is ✅ UNIQUE: that one state `p`.")
    add("")
    add("Two things **never** matter: what B can do *beyond* those sequences (B may be much broader than A), "
        "and what happens *after* `q` (the future).")
    add("")
    add("Why the answer cannot be \"guessed\" in the bad cases: the instance is only known to be in `q`; "
        "which of the possible histories it actually followed was not recorded. "
        "If B treats those histories differently, no choice is correct for all of them.")
    add("")

    # ------------------------------------------------------------------ 2
    add("## 2. Cheat sheet: what differs in B → what happens")
    add("")
    add("| What differs in B (compared with A) | Result | Examples |")
    add("|---|---|---|")
    for change, outcome, _, case_ids in CHEATSHEET:
        links = ", ".join(f"[{cid}](#{cid.lower()})" for cid in case_ids)
        add(f"| {change} | {outcome} | {links} |")
    add("")

    # ------------------------------------------------------------------ 3
    add("## 3. Overview of all examples")
    add("")
    add(f"### ✅ Mapping is possible: {len(possible)} examples")
    add("")
    L += _overview_table(possible, results)
    add("")
    add(f"### ❌ Impossible: B cannot replay a history (STUCK): {len(by_status[Status.STUCK])} examples")
    add("")
    L += _overview_table(by_status[Status.STUCK], results)
    add("")
    add(f"### ❓ Impossible: B separates what A merged (AMBIGUOUS): {len(by_status[Status.AMBIGUOUS])} examples")
    add("")
    L += _overview_table(by_status[Status.AMBIGUOUS], results)
    add("")
    add(f"### 🚫 Meaningless: no history (UNREACHABLE): {len(by_status[Status.UNREACHABLE])} example")
    add("")
    L += _overview_table(by_status[Status.UNREACHABLE], results)
    add("")

    # ------------------------------------------------------------------ 4
    add("## 4. Minimal pairs: a tiny change flips the answer")
    add("")
    add("Each pair differs in one small detail of B (or of the question). "
        "Compare the two pictures side by side.")
    add("")
    for pid, (title, members) in PAIRS.items():
        add(f"### {pid}: {title}")
        add("")
        cells = "".join(_pair_cell(_case(cid), results[cid]) for cid in members)
        add(f"<table><tr>{cells}</tr></table>")
        add("")

    # ------------------------------------------------------------------ 5
    add("## 5. All examples in detail")
    add("")
    add("How to read a picture: gold node = current state of A; coloured node = corresponding "
        "state(s) of B; thick coloured edges = the shortest history leading there (same colour in A and B); "
        "red = a history B cannot replay; grey = not on any history of the current state. "
        "A dashed arrow goes from the current state to its match in B.")
    add("")
    for level in LEVELS:
        cases = [c for c in CASES if c.level == level]
        add(f"### Level: {level} ({len(cases)})")
        add("")
        for c in cases:
            r = results[c.id]
            old, new = DFA.from_text(c.old), DFA.from_text(c.new)
            add(f"#### {c.id}")
            add("")
            add(f"**{c.title}**" + (" (lenient mode)" if c.lenient else ""))
            add("")
            line = f"**Result:** {badge(c, r)}: {result_text(c, r)} · **Pattern:** {c.reason}"
            if c.pair:
                line += f" · **Minimal pair:** [{c.pair}](#4-minimal-pairs-a-tiny-change-flips-the-answer)"
            add(line)
            add("")
            add(f"![{c.id}](images/{c.id}.png)")
            add("")
            add(f"**Old automaton A** (start `{old.start}`), current state **`{c.current}`**:")
            add("")
            add("```")
            add(old.describe(indent=""))
            add("```")
            add("")
            add(f"**New automaton B** (start `{new.start}`):")
            add("")
            add("```")
            add(new.describe(indent=""))
            add("```")
            add("")
            add(f"**Why:** {c.why}")
            add("")
            if c.table:
                add("Mapping of **all** states of A (`map_all`):")
                add("")
                add("```")
                add(format_table(map_all(old, new, lenient=c.lenient)))
                add("```")
                add("")
            add("<details><summary>Program output</summary>")
            add("")
            add("```")
            add(r.explain())
            add("```")
            add("")
            add("</details>")
            add("")
    return "\n".join(L).rstrip() + "\n"


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build EXAMPLES.md and images/*.png")
    parser.add_argument("--outdir", default=os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--no-images", action="store_true",
                        help="only write EXAMPLES.md (Graphviz not needed)")
    parser.add_argument("--dpi", type=int, default=100)
    args = parser.parse_args(argv)

    results = compute_results()
    os.makedirs(args.outdir, exist_ok=True)

    if not args.no_images:
        from visualize import render_png
        imgdir = os.path.join(args.outdir, "images")
        os.makedirs(imgdir, exist_ok=True)
        for case in CASES:
            render_png(results[case.id], os.path.join(imgdir, case.id + ".png"),
                       _title(case), args.dpi)
        print(f"wrote {len(CASES)} pictures to {imgdir}")

    path = os.path.join(args.outdir, "EXAMPLES.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_markdown(results))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
