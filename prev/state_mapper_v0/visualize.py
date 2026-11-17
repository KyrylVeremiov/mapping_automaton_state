"""Pictures in the style of the reference images (needs the Graphviz ``dot`` executable).

render()           one picture per (definition, policy): OLD automaton A with the current state (gold)
                   above, NEW automaton B with the result below.  Thick coloured paths are the witness
                   histories, grey parts lie on no history of the current state.
render_combined()  ONE picture for several modes: A and B are drawn once, every correspondence arrow is
                   labelled with the modes that produce it, and a table at the top lists the result of
                   every mode.
"""
from __future__ import annotations

import html
import os
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from prev.state_mapper_v0.mapping import AMBIGUOUS, NO_MATCH, STUCK, UNIQUE, UNREACHABLE, WEAK, Live, Trace

FONT = "Helvetica"
GREEN, RED = "#2ca25f", "#d62728"
PALETTE = ["#e07b00", "#1f77b4", "#8e44ad", "#16a085", "#a0522d", "#c2185b"]
GOLD, GOLD_DARK = "#ffd54a", "#8a6d00"
GRAY_FILL, GRAY_LINE, GRAY_TEXT = "#f2f2f2", "#bbbbbb", "#999999"
BG_A, BORDER_A = "#fdf9e7", "#c9a227"
BG_B, BORDER_B = "#eff4fc", "#4a74b4"


class GraphvizMissing(RuntimeError):
    pass


def _dot_executable() -> Optional[str]:
    executable = shutil.which("dot")
    if executable:
        return executable

    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            candidate = os.path.join(root, "Graphviz", "bin", "dot.exe")
            if os.path.isfile(candidate):
                return candidate
    return None


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def _mix(color: str, t: float = 0.8) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(v + (255 - v) * t) for v in (r, g, b))


def _word(w) -> str:
    return " ".join(w) if w else "(empty word)"


def _label(letters, sigma) -> str:
    if len(sigma) >= 3 and set(letters) == set(sigma):
        return "*"
    return ", ".join(sorted(letters, key=sigma.index))


# ------------------------------------------------------------------ description
@dataclass
class Group:
    """One witness history: coloured paths in A and B and (maybe) an arrow q -> target."""
    color: str
    head: str                       # bold caption of the arrow
    target: Optional[str]           # state of B the arrow points to (None: no arrow)
    word: tuple
    a_trace: Trace
    b_trace: Optional[Trace]
    caption: str = ""               # which modes give this arrow (combined picture)


@dataclass
class Spec:
    q: str
    unreachable: bool
    live: Live
    groups: list
    roles: dict                     # state of B -> (colour, tag)
    result_text: str
    title: str
    subtitle: str
    note: str
    legend: list
    table_html: str = ""


def _result_text(r) -> str:
    if r.verdict == UNIQUE:
        return f"UNIQUE -> '{r.p}'"
    if r.verdict == AMBIGUOUS:
        return "AMBIGUOUS -> {" + ", ".join(f"'{c}'" for c in r.candidates) + "}"
    return r.verdict


def _verdict_color(r) -> str:
    return {UNIQUE: GREEN, AMBIGUOUS: PALETTE[0]}.get(r.verdict, RED)


def _subtitle(r) -> str:
    q, simple = r.q, "simple " if r.definition == WEAK else ""
    if r.verdict == UNIQUE:
        return (f"UNIQUE: state '{q}' of A corresponds to state '{r.p}' of B "
                f"(every {simple}history of '{q}' ends there)")
    if r.verdict == AMBIGUOUS:
        return (f"AMBIGUOUS: {simple}histories of '{q}' lead B to different states: "
                + ", ".join(f"'{c}'" for c in r.candidates))
    if r.verdict == STUCK:
        i, s, c = r.witnesses[0].b_trace.stuck
        return f"STUCK: B has no transition on '{c}' in state '{s}' (history: {_word(r.witnesses[0].word)})"
    if r.verdict == UNREACHABLE:
        return f"UNREACHABLE: state '{q}' cannot be reached from the start state of A"
    if r.reason == "q_not_accepting":
        return f"NO_MATCH: state '{q}' is not accepting in A, so it has no histories"
    return (f"NO_MATCH: every history leads B to '{r.p}', which is not accepting "
            f"(the histories are not in L(B))")


