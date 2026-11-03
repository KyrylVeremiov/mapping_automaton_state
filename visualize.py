#!/usr/bin/env python3
"""
visualize - draw the result of state_mapper as one picture (PNG).

The picture contains
  * the OLD automaton A with its current state highlighted (gold, double ring),
  * the NEW automaton B with the corresponding state(s) highlighted,
  * dashed arrows from the current state of A to the corresponding state(s)
    of B, labelled with an example history,
  * thick coloured edges: the shortest history leading to every candidate
    (the same colour is used in A and in B; an edge shared by several
    histories gets several parallel colours),
  * a red dashed edge to a red box where B cannot replay a history,
  * grey elements: not on any history of the current state / never visited.

Rendering needs the Graphviz `dot` program (https://graphviz.org/download/).
Python packages are not required: the DOT text is piped to `dot -Tpng`.

Usage:
    python visualize.py --example L3-03 -o ticket.png       # a case from examples.py
    python visualize.py --all-examples images/              # one PNG per example
    python visualize.py old.json new.json STATE -o out.png [--lenient] [--dot out.dot]
"""
from __future__ import annotations

import argparse
import html
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Set, Tuple

# Private helpers are imported on purpose: this module is part of the same package.
from state_mapper import (DFA, MappingResult, State, Status, _explore, fmt_word,
                          map_state)

GOLD, GREEN, RED, GREY = "#ffd54a", "#2e9e5b", "#d62728", "#bdbdbd"
PALETTE = ["#e07b00", "#1f77b4", "#8e44ad", "#16a085", "#b8860b", "#c2185b"]
Edge = Tuple[State, str, State]


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _esc(text: object) -> str:
    """Escape a string for a double-quoted DOT identifier / label."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _nid(prefix: str, state: State) -> str:
    """Node id; the prefix keeps same-named states of A and B apart."""
    return f'"{prefix}:{_esc(state)}"'


def _light(color: str, mix: float = 0.82) -> str:
    """Blend a #rrggbb colour with white (for node fills)."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (round(c + (255 - c) * mix) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _reachable(dfa: DFA) -> Set[State]:
    seen = {dfa.start}
    stack = [dfa.start]
    while stack:
        for _, dst in dfa.edges_from(stack.pop()):
            if dst not in seen:
                seen.add(dst)
                stack.append(dst)
    return seen


def _path_edges(dfa: DFA, word: Tuple[str, ...]) -> List[Edge]:
    """Edges used by `word`, up to the point where the automaton gets stuck."""
    edges: List[Edge] = []
    state = dfa.start
    for sym in word:
        nxt = dfa.step(state, sym)
        if nxt is None:
            break
        edges.append((state, sym, nxt))
        state = nxt
    return edges


def _dot_executable() -> Optional[str]:
    """Return Graphviz's dot executable, including standard Windows installs."""
    executable = shutil.which("dot")
    if executable:
        return executable

    candidates = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            candidates.append(os.path.join(root, "Graphviz", "bin", "dot.exe"))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _candidate_colors(result: MappingResult) -> Dict[State, str]:
    if result.status is Status.UNIQUE:
        return {result.answer: GREEN}                     # type: ignore[dict-item]
    return {cand: PALETTE[i % len(PALETTE)]
            for i, cand in enumerate(result.candidates)}


def _headline(result: MappingResult) -> str:
    q = result.current
    if result.status is Status.UNIQUE:
        text = (f"UNIQUE: state '{q}' of A corresponds to state '{result.answer}' of B "
                f"(every history of '{q}' ends there)")
        if result.stuck is not None:
            text += "; lenient mode: some histories are not replayable by B"
        return text
    if result.status is Status.AMBIGUOUS:
        names = ", ".join(f"'{c}'" for c in result.candidates)
        return (f"AMBIGUOUS: A merged different histories into '{q}', "
                f"B keeps them apart: {names}")
    if result.status is Status.STUCK:
        s = result.stuck
        assert s is not None
        return (f"STUCK: B cannot replay history '{fmt_word(s.history)}' "
                f"(event '{s.event}' is not allowed in B state '{s.new_state}')")
    return f"UNREACHABLE: state '{q}' has no history in A"


