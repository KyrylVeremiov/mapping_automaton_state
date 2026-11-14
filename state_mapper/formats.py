"""Readers for popular automaton file formats.  The format is detected automatically.

  .json        JSON, several common dialects (see ``_json_to_parts``):
                 {"start": "S0", "transitions": [["S0", "a", "S1"], ...]}
                 {"initial_state": "q0", "final_states": [...], "input_symbols": [...],
                  "transitions": {"q0": {"a": "q1"}, ...}}          (python 'automata-lib' style)
                 {"transitions": [{"from": "q0", "symbol": "a", "to": "q1"}, ...], ...}
  .dot / .gv   Graphviz: edges with ``label``; ``doublecircle`` nodes are accepting;
               the start state is the target of an arrow from an invisible/point node
  .jff         JFLAP (XML) finite automata
  .fsm / .att  AT&T / OpenFst text format:  ``src dst label`` per arc, final states on their own lines;
               the start state is the source of the first arc
  .aut         the project's own text format (see automaton.py)

In every format a transition label may be a letter, a list ``a,b``, ``*`` (any letter) or ``!a`` (any
letter except a).  If no accepting state is marked, all states are accepting.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from automaton import (_KEYVAL, _TRANSITION, Automaton, AutomatonError, build_automaton,
                       parse_automaton)

FORMATS = ("auto", "aut", "json", "dot", "jff", "att")
_EXTENSIONS = {".aut": "aut", ".json": "json", ".dot": "dot", ".gv": "dot",
               ".jff": "jff", ".jflap": "jff", ".xml": "jff",
               ".fsm": "att", ".att": "att", ".fst": "att"}
_EPSILON = {"<eps>", "eps", "epsilon", "\u03b5", "\u03bb", "lambda"}


# ------------------------------------------------------------------- detection
def _strip_dot_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*#.*$", "", text)
    return re.sub(r"//[^\n]*", "", text)


def detect_format(path: Path, text: str) -> str:
    fmt = _EXTENSIONS.get(path.suffix.lower())
    if fmt:
        return fmt
    s = text.lstrip("\ufeff \t\r\n")
    if s.startswith(("{", "[")):
        return "json"
    if s.startswith("<"):
        return "jff"
    if re.search(r"\b(?:di)?graph\b[^{]*\{", _strip_dot_comments(text)):
        return "dot"
    lines = [ln.split("#", 1)[0].strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if any(_KEYVAL.match(ln) or _TRANSITION.match(ln) for ln in lines):
        return "aut"
    if lines and all(1 <= len(ln.split()) <= 5 for ln in lines) and any(len(ln.split()) >= 3 for ln in lines):
        return "att"
    raise AutomatonError(f"{path}: cannot detect the file format; use --format {{{','.join(FORMATS[1:])}}}")


# ------------------------------------------------------------------------ JSON
def _pick(d: dict, keys):
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in low:
            return low[k.lower()], True
    return None, False


def _scalar(x, what, source):
    if isinstance(x, (list, tuple)):
        if len(x) != 1:
            raise AutomatonError(f"{source}: {what} must be a single value, got {x!r}")
        x = x[0]
    if isinstance(x, (dict, bool)) or x is None:
        raise AutomatonError(f"{source}: bad {what}: {x!r}")
    return str(x)


def _label_of(x, source) -> str:
    if isinstance(x, (list, tuple)):
        return ",".join(_scalar(i, "letter", source) for i in x)
    return _scalar(x, "letter", source)


def _json_to_parts(data, source):
    if isinstance(data, list):
        data = {"transitions": data}
    if not isinstance(data, dict):
        raise AutomatonError(f"{source}: JSON must be an object (or a list of transitions)")

    start, has = _pick(data, ("start", "initial", "initial_state", "start_state", "init", "q0",
                              "initial_states", "start_states"))
    start = _scalar(start, "start state", source) if has else None
    acc, has = _pick(data, ("accept", "accepting", "accepting_states", "accept_states", "final",
                            "finals", "final_states", "F", "accepted"))
    accepting = [_scalar(x, "accepting state", source) for x in acc] if has and isinstance(acc, list) else (
        [_scalar(acc, "accepting state", source)] if has and acc is not None else [])
    alpha, has = _pick(data, ("alphabet", "input_symbols", "sigma", "symbols"))
    alphabet = [_scalar(x, "letter", source) for x in alpha] if has and isinstance(alpha, list) else []

    states = []
    st, has = _pick(data, ("states", "Q"))
    if has and isinstance(st, list):
        for item in st:
            if isinstance(item, dict):
                name, ok = _pick(item, ("name", "id", "label", "state"))
                if not ok:
                    raise AutomatonError(f"{source}: state object without a name: {item!r}")
                name = _scalar(name, "state name", source)
                states.append(name)
                init, _ = _pick(item, ("initial", "start", "is_initial"))
                fin, _ = _pick(item, ("final", "accepting", "accept", "is_final"))
                if init is True and start is None:
                    start = name
                if fin is True:
                    accepting.append(name)
            else:
                states.append(_scalar(item, "state name", source))

    trs = []
    tr, has = _pick(data, ("transitions", "delta", "edges", "arcs"))
    if not has:
        raise AutomatonError(f"{source}: no 'transitions' in the JSON file")
    if isinstance(tr, dict):                               # {"q0": {"a": "q1"}}
        for src, row in tr.items():
            if not isinstance(row, dict):
                raise AutomatonError(f"{source}: transitions of '{src}' must be an object letter -> state")
            for letter, dst in row.items():
                for d in (dst if isinstance(dst, list) else [dst]):
                    trs.append((str(src), str(letter), _scalar(d, "target state", source)))
    elif isinstance(tr, list):
        for item in tr:
            if isinstance(item, (list, tuple)) and len(item) == 3:       # ["S0", "a", "S1"]
                trs.append((_scalar(item[0], "source state", source), _label_of(item[1], source),
                            _scalar(item[2], "target state", source)))
            elif isinstance(item, dict):                                  # {"from":..,"symbol":..,"to":..}
                src, o1 = _pick(item, ("from", "src", "source", "state", "current", "origin"))
                let, o2 = _pick(item, ("symbol", "letter", "label", "input", "on", "char", "read", "sym", "event"))
                dst, o3 = _pick(item, ("to", "dst", "target", "next", "next_state", "dest", "destination"))
                if not (o1 and o2 and o3):
                    raise AutomatonError(f"{source}: transition object needs from/symbol/to: {item!r}")
                trs.append((_scalar(src, "source state", source), _label_of(let, source),
                            _scalar(dst, "target state", source)))
            else:
                raise AutomatonError(f"{source}: cannot read transition {item!r}")
    else:
        raise AutomatonError(f"{source}: 'transitions' must be a list or an object")
    name, _ = _pick(data, ("name", "title"))
    return dict(name=str(name) if name else "", start=start, transitions=trs, states=states,
                accepting=accepting, alphabet=alphabet)


def parse_json(text: str, source: str) -> Automaton:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AutomatonError(f"{source}: invalid JSON: {e}") from e
    parts = _json_to_parts(data, source)
    if parts["start"] is None:
        raise AutomatonError(f"{source}: no start state (expected key 'start' or 'initial_state')")
    return build_automaton(source, **parts)


# ------------------------------------------------------------------------- DOT
_ID = r'"(?:[^"\\]|\\.)*"|[^\s"\[\]=;,{}]+'


def _unquote(x: str) -> str:
    x = x.strip()
    if len(x) >= 2 and x[0] == '"' and x[-1] == '"':
        x = x[1:-1].replace('\\"', '"')
    if x.startswith("<") and x.endswith(">"):           # HTML-like label: drop the tags
        x = re.sub(r"<[^>]*>", "", x[1:-1])
    return x.strip()


def _dot_statements(text: str):
    """Split DOT text into statements (braces, ';' and newlines outside quotes/brackets separate)."""
    out, cur, quote, depth = [], [], False, 0
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and i + 1 < len(text):
                cur.append(text[i + 1])
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
            cur.append(ch)
        elif ch == "[":
            depth += 1
            cur.append(ch)
        elif ch == "]":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif depth == 0 and ch in "{};\n":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def _dot_attrs(s: str) -> dict:
    return {m.group(1).lower(): _unquote(m.group(2))
            for m in re.finditer(r'(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|<[^>]*>|[^,;\s\]]+)', s)}


def parse_dot(text: str, source: str) -> Automaton:
    nodes, edges = {}, []                      # name -> attrs ; (src, dst, attrs)
    shape, peripheries, gname = "ellipse", 1, ""

    def touch(n):
        if n not in nodes:
            nodes[n] = {"shape": shape, "peripheries": str(peripheries)}
        return nodes[n]

    for stmt in _dot_statements(_strip_dot_comments(text)):
        m = re.match(r"^(?:strict\s+)?(?:di)?graph\b\s*(.*)$", stmt, re.I | re.S)
        if m:
            gname = _unquote(m.group(1)) if m.group(1) else ""
            continue
        if re.match(r"^subgraph\b", stmt, re.I) or re.match(r"^\w+\s*=\s*[^\[]+$", stmt):
            continue
        br = stmt.find("[")
        head, attrs = (stmt[:br], _dot_attrs(stmt[br:])) if br >= 0 else (stmt, {})
        head = head.strip()
        low = head.lower()
        if low in ("node", "edge", "graph"):
            if low == "node":
                shape = attrs.get("shape", shape)
                peripheries = int(attrs["peripheries"]) if attrs.get("peripheries", "").isdigit() else peripheries
            continue
        if "->" in head or "--" in head:
            ids = [_unquote(x) for x in re.split(r"->|--", head)]
            ids = [re.sub(r":\w+$", "", x) for x in ids]            # drop ports
            for n in ids:
                touch(n)
            for u, v in zip(ids, ids[1:]):
                edges.append((u, v, attrs))
        else:
            for tok in re.findall(_ID, head):
                node = touch(_unquote(tok))
                if "shape" in attrs:
                    node["shape"] = attrs["shape"]
                if "peripheries" in attrs:
                    node["peripheries"] = attrs["peripheries"]
                if "label" in attrs:
                    node["label"] = attrs["label"]

    incoming = {v for _, v, _ in edges}
    entry = {n for n, a in nodes.items()
             if n not in incoming and (a["shape"] in ("point", "none", "plaintext", "plain")
                                       or all(not e[2].get("label", "").strip() for e in edges if e[0] == n)
                                       and any(e[0] == n for e in edges))}
    start, real = [], []
    for u, v, a in edges:
        if u in entry and not a.get("label", "").strip():
            start.append(v)
        elif u in entry:
            raise AutomatonError(f"{source}: node '{u}' looks like a start marker but has a labelled edge")
        else:
            real.append((u, v, a))
    if len(set(start)) != 1:
        raise AutomatonError(f"{source}: need exactly one start arrow (an unlabelled edge from an invisible "
                             f"'point' node); found {len(set(start))}")
    trs = []
    for u, v, a in real:
        label = a.get("label", "").strip()
        if not label:
            raise AutomatonError(f"{source}: edge {u} -> {v} has no label")
        if label.lower() in _EPSILON:
            raise AutomatonError(f"{source}: epsilon transitions are not supported (edge {u} -> {v})")
        trs.append((u, label, v))
    accepting = [n for n, a in nodes.items() if n not in entry and
                 (a["shape"] in ("doublecircle", "doubleoctagon", "tripleoctagon") or
                  (a["peripheries"].isdigit() and int(a["peripheries"]) >= 2))]
    states = [n for n in nodes if n not in entry]
    return build_automaton(source, gname, start[0], trs, states, accepting)


# ------------------------------------------------------------------------ JFLAP
def parse_jff(text: str, source: str) -> Automaton:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise AutomatonError(f"{source}: invalid XML: {e}") from e
    auto = root if root.tag == "automaton" else root.find(".//automaton")
    if auto is None:
        raise AutomatonError(f"{source}: no <automaton> element (a JFLAP file?)")
    kind = root.findtext("type")
    if kind not in (None, "fa"):
        raise AutomatonError(f"{source}: only finite automata (<type>fa</type>) are supported, got '{kind}'")
    names, order, start, accepting = {}, [], [], []
    for st in auto.findall("state"):
        sid = st.get("id")
        if sid is None:
            raise AutomatonError(f"{source}: <state> without id")
        names[sid] = st.get("name") or f"q{sid}"
    if len(set(names.values())) != len(names):                  # names must be unique
        names = {k: f"{v}#{k}" for k, v in names.items()}
    for st in auto.findall("state"):
        n = names[st.get("id")]
        order.append(n)
        if st.find("initial") is not None:
            start.append(n)
        if st.find("final") is not None:
            accepting.append(n)
    if len(start) != 1:
        raise AutomatonError(f"{source}: expected exactly one <initial/> state, found {len(start)}")
    trs = []
    for tr in auto.findall("transition"):
        f, t, rd = tr.findtext("from"), tr.findtext("to"), tr.find("read")
        letter = (rd.text or "").strip() if rd is not None else ""
        if f not in names or t not in names:
            raise AutomatonError(f"{source}: transition refers to an unknown state id")
        if not letter or letter.lower() in _EPSILON:
            raise AutomatonError(f"{source}: epsilon (lambda) transitions are not supported")
        trs.append((names[f], letter, names[t]))
    return build_automaton(source, "", start[0], trs, order, accepting)


# ----------------------------------------------------------- AT&T / OpenFst text
def parse_att(text: str, source: str) -> Automaton:
    start, trs, finals = None, [], []
    for n, raw in enumerate(text.splitlines(), 1):
        t = raw.split("#", 1)[0].split()
        if not t:
            continue
        if len(t) >= 3:
            if t[2].lower() in _EPSILON:
                raise AutomatonError(f"{source}:{n}: epsilon transitions are not supported")
            start = start if start is not None else t[0]
            trs.append((t[0], t[2], t[1]))
        elif len(t) in (1, 2):
            finals.append(t[0])                       # "state [weight]"
        else:
            raise AutomatonError(f"{source}:{n}: cannot parse line {raw.strip()!r}")
    if start is None:
        raise AutomatonError(f"{source}: no transitions found")
    return build_automaton(source, "", start, trs, accepting=finals)


# ------------------------------------------------------------------------ driver
def load_automaton(path, fmt: str = "auto") -> Automaton:
    path = Path(path)
    if fmt not in FORMATS:
        raise AutomatonError(f"unknown format '{fmt}' (choose from {', '.join(FORMATS)})")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise AutomatonError(f"cannot read {path}: {e}") from e
    kind = detect_format(path, text) if fmt == "auto" else fmt
    parser = {"aut": parse_automaton, "json": parse_json, "dot": parse_dot,
              "jff": parse_jff, "att": parse_att}[kind]
    a = parser(text, str(path))
    if not a.name:
        a.name = path.stem
    return a