def _legend(r) -> list:
    cur = (GOLD, "current state of A")
    gray = (GRAY_FILL, "not on any simple history of the current state"
            if r.definition == WEAK and r.live_exact else "not on any history of the current state")
    if r.verdict == UNIQUE:
        return [cur, (_mix(GREEN), "corresponding state of B (green path = its history)"), gray]
    if r.verdict == AMBIGUOUS:
        return [cur, (_mix(PALETTE[0]), "candidate state of B (same-colour path = its history)"), gray]
    if r.verdict == STUCK:
        return [cur, (_mix(RED), "state where B gets stuck (red path = the history)"), gray]
    if r.verdict == UNREACHABLE:
        return [(GOLD, "current state of A (unreachable)"), ("#ffffff", "reachable from the start state"),
                (GRAY_FILL, "not reachable")]
    return [cur, (_mix(RED), "red path = witness word"), gray]


def _spec_single(A, B, r, title) -> Spec:
    cols, k = [], 0
    for w in r.witnesses:
        if r.verdict == UNIQUE:
            cols.append(GREEN)
        elif r.verdict == NO_MATCH or (r.verdict == STUCK and w.b_state is None):
            cols.append(RED)
        else:
            cols.append(PALETTE[k % len(PALETTE)])
            k += 1
    head_of = {UNIQUE: "corresponds to", AMBIGUOUS: "possible match", STUCK: "possible match",
               NO_MATCH: "not a match"}
    tag_of = {UNIQUE: "match", AMBIGUOUS: "candidate", STUCK: "candidate", NO_MATCH: "not accepting"}
    groups, roles = [], {}
    for w, col in zip(r.witnesses, cols):
        if w.b_trace is None:
            groups.append(Group(col, "", None, w.word, w.a_trace, None))
        elif w.b_state is None:
            s = w.b_trace.stuck[1]
            groups.append(Group(col, "B gets stuck", s, w.word, w.a_trace, w.b_trace))
            roles.setdefault(s, (col, "stuck here"))
        else:
            groups.append(Group(col, head_of[r.verdict], w.b_state, w.word, w.a_trace, w.b_trace))
    for g in groups:
        if g.b_trace is not None and g.b_trace.stuck is None:
            roles.setdefault(g.target, (g.color, tag_of[r.verdict]))
    note = (f"definition: {r.definition}   |   policy: {r.policy}"
            + ("   |   accepting states declared in the files"
               if A.explicit_accepting or B.explicit_accepting else ""))
    return Spec(r.q, r.verdict == UNREACHABLE, r.live, groups, roles, "result: " + _result_text(r),
                title or "State mapping: old automaton A -> new automaton B",
                _subtitle(r), note, _legend(r))


# --------------------------------------------------------------- combined picture
def _modes_caption(modes) -> str:
    modes = set(modes)
    if len(modes) == 4:
        return "all modes"
    for d in ("strong", "weak"):
        if modes == {(d, "strict"), (d, "lenient")}:
            return f"{d}, both policies"
    for p in ("strict", "lenient"):
        if modes == {("strong", p), ("weak", p)}:
            return f"{p}, both definitions"
    order = [("strong", "strict"), ("strong", "lenient"), ("weak", "strict"), ("weak", "lenient")]
    return ", ".join(f"{d}/{p}" for d, p in order if (d, p) in modes)


def _union(results, attr):
    sets = [getattr(r.live, attr) for _, _, r in results]
    if any(x is None for x in sets):
        return None
    out = set()
    for x in sets:
        out |= x
    return out


def _mode_table(results) -> str:
    defs, pols = [], []
    for d, p, _ in results:
        if d not in defs:
            defs.append(d)
        if p not in pols:
            pols.append(p)
    cell = {(d, p): r for d, p, r in results}
    head = '<TD BGCOLOR="#eeeeee"> </TD>' + "".join(
        f'<TD BGCOLOR="#eeeeee"><B>policy: {esc(p)}</B></TD>' for p in pols)
    rows = [f"<TR>{head}</TR>"]
    for d in defs:
        tds = f'<TD BGCOLOR="#eeeeee" ALIGN="LEFT"><B>definition: {esc(d)}</B></TD>'
        for p in pols:
            r = cell.get((d, p))
            if r is None:
                tds += "<TD>-</TD>"
            else:
                tds += (f'<TD ALIGN="LEFT"><FONT COLOR="{_verdict_color(r)}"><B>'
                        f'{esc(_result_text(r))}</B></FONT></TD>')
        rows.append(f"<TR>{tds}</TR>")
    return ('<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#999999">'
            + "".join(rows) + "</TABLE>")


