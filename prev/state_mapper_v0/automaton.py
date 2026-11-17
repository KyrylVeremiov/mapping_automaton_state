"""Deterministic finite automata with partial transition functions.

Text format (``*.aut``), one item per line, ``#`` starts a comment::

    name: optional human readable title
    alphabet: a b c          # optional, letters are also collected from transitions
    start: s0                # required
    accept: s1 s2            # optional; if omitted EVERY state is accepting
    states: s0 s1 s2 trap    # optional; only needed for states without transitions
    s0 -a-> s1               # a single letter
    s0 -a,b-> s1             # several letters
    s0 -*-> s2               # any letter
    s0 -!a-> s2              # any letter except a   (also  -!a,b->)

A letter is any token without whitespace and commas.  Several transitions of one
state may overlap only through the "else" rule, which keeps the automaton
deterministic:   explicit letter  >  ``!``-transition  >  ``*``-transition.
Two ``!``-transitions that cover a common letter with different targets are rejected.

The alphabet used for both automata is the union of the declared alphabets and all
letters that occur in either file; ``*`` and ``!`` are expanded over that union.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

LETTERS, NOT, ANY = "letters", "not", "any"

_TRANSITION = re.compile(r"^(\S+)\s+-\s*(.*?)\s*->\s*(\S+)$")
_KEYVAL = re.compile(r"^(name|title|alphabet|start|accept|states)\s*:\s*(.*)$", re.IGNORECASE)


class AutomatonError(ValueError):
    """Raised for malformed or non-deterministic automata."""


@dataclass(frozen=True)
class RawTransition:
    src: str
    kind: str          # LETTERS / NOT / ANY
    letters: tuple     # letters (LETTERS) or excluded letters (NOT)
    dst: str
    line: int


class Automaton:
    """A DFA (Q, Sigma, delta, start, F) where delta is a *partial* function."""

    def __init__(self, source: str = "<automaton>"):
        self.source = source
        self.name = ""
        self.states: list = []
        self.start = None
        self.declared_alphabet: list = []
        self.declared_accepting = None      # None => all states accepting
        self.raw: list = []
        # filled in by compile():
        self.sigma: list = []
        self.delta: dict = {}               # (state, letter) -> state
        self.accepting: set = set()

    # ---------------------------------------------------------------- building
    def add_state(self, s: str) -> None:
        if s not in self.states:
            self.states.append(s)

    @property
    def explicit_accepting(self) -> bool:
        """True if the file declares its accepting states (else all are accepting)."""
        return bool(self.declared_accepting)

    def letters(self) -> set:
        """All letters mentioned in the file (declared or in transitions)."""
        out = set(self.declared_alphabet)
        for t in self.raw:
            out.update(t.letters)
        return out

    # ---------------------------------------------------------------- compiling
    def compile(self, sigma) -> None:
        """Expand ``*`` / ``!`` over ``sigma`` and build the partial table delta."""
        self.sigma = list(sigma)
        alphabet = set(sigma)
        by_src: dict = {}
        for t in self.raw:
            by_src.setdefault(t.src, []).append(t)

        delta = {}
        for q in self.states:
            explicit, nots, anys = {}, [], []
            for t in by_src.get(q, []):
                if t.kind == LETTERS:
                    for c in t.letters:
                        if c in explicit and explicit[c][0] != t.dst:
                            raise AutomatonError(
                                f"{self.source}: state '{q}' has two different transitions on "
                                f"'{c}' (lines {explicit[c][1]} and {t.line}): not deterministic")
                        explicit[c] = (t.dst, t.line)
                elif t.kind == NOT:
                    nots.append(t)
                else:
                    anys.append(t)
            if len({t.dst for t in anys}) > 1:
                raise AutomatonError(f"{self.source}: state '{q}' has several different '*' transitions")
            for i, t1 in enumerate(nots):
                for t2 in nots[i + 1:]:
                    common = alphabet - set(t1.letters) - set(t2.letters)
                    if common and t1.dst != t2.dst:
                        raise AutomatonError(
                            f"{self.source}: state '{q}': '!' transitions on lines {t1.line} and "
                            f"{t2.line} overlap on {sorted(common)} with different targets")
            for c in sigma:
                if c in explicit:
                    delta[(q, c)] = explicit[c][0]
                    continue
                hit = [t for t in nots if c not in t.letters]
                if hit:
                    delta[(q, c)] = hit[0].dst
                elif anys:
                    delta[(q, c)] = anys[0].dst
        self.delta = delta
        self.accepting = set(self.declared_accepting) if self.declared_accepting else set(self.states)

    # ---------------------------------------------------------------- queries
    def step(self, q, c):
        """One-step partial transition function; None if undefined."""
        return self.delta.get((q, c))

    def is_complete(self) -> bool:
        return all((q, c) in self.delta for q in self.states for c in self.sigma)


# -------------------------------------------------------------------- parsing
def _split_list(text: str) -> list:
    return [x for x in re.split(r"[\s,]+", text.strip()) if x]


def _parse_label(label: str, source: str, line: int):
    label = label.strip()
    if label == "*":
        return ANY, ()
    kind = LETTERS
    if label.startswith("!"):
        kind, label = NOT, label[1:]
    letters = tuple(x.strip() for x in label.split(",") if x.strip())
    if not letters:
        raise AutomatonError(f"{source}:{line}: empty transition label")
    for c in letters:
        if re.search(r"\s", c) or c == "*" or c.startswith("!"):
            raise AutomatonError(f"{source}:{line}: bad letter {c!r}")
    return kind, letters


def parse_automaton(text: str, source: str = "<string>") -> Automaton:
    a = Automaton(source)
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _KEYVAL.match(line)
        if m:
            key, value = m.group(1).lower(), m.group(2).strip()
            if key in ("name", "title"):
                a.name = value
            elif key == "alphabet":
                a.declared_alphabet += _split_list(value)
            elif key == "start":
                if not value or len(value.split()) != 1:
                    raise AutomatonError(f"{source}:{lineno}: 'start' needs exactly one state")
                a.start = value
                a.add_state(value)
            elif key == "accept":
                a.declared_accepting = (a.declared_accepting or []) + _split_list(value)
                for s in _split_list(value):
                    a.add_state(s)
            elif key == "states":
                for s in _split_list(value):
                    a.add_state(s)
            continue
        m = _TRANSITION.match(line)
        if not m:
            raise AutomatonError(f"{source}:{lineno}: cannot parse line: {raw.strip()!r}")
        src, label, dst = m.groups()
        kind, letters = _parse_label(label, source, lineno)
        a.add_state(src)
        a.add_state(dst)
        a.raw.append(RawTransition(src, kind, letters, dst, lineno))
    if a.start is None:
        raise AutomatonError(f"{source}: no 'start:' line")
    return a


def build_automaton(source, name, start, transitions, states=(), accepting=None, alphabet=()) -> Automaton:
    """Common constructor for all file formats.

    transitions: iterable of (src, label, dst); label is a letter, 'a,b', '*' or '!a'.
    accepting  : iterable of state names; None or empty means "not declared" (all accepting).
    """
    a = Automaton(source)
    a.name = name or ""
    a.declared_alphabet = list(alphabet)
    if start is None or str(start) == "":
        raise AutomatonError(f"{source}: no start state")
    a.start = str(start)
    a.add_state(a.start)
    for s in states:
        a.add_state(str(s))
    for i, (src, label, dst) in enumerate(transitions, 1):
        kind, letters = _parse_label(str(label), source, i)
        a.add_state(str(src))
        a.add_state(str(dst))
        a.raw.append(RawTransition(str(src), kind, letters, str(dst), i))
    if accepting:
        a.declared_accepting = [str(x) for x in accepting]
        for x in a.declared_accepting:
            a.add_state(x)
    return a


def load_automaton(path, fmt: str = "auto") -> Automaton:
    """Load an automaton; fmt = auto | aut | json | dot | jff | att (auto: by extension / content)."""
    from prev.state_mapper_v0.formats import load_automaton as _load     # imported lazily: formats imports this module
    return _load(path, fmt)


def load_pair(old_path, new_path, fmt: str = "auto"):
    """Load A (old) and B (new) and compile both over the common alphabet."""
    A, B = load_automaton(old_path, fmt), load_automaton(new_path, fmt)
    sigma = sorted(A.letters() | B.letters())
    if not sigma:
        raise AutomatonError("the alphabet is empty: declare it with 'alphabet: a b ...'")
    A.compile(sigma)
    B.compile(sigma)
    return A, B