# --------------------------------------------------------------------------
# DOT generation
# --------------------------------------------------------------------------
def _emit_edges(dfa: DFA, prefix: str, highlight: Dict[Edge, List[str]],
                active: Set[State]) -> List[str]:
    """Edges of one automaton; parallel edges with equal style share a label."""
    groups: Dict[Tuple[State, State, str, str, str], List[str]] = {}
    for src in dfa._bfs_order():
        for sym, dst in dfa.edges_from(src):
            colors = highlight.get((src, sym, dst))
            if colors:
                style = (":".join(colors), "2.6", colors[0])
            elif src in active and dst in active:
                style = ("#444444", "1.2", "#222222")
            else:
                style = (GREY, "1.0", "#9a9a9a")
            groups.setdefault((src, dst) + style, []).append(sym)
    lines = []
    for (src, dst, color, width, fcolor), labels in groups.items():
        lines.append(f'    {_nid(prefix, src)} -> {_nid(prefix, dst)} '
                     f'[label="{_esc(", ".join(labels))}", color="{color}", '
                     f'fontcolor="{fcolor}", penwidth={width}];')
    return lines


def _legend(result: MappingResult) -> str:
    def cell(color: str, text: str) -> str:
        return (f'<TD BGCOLOR="{color}" WIDTH="16" HEIGHT="11" FIXEDSIZE="TRUE"></TD>'
                f'<TD BORDER="0">{html.escape(text)}</TD>')
    items = [cell(GOLD, "current state of A")]
    if result.status is Status.UNIQUE:
        items.append(cell(_light(GREEN, 0.55), "corresponding state of B (green path = its history)"))
    elif result.candidates:
        items.append(cell(_light(PALETTE[0], 0.55), "candidate state of B (same-colour path = its history)"))
    if result.stuck is not None:
        items.append(cell(_light(RED, 0.55), "history that B cannot replay"))
    items.append(cell("#e6e6e6", "not on any history of the current state"))
    return ('<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="6" CELLPADDING="2"><TR>'
            + "".join(items) + "</TR></TABLE>")