def _spec_combined(A, B, results, title) -> Spec:
    q = results[0][2].q
    kind_of = {UNIQUE: "match", AMBIGUOUS: "candidate", STUCK: "candidate", NO_MATCH: "nomatch"}
    head_of = {"match": "corresponds to", "candidate": "possible match", "stuck": "B gets stuck",
               "nomatch": "not a match", "noacc": ""}
    tag_of = {"match": "match", "candidate": "candidate", "stuck": "stuck here", "nomatch": "not accepting"}
    items = {}                                   # (kind, target, word) -> [modes, a_trace, b_trace]
    for d, p, r in results:
        for w in r.witnesses:
            if w.b_trace is None:
                kind, target = "noacc", None
            elif w.b_state is None:
                kind, target = "stuck", w.b_trace.stuck[1]
            else:
                kind, target = kind_of[r.verdict], w.b_state
            it = items.setdefault((kind, target, w.word), [[], w.a_trace, w.b_trace])
            it[0].append((d, p))
    match_targets = {t for (k, t, _) in items if k == "match"}
    color_of, pi = {}, 0
    for kind, target, _ in items:
        if (kind, target) in color_of:
            continue
        if kind in ("stuck", "nomatch", "noacc"):
            color_of[(kind, target)] = RED
        elif kind == "match" and len(match_targets) == 1:
            color_of[(kind, target)] = GREEN
        else:
            color_of[(kind, target)] = PALETTE[pi % len(PALETTE)]
            pi += 1
    groups, roles = [], {}
    for (kind, target, word), (modes, at, bt) in items.items():
        col = color_of[(kind, target)]
        groups.append(Group(col, head_of[kind], target, word, at, bt, _modes_caption(modes)))
        if target is not None:
            tag, prev = tag_of[kind], roles.get(target)
            if prev is None:
                roles[target] = (col, tag)
            elif tag not in prev[1]:
                roles[target] = (prev[0], f"{prev[1]} / {tag}")
    unreachable = all(r.verdict == UNREACHABLE for _, _, r in results)
    verdicts = {r.verdict for _, _, r in results}
    gray = (GRAY_FILL, "not on any history of the current state")
    legend = [(GOLD, "current state of A (unreachable)" if unreachable else "current state of A")]
    if unreachable:
        legend += [("#ffffff", "reachable from the start state"), (GRAY_FILL, "not reachable")]
    else:
        if UNIQUE in verdicts:
            legend.append((_mix(GREEN), "UNIQUE: corresponding state of B"))
        if AMBIGUOUS in verdicts or STUCK in verdicts:
            legend.append((_mix(PALETTE[0]), "AMBIGUOUS: candidate states of B (one colour per candidate)"))
        if STUCK in verdicts or NO_MATCH in verdicts:
            legend.append((_mix(RED), "STUCK / NO_MATCH"))
        legend.append(gray)
    n = len(results)
    live = Live(_union(results, "a_states"), _union(results, "a_edges"),
                _union(results, "b_states"), _union(results, "b_edges"))
    note = ("every arrow is labelled with the modes that produce it; accepting states declared in the files"
            if A.explicit_accepting or B.explicit_accepting
            else "every arrow is labelled with the modes that produce it")
    return Spec(q, unreachable, live, groups, roles, f"results: see the table above",
                title or "State mapping: old automaton A -> new automaton B",
                f"Results of all {n} modes on one picture", note, legend, _mode_table(results))


# ----------------------------------------------------------------- dot building
def _node(nid, label, fill="white", color="#444444", fontcolor="black", pen=1.2, peri=1):
    return (f'    {nid} [label=<{label}>, fillcolor="{fill}", color="{color}", '
            f'fontcolor="{fontcolor}", penwidth={pen}, peripheries={peri}];')


def _edge_colors(traces_and_colors):
    colors, skips = defaultdict(list), []
    for t, col in traces_and_colors:
        if t is None:
            continue
        for src, c, dst, skip in t.steps:
            if skip:
                skips.append((src, c, col))
            elif col not in colors[(src, c, dst)]:
                colors[(src, c, dst)].append(col)
    return colors, skips