def _build_dot(result: MappingResult, title: str, swap: bool) -> str:
    """DOT source; `swap` declares the NEW cluster before the OLD one."""
    old, new, q = result.old, result.new, result.current
    colors = _candidate_colors(result)

    # --- which parts of A and B matter for the answer ---------------------
    keep = old.can_reach(q)
    if old.start in keep:
        visited = _explore(old, new, keep)
        relevant_a = {a for a, _ in visited}
        visited_b = {b for _, b in visited if b is not None}
    else:
        relevant_a, visited_b = set(), set()
    relevant_a &= _reachable(old)

    # --- coloured histories ---------------------------------------------
    hl_a: Dict[Edge, List[str]] = {}
    hl_b: Dict[Edge, List[str]] = {}

    def add(target: Dict[Edge, List[str]], edge: Edge, color: str) -> None:
        if color not in target.setdefault(edge, []):
            target[edge].append(color)

    for cand, word in result.candidates.items():
        for e in _path_edges(old, word):
            add(hl_a, e, colors[cand])
        for e in _path_edges(new, word):
            add(hl_b, e, colors[cand])
    if result.stuck is not None:
        for e in _path_edges(old, result.stuck.history):
            add(hl_a, e, RED)
        for e in _path_edges(new, result.stuck.history):
            add(hl_b, e, RED)

    # --- header (title, headline, legend) --------------------------------
    title = title or "State mapping: old automaton A -> new automaton B"
    header = ('<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="3">'
              f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="22"><B>{html.escape(title)}</B></FONT></TD></TR>'
              f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="15">{html.escape(_headline(result))}</FONT></TD></TR>'
              f'<TR><TD ALIGN="LEFT">{_legend(result)}</TD></TR>'
              '</TABLE>>')

    L: List[str] = [
        "digraph G {",
        "  rankdir=LR; compound=true; newrank=true; pad=0.35; nodesep=1.0; ranksep=0.8;",
        '  bgcolor="white"; labelloc=t; labeljust=l; fontname="Helvetica";',
        f"  label={header};",
        '  node [fontname="Helvetica", fontsize=14, shape=ellipse, margin="0.12,0.06"];',
        '  edge [fontname="Helvetica", fontsize=13, arrowsize=0.8];',
    ]

    # --- old automaton ---------------------------------------------------
    head, L = L, []
    L += ['  subgraph cluster_old {',
          f'    label=<<B>OLD automaton A</B>  (current state: {html.escape(str(q))})>;',
          '    fontname="Helvetica"; fontsize=16; labeljust=l; style="rounded,filled";',
          '    color="#c9a227"; fillcolor="#fffbea"; margin=16;',
          '    "A:__start__" [shape=point, width=0.12, color="#444444"];']
    for state in old._bfs_order():
        attrs = ['style=filled', f'label="{_esc(state)}"']
        if state == q:
            attrs += [f'fillcolor="{GOLD}"', 'color="#8a6d00"', "penwidth=2.5", "peripheries=2",
                      f'label="{_esc(state)}\\n(current)"']
        elif state in relevant_a:
            attrs += ['fillcolor="white"', 'color="#444444"']
        else:
            attrs += ['fillcolor="#f4f4f4"', f'color="{GREY}"', 'fontcolor="#9a9a9a"']
        L.append(f'    {_nid("A", state)} [{", ".join(attrs)}];')
    L.append(f'    "A:__start__" -> {_nid("A", old.start)} [color="#444444"];')
    L += _emit_edges(old, "A", hl_a, relevant_a)
    L.append("  }")
    old_block, L = L, []

    # --- new automaton ---------------------------------------------------
    verdict = result.short()
    L += ['  subgraph cluster_new {',
          f'    label=<<B>NEW automaton B</B>  (result: {html.escape(verdict)})>;',
          '    fontname="Helvetica"; fontsize=16; labeljust=l; labelloc=b; style="rounded,filled";',
          '    color="#4a78b5"; fillcolor="#f2f7ff"; margin=16;',
          '    "B:__start__" [shape=point, width=0.12, color="#444444"];']
    for state in new._bfs_order():
        attrs = ['style=filled', f'label="{_esc(state)}"']
        if state in colors:
            tag = "match" if result.status is Status.UNIQUE else "candidate"
            attrs += [f'fillcolor="{_light(colors[state], 0.78)}"', f'color="{colors[state]}"',
                      "penwidth=3.5", f'label="{_esc(state)}\\n({tag})"']
        elif state in visited_b:
            attrs += ['fillcolor="white"', 'color="#444444"']
        else:
            attrs += ['fillcolor="#f4f4f4"', f'color="{GREY}"', 'fontcolor="#9a9a9a"']
        L.append(f'    {_nid("B", state)} [{", ".join(attrs)}];')
    L.append(f'    "B:__start__" -> {_nid("B", new.start)} [color="#444444"];')
    active_b = visited_b | set(colors)
    L += _emit_edges(new, "B", hl_b, active_b)
    if result.stuck is not None:
        s = result.stuck
        L.append(f'    "B:__stuck__" [shape=box, style="rounded,filled", fillcolor="{_light(RED, 0.85)}", '
                 f'color="{RED}", fontcolor="{RED}", penwidth=2, '
                 f'label="B has no transition\\non \'{_esc(s.event)}\' here"];')
        L.append(f'    {_nid("B", s.new_state)} -> "B:__stuck__" [style=dashed, color="{RED}", '
                 f'fontcolor="{RED}", penwidth=2.2, label="{_esc(s.event)}"];')
    L.append("  }")

    new_block, L = L, []
    L = head + (new_block + old_block if swap else old_block + new_block)

    # --- correspondence arrows (do not influence the layout) ---------------
    for cand, word in result.candidates.items():
        what = "corresponds to" if result.status is Status.UNIQUE else "possible match"
        # HTML label with a white background so the dashed line does not strike the text
        label = ('<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2" BGCOLOR="white">'
                 f'<TR><TD><FONT COLOR="{colors[cand]}"><B>{what}</B></FONT></TD></TR>'
                 f'<TR><TD><FONT COLOR="{colors[cand]}">history: {html.escape(fmt_word(word))}</FONT></TD></TR>'
                 '</TABLE>>')
        L.append(f'  {_nid("A", q)} -> {_nid("B", cand)} [constraint=false, style=dashed, '
                 f'color="{colors[cand]}", penwidth=2.6, arrowsize=1.1, label={label}];')
    L.append("}")
    return "\n".join(L)