def _edges(M, ids, colors, skips, live_edges):
    groups = defaultdict(lambda: defaultdict(list))
    for (s, c), d in M.delta.items():
        cols = tuple(colors.get((s, c, d), ()))
        live = cols != () or live_edges is None or (s, c, d) in live_edges
        groups[(s, d)][(cols, live)].append(c)
    out = []
    for (s, d), parts in groups.items():
        for (cols, live), letters in parts.items():
            lab = esc(_label(letters, M.sigma))
            if cols:
                a = f'color="{":".join(cols)}", fontcolor="{cols[0]}", penwidth=3.2'
            elif live:
                a = ""
            else:
                a = f'color="{GRAY_LINE}", fontcolor="{GRAY_TEXT}"'
            out.append(f'    {ids[s]} -> {ids[d]} [label="{lab}"{", " + a if a else ""}];')
    by_state = defaultdict(list)
    for s, c, col in skips:
        by_state[(s, col)].append(c)
    for (s, col), letters in by_state.items():
        lab = esc(_label(sorted(set(letters)), M.sigma)) + " (skip)"
        out.append(f'    {ids[s]} -> {ids[s]} [label="{lab}", style=dashed, color="{col}", '
                   f'fontcolor="{col}", penwidth=2.4];')
    return out


def _dot(A, B, sp: Spec) -> str:
    ida = {s: f"A{i}" for i, s in enumerate(A.states)}
    idb = {s: f"B{i}" for i, s in enumerate(B.states)}
    a_col, a_skip = _edge_colors([(g.a_trace, g.color) for g in sp.groups])
    b_col, b_skip = _edge_colors([(g.b_trace, g.color) for g in sp.groups])
    la, lb = sp.live.a_states, sp.live.b_states

    L = ["digraph G {",
         '  graph [fontname="%s", rankdir=LR, pad="0.35", nodesep="0.55", ranksep="0.85", newrank=true];' % FONT,
         f'  node [fontname="{FONT}", fontsize=15, shape=ellipse, style=filled, fillcolor=white, '
         f'color="#444444", penwidth=1.2];',
         f'  edge [fontname="{FONT}", fontsize=13, color="#444444", fontcolor="#333333", arrowsize=0.8];']

    CA = ["  subgraph cluster_A {",
          f'    label=<<B>OLD automaton A</B>  (current state: {esc(sp.q)})>; labeljust=l; labelloc=t; '
          f'fontsize=18; style="rounded,filled"; fillcolor="{BG_A}"; color="{BORDER_A}"; margin=20;',
          '    A_init [shape=point, width=0.14, label="", fillcolor="#444444"];',
          f'    A_init -> {ida[A.start]};']
    for s in A.states:
        peri = 2 if (A.explicit_accepting and s in A.accepting) else 1
        if s == sp.q:
            border = RED if sp.unreachable else GOLD_DARK
            extra = "unreachable" if sp.unreachable else "current"
            CA.append(_node(ida[s], f"{esc(s)}<BR/>({extra})", GOLD, border, "black", 3.2, 2))
        elif la is not None and s not in la:
            CA.append(_node(ida[s], esc(s), GRAY_FILL, GRAY_LINE, GRAY_TEXT, 1.2, peri))
        else:
            CA.append(_node(ida[s], esc(s), peri=peri))
    CA += _edges(A, ida, a_col, a_skip, sp.live.a_edges)
    CA.append("  }")

    CB = ["  subgraph cluster_B {",
          f'    label=<<B>NEW automaton B</B>  ({esc(sp.result_text)})>; labeljust=l; labelloc=b; '
          f'fontsize=18; style="rounded,filled"; fillcolor="{BG_B}"; color="{BORDER_B}"; margin=20;',
          '    B_init [shape=point, width=0.14, label="", fillcolor="#444444"];',
          f'    B_init -> {idb[B.start]};']
    for s in B.states:
        peri = 2 if (B.explicit_accepting and s in B.accepting) else 1
        if s in sp.roles:
            col, tag = sp.roles[s]
            CB.append(_node(idb[s], f"{esc(s)}<BR/>({esc(tag)})", _mix(col, 0.82), col, "black", 3.6, peri))
        elif lb is not None and s not in lb:
            CB.append(_node(idb[s], esc(s), GRAY_FILL, GRAY_LINE, GRAY_TEXT, 1.2, peri))
        else:
            CB.append(_node(idb[s], esc(s), peri=peri))
    CB += _edges(B, idb, b_col, b_skip, sp.live.b_edges)
    seen = set()
    for k, g in enumerate(sp.groups):
        if g.b_trace is not None and g.b_trace.stuck is not None:
            _, s, c = g.b_trace.stuck
            if (s, c) in seen:
                continue
            seen.add((s, c))
            CB.append(f'    BX{k} [shape=box, style="filled,dashed", fillcolor="{_mix(RED, .88)}", color="{RED}", '
                      f'fontcolor="{RED}", label=<<B>STUCK</B><BR/>no transition>];')
            CB.append(f'    {idb[s]} -> BX{k} [label="{esc(c)}", style=dashed, color="{RED}", '
                      f'fontcolor="{RED}", penwidth=2.4];')
    CB.append("  }")

    has_arrow = any(g.target is not None for g in sp.groups)
    # without a correspondence arrow dot stacks the two components in reverse order
    L += (CA + CB) if has_arrow else (CB + CA)
    # invisible arrow A -> B (same form as the visible ones): keeps A above B
    L.append(f'  {ida[sp.q]} -> {idb[B.start]} [style=invis, constraint=false];')

    arrows = {}                                   # (target, word) -> [groups]; same endpoints share one arrow
    for g in sp.groups:
        if g.target is not None:
            arrows.setdefault((g.target, g.word), []).append(g)
    for (target, word), gs in arrows.items():
        colors = list(dict.fromkeys(g.color for g in gs))
        rows = ""
        for g in gs:
            rows += f'<TR><TD><FONT COLOR="{g.color}"><B>{esc(g.head)}</B></FONT></TD></TR>'
            if g.caption:
                rows += f'<TR><TD><FONT COLOR="{g.color}" POINT-SIZE="11"><I>{esc(g.caption)}</I></FONT></TD></TR>'
        lab = ('<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2" BGCOLOR="white">'
               f'{rows}<TR><TD><FONT COLOR="{colors[0]}">history: {esc(_word(word))}</FONT></TD></TR></TABLE>>')
        L.append(f'  {ida[sp.q]} -> {idb[target]} [style=dashed, penwidth=3, color="{":".join(colors)}", '
                 f'constraint=false, label={lab}];')

    cells = ""
    for fill, text in sp.legend:
        cells += (f'<TD BGCOLOR="{fill}" BORDER="1" WIDTH="22" HEIGHT="22" FIXEDSIZE="TRUE"> </TD>'
                  f'<TD ALIGN="LEFT">{esc(text)}</TD><TD WIDTH="10"> </TD>')
    table = f'<TR><TD ALIGN="LEFT">{sp.table_html}</TD></TR>' if sp.table_html else ""
    header = ('<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4">'
              f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="26"><B>{esc(sp.title)}</B></FONT></TD></TR>'
              f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="17">{esc(sp.subtitle)}</FONT></TD></TR>'
              f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="13" COLOR="#777777">{esc(sp.note)}</FONT></TD></TR>'
              f'{table}'
              f'<TR><TD ALIGN="LEFT"><TABLE BORDER="0" CELLBORDER="0" CELLSPACING="3" CELLPADDING="2">'
              f'<TR>{cells}</TR></TABLE></TD></TR></TABLE>')
    # set last, so that the clusters do not inherit this label
    L.append(f'  graph [label=<{header}>, labelloc=t, labeljust=l];')
    L.append("}")
    return "\n".join(L)


def build_dot(A, B, r, title=None) -> str:
    return _dot(A, B, _spec_single(A, B, r, title))


def build_combined_dot(A, B, results, title=None) -> str:
    return _dot(A, B, _spec_combined(A, B, results, title))


# ----------------------------------------------------------------------- render
def _render_dot(dot_text, out_path, fmt, dpi) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    exe = _dot_executable()
    if exe is None:
        out_path.with_suffix(".dot").write_text(dot_text, encoding="utf-8")
        raise GraphvizMissing(
            "Graphviz 'dot' was not found; install Graphviz (https://graphviz.org/download/) "
            f"to render pictures. The DOT source was saved to {out_path.with_suffix('.dot')}")
    proc = subprocess.run([exe, f"-T{fmt}", f"-Gdpi={dpi}", "-o", str(out_path)],
                          input=dot_text.encode("utf-8"), capture_output=True)
    if proc.returncode != 0:
        out_path.with_suffix(".dot").write_text(dot_text, encoding="utf-8")
        raise RuntimeError("dot failed: " + proc.stderr.decode("utf-8", "replace"))
    return out_path


def render(A, B, r, out_path, title=None, fmt="png", dpi=100) -> Path:
    """One mode.  On failure the .dot source is saved next to ``out_path``."""
    return _render_dot(build_dot(A, B, r, title), out_path, fmt, dpi)


def render_combined(A, B, results, out_path, title=None, fmt="png", dpi=100) -> Path:
    """Several modes on one picture.  results = [(definition, policy, Result), ...]."""
    return _render_dot(build_combined_dot(A, B, results, title), out_path, fmt, dpi)