def _a_above_b(dot_text: str) -> bool:
    """Lay the graph out with Graphviz and check that OLD is drawn above NEW."""
    executable = _dot_executable()
    if executable is None:
        raise FileNotFoundError("Graphviz 'dot' was not found")
    out = subprocess.run([executable, "-Tplain"], input=dot_text.encode("utf-8"),
                         capture_output=True, check=True).stdout.decode("utf-8", "replace")
    y = {}
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] == "node" and parts[1].strip('"') in ("A:__start__", "B:__start__"):
            y[parts[1].strip('"')] = float(parts[3])          # plain format: y grows upwards
    return y.get("A:__start__", 0.0) >= y.get("B:__start__", 0.0)


def to_dot(result: MappingResult, title: str = "") -> str:
    """Graphviz DOT source for one mapping result (old automaton above, new below).

    Graphviz decides the vertical order of unconnected clusters itself, so the
    layout is probed once with `dot -Tplain` and the clusters are swapped in the
    source if needed.  Without Graphviz installed the unswapped source is returned.
    """
    dot_text = _build_dot(result, title, swap=False)
    try:
        if not _a_above_b(dot_text):
            return _build_dot(result, title, swap=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    return dot_text


def render_png(result: MappingResult, path: str, title: str = "", dpi: int = 130) -> None:
    """Render the figure to `path` using the Graphviz `dot` program."""
    dot_text = to_dot(result, title)
    executable = _dot_executable()
    if executable is None:
        raise RuntimeError("Graphviz 'dot' was not found. Install Graphviz "
                           "(https://graphviz.org/download/) or add its bin directory "
                           "to PATH, or use --dot to save the DOT source and render it "
                           "elsewhere.")
    try:
        proc = subprocess.run([executable, "-Tpng", f"-Gdpi={dpi}", "-o", path],
                              input=dot_text.encode("utf-8"), capture_output=True)
    except FileNotFoundError:
        raise RuntimeError("Graphviz 'dot' could not be started. Check the installation "
                           "or add its bin directory to PATH.") from None
    if proc.returncode != 0:
        raise RuntimeError("dot failed: " + proc.stderr.decode("utf-8", "replace"))


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Draw the state mapping as a PNG.")
    parser.add_argument("old", nargs="?", help="JSON file of the old automaton")
    parser.add_argument("new", nargs="?", help="JSON file of the new automaton")
    parser.add_argument("state", nargs="?", help="current state of the old automaton")
    parser.add_argument("--example", metavar="ID", help="draw a case from examples.py, e.g. L3-03")
    parser.add_argument("--all-examples", metavar="DIR", help="draw every example into DIR")
    parser.add_argument("-o", "--output", default="mapping.png", help="output PNG (default: mapping.png)")
    parser.add_argument("--dot", metavar="FILE", help="also save the DOT source")
    parser.add_argument("--lenient", action="store_true")
    parser.add_argument("--dpi", type=int, default=130)
    args = parser.parse_args(argv)

    if args.all_examples or args.example:
        from v0.examples import CASES
        cases = [c for c in CASES if args.example in (None, c.id)]
        if not cases:
            parser.error(f"unknown example id {args.example!r}")
        outdir = args.all_examples
        if outdir:
            os.makedirs(outdir, exist_ok=True)
        for case in cases:
            result = map_state(DFA.from_text(case.old), case.current,
                               DFA.from_text(case.new), lenient=case.lenient)
            path = (os.path.join(outdir, f"{case.id}.png") if outdir else args.output)
            title = f"[{case.id}] {case.title}" + (" (lenient mode)" if case.lenient else "")
            render_png(result, path, title, args.dpi)
            if args.dot and not outdir:
                with open(args.dot, "w", encoding="utf-8") as fh:
                    fh.write(to_dot(result, title))
            print(f"{case.id}: {result.short():<28} -> {path}")
        return 0

    if not (args.old and args.new and args.state):
        parser.error("give OLD.json NEW.json STATE, or use --example / --all-examples")
    old, new = DFA.from_json_file(args.old), DFA.from_json_file(args.new)
    result = map_state(old, args.state, new, lenient=args.lenient)
    render_png(result, args.output, "", args.dpi)
    if args.dot:
        with open(args.dot, "w", encoding="utf-8") as fh:
            fh.write(to_dot(result))
    print(f"{result.short()} -> {args.output}")
    return 0 if result.status is Status.UNIQUE else 1


if __name__ == "__main__":
    sys.exit(main())
