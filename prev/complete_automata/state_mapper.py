#!/usr/bin/env python3
"""
state_mapper - find the state of a NEW partial DFA that corresponds, "by the
past", to the current state of an OLD partial DFA.

Problem
-------
We have an old automaton A, its current state q, and a new automaton B.
The history that brought A into q is unknown (there is no log).  We look for
a state p of B such that the real history -- whatever it was -- brings B
into p as well.

Definitions
-----------
H_A(q) = { w : delta_A(start_A, w) = q }         all histories of q in A
N(q)   = { delta_B(start_B, w) : w in H_A(q) }   where "B has no transition"
                                                 is a separate value
                                                 (UNDEFINED = None)

Criterion
---------
A history-exact answer exists  <=>  q is reachable in A and N(q) = {p} for a
single real state p of B (in particular UNDEFINED is not in N(q)).
Then p is the answer, and it is unique.  Otherwise:

  * q is not reachable in A         -> UNREACHABLE (no history at all)
  * N(q) contains UNDEFINED         -> STUCK       (B cannot replay a history)
  * N(q) has >= 2 real states       -> AMBIGUOUS   (B separates histories that
                                                    A merged into q)

Algorithm
---------
H_A(q) is usually infinite (cycles), so words are not enumerated.  Instead we
run BFS over the product A x B starting from (start_A, start_B); B moves to
UNDEFINED when it has no transition and stays there.  A pair (a, b) is
reachable iff some word leads A to a and B to b.  Hence N(q) is exactly the
set of second components of reachable pairs (q, *).  BFS also gives the
shortest word for every pair, which we use as human-readable evidence.

Only A-states that can reach q are explored (everything else cannot lie on a
history of q), which does not change the answer but makes it faster.

Complexity (n = |Q_A| after trimming, m = |Q_B|, E = number of transitions of
trimmed A):  time O((m + 1) * E) <= O(n * m * k),  memory O(n * m).

Completely defined automata
---------------------------
If B is complete, "B has no transition" never happens: a forbidden event
leads to a trap (sink) state instead.  The algorithm cannot know which states
of B mean "error", so you name them: error_states={...}.  A history that
enters such a state counts as NOT replayable (STUCK), exactly as if B had no
transition there.  Without the declaration the trap is an ordinary state, and
a NOTE is printed when the chosen B state looks like a trap (absorbing in B
while the old state can still move on).

Final states are ignored: only the transition structure (the "past") matters.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, Hashable, Iterable, List, Optional, Tuple

State = Hashable
Symbol = str
Word = Tuple[Symbol, ...]
Pair = Tuple[State, Optional[State]]      # (state of A, state of B or None)
Parent = Dict[Pair, Optional[Tuple[Pair, Symbol]]]


# --------------------------------------------------------------------------
# Partial DFA
# --------------------------------------------------------------------------
class DFA:
    """Partial deterministic finite automaton (immutable after construction)."""

    _EDGE_RE = re.compile(r"^(\S+)\s+-(\S+?)->\s+(\S+)$")

    def __init__(self, start: State,
                 transitions: Iterable[Tuple[State, Symbol, State]],
                 states: Iterable[State] = ()):
        self.start = start
        self._delta: Dict[State, Dict[Symbol, State]] = {start: {}}
        for s in states:
            self._delta.setdefault(s, {})
        for src, sym, dst in transitions:
            row = self._delta.setdefault(src, {})
            if sym in row and row[sym] != dst:
                raise ValueError(
                    f"not deterministic: state {src!r} has two transitions "
                    f"on {sym!r}: -> {row[sym]!r} and -> {dst!r}")
            row[sym] = dst
            self._delta.setdefault(dst, {})
        # Cache sorted edge lists: gives deterministic BFS order and output.
        self._edges: Dict[State, Tuple[Tuple[Symbol, State], ...]] = {
            s: tuple(sorted(row.items(), key=lambda kv: str(kv[0])))
            for s, row in self._delta.items()
        }

    # ---- construction helpers ------------------------------------------
    @classmethod
    def from_text(cls, text: str) -> "DFA":
        """Parse 'start=s; s -a-> x; x -b-> q' (items split by ';' or newline).

        Several events with the same target may be written together:
        's -a,b-> x'.  If 'start=' is omitted, the source of the first
        transition is the start state.  State and event names must not
        contain whitespace; event names must not contain a comma.
        """
        start: Optional[str] = None
        edges: List[Tuple[str, str, str]] = []
        for item in re.split(r"[;\n]", text):
            item = item.strip()
            if not item or item.startswith("#"):
                continue
            if item.startswith("start="):
                start = item[len("start="):].strip()
                continue
            match = cls._EDGE_RE.match(item)
            if not match:
                raise ValueError(f"cannot parse transition: {item!r}")
            src, symbols, dst = match.groups()
            edges.extend((src, sym, dst) for sym in symbols.split(","))
        if start is None:
            if not edges:
                raise ValueError("start state is required")
            start = edges[0][0]
        return cls(start, edges)

    @classmethod
    def from_json_file(cls, path: str) -> "DFA":
        """Load {"start": "s", "transitions": [["s","a","x"], ...]}.
        An optional "states" list declares states without transitions."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return cls(data["start"], [tuple(t) for t in data["transitions"]],
                   data.get("states", ()))

    # ---- basic queries ---------------------------------------------------
    @property
    def states(self) -> FrozenSet[State]:
        return frozenset(self._delta)

    @property
    def alphabet(self) -> FrozenSet[Symbol]:
        return frozenset(sym for row in self._delta.values() for sym in row)

    @property
    def num_transitions(self) -> int:
        return sum(len(row) for row in self._delta.values())

    def step(self, state: State, symbol: Symbol) -> Optional[State]:
        """Next state, or None if the transition is not defined."""
        return self._delta.get(state, {}).get(symbol)

    def edges_from(self, state: State) -> Tuple[Tuple[Symbol, State], ...]:
        return self._edges.get(state, ())

    def run(self, word: Iterable[Symbol], state: Optional[State] = None,
            error_states: FrozenSet[State] = frozenset()) -> Optional[State]:
        """State reached by `word` (from the start state by default), or
        None if some transition on the way is undefined or enters one of
        `error_states`."""
        current = self.start if state is None else state
        for sym in word:
            current = self.step(current, sym)
            if current is None or current in error_states:
                return None
        return current

    def can_reach(self, target: State) -> set:
        """All states from which `target` is reachable (including itself)."""
        reverse: Dict[State, List[State]] = {}
        for src, row in self._delta.items():
            for dst in row.values():
                reverse.setdefault(dst, []).append(src)
        seen = {target}
        stack = [target]
        while stack:
            cur = stack.pop()
            for prev in reverse.get(cur, ()):
                if prev not in seen:
                    seen.add(prev)
                    stack.append(prev)
        return seen

    def is_absorbing(self, state: State) -> bool:
        """True if the state has transitions and all of them loop back to itself."""
        edges = self._edges.get(state, ())
        return bool(edges) and all(dst == state for _, dst in edges)

    def is_complete(self, alphabet: Optional[Iterable[Symbol]] = None) -> bool:
        """True if every state has a transition on every symbol of `alphabet`
        (default: the automaton's own alphabet)."""
        symbols = self.alphabet if alphabet is None else frozenset(alphabet)
        return all(sym in row for row in self._delta.values() for sym in symbols)

    def completed(self, alphabet: Optional[Iterable[Symbol]] = None,
                  sink: State = "sink") -> "DFA":
        """Completely defined copy: every missing transition goes to `sink`
        (an absorbing state that is added only if something is missing).
        Remember to declare `sink` in error_states when mapping into this copy."""
        symbols = sorted(self.alphabet if alphabet is None else alphabet, key=str)
        edges = [(s, sym, dst) for s, row in self._delta.items() for sym, dst in row.items()]
        missing = [(s, sym, sink) for s, row in self._delta.items()
                   for sym in symbols if sym not in row]
        if missing:
            if sink in self._delta:
                raise ValueError(f"sink name {sink!r} is already a state")
            edges += missing + [(sink, sym, sink) for sym in symbols]
        return DFA(self.start, edges, self._delta.keys())

    def _bfs_order(self) -> List[State]:
        order = [self.start]
        seen = {self.start}
        for s in order:                      # list grows while iterating
            for _, dst in self._edges[s]:
                if dst not in seen:
                    seen.add(dst)
                    order.append(dst)
        rest = sorted((s for s in self._delta if s not in seen), key=str)
        return order + rest

    def describe(self, indent: str = "  ") -> str:
        """One line per (source, target): parallel events are joined as 'a,b'."""
        lines = []
        for src in self._bfs_order():
            grouped: Dict[State, List[Symbol]] = {}
            for sym, dst in self._edges[src]:
                grouped.setdefault(dst, []).append(sym)
            for dst, symbols in grouped.items():
                lines.append(f"{indent}{src} -{','.join(symbols)}-> {dst}")
        return "\n".join(lines) if lines else f"{indent}(no transitions)"


# --------------------------------------------------------------------------
# Words and traces (for readable output)
# --------------------------------------------------------------------------
def fmt_word(word: Word) -> str:
    return " ".join(str(s) for s in word) if word else "<empty>"


def _trace(dfa: DFA, word: Word, error_states: FrozenSet[State] = frozenset()) -> str:
    """'s -a-> x -b-> q'; shows '<undefined>' where the automaton gets stuck and
    marks the first error state that is entered."""
    state = dfa.start
    parts = [str(state)]
    for sym in word:
        nxt = dfa.step(state, sym)
        if nxt is None:
            parts += [f"-{sym}->", "<undefined>"]
            break
        if nxt in error_states:
            parts += [f"-{sym}->", f"{nxt} (error state)"]
            break
        parts += [f"-{sym}->", str(nxt)]
        state = nxt
    return " ".join(parts)


# --------------------------------------------------------------------------
# Product exploration
# --------------------------------------------------------------------------
def _explore(old: DFA, new: DFA, keep: Optional[set] = None,
             error_states: FrozenSet[State] = frozenset()) -> Parent:
    """BFS over the product old x new (new is completed with UNDEFINED=None).

    Entering a state of `error_states` counts as "B has no transition": the
    second component becomes UNDEFINED (None) and stays there.
    Returns a parent map: pair -> (previous pair, symbol) or None for the
    root.  If `keep` is given, only old-states in `keep` are visited.
    """
    root: Pair = (old.start, new.start)
    parent: Parent = {root: None}
    queue = deque([root])
    while queue:
        a, b = queue.popleft()
        for sym, a2 in old.edges_from(a):
            if keep is not None and a2 not in keep:
                continue
            b2 = None if b is None else new.step(b, sym)
            if b2 in error_states:
                b2 = None
            nxt: Pair = (a2, b2)
            if nxt not in parent:
                parent[nxt] = ((a, b), sym)
                queue.append(nxt)
    return parent


def _word_to(parent: Parent, pair: Pair) -> Word:
    """Shortest word that leads the product from the root to `pair`."""
    symbols: List[Symbol] = []
    while parent[pair] is not None:
        pair, sym = parent[pair]          # type: ignore[misc]
        symbols.append(sym)
    symbols.reverse()
    return tuple(symbols)


def distinguishing_word(dfa: DFA, p1: State, p2: State,
                        error_states: FrozenSet[State] = frozenset()) -> Optional[Word]:
    """Shortest event sequence allowed from exactly one of p1, p2 (or None
    if both states allow exactly the same event sequences).  A transition
    into one of `error_states` counts as "not allowed"."""
    root: Pair = (p1, p2)
    parent: Parent = {root: None}
    queue = deque([root])
    while queue:
        x, y = queue.popleft()
        symbols = sorted({s for s, _ in dfa.edges_from(x)} |
                         {s for s, _ in dfa.edges_from(y)}, key=str)
        for sym in symbols:
            x2, y2 = dfa.step(x, sym), dfa.step(y, sym)
            if x2 in error_states:
                x2 = None
            if y2 in error_states:
                y2 = None
            if (x2 is None) != (y2 is None):
                return _word_to(parent, (x, y)) + (sym,)
            if x2 is None:                # both undefined: nothing to compare
                continue
            nxt: Pair = (x2, y2)
            if nxt not in parent:
                parent[nxt] = ((x, y), sym)
                queue.append(nxt)
    return None


# --------------------------------------------------------------------------
# Result objects
# --------------------------------------------------------------------------
class Status(Enum):
    UNIQUE = "UNIQUE"            # exactly one corresponding state in B
    AMBIGUOUS = "AMBIGUOUS"      # B separates histories that A merged
    STUCK = "STUCK"              # B cannot replay some history of q
    UNREACHABLE = "UNREACHABLE"  # q has no history in A


@dataclass
class StuckWitness:
    """A history of q in A that B cannot replay."""
    history: Word       # shortest such history
    replayed: Word      # the part of it that B can replay
    event: Symbol       # first event that B rejects
    new_state: State    # B state in which `event` is not allowed
    into_error: Optional[State] = None   # declared error state the event leads to
                                         # (None: B simply has no such transition)


@dataclass
class MappingResult:
    status: Status
    current: State                      # q, the state of A that was asked about
    answer: Optional[State]             # p, only when status is UNIQUE
    candidates: Dict[State, Word]       # real B states in N(q) -> shortest history
    stuck: Optional[StuckWitness]       # not None if UNDEFINED is in N(q)
    explored_pairs: int                 # size of the explored product
    old: DFA
    new: DFA
    lenient: bool = False
    error_states: FrozenSet[State] = frozenset()   # B states declared as errors

    def short(self) -> str:
        if self.status is Status.UNIQUE:
            return f"UNIQUE -> '{self.answer}'"
        if self.status is Status.AMBIGUOUS:
            return "AMBIGUOUS -> {" + ", ".join(f"'{c}'" for c in self.candidates) + "}"
        return self.status.value

    # ---- visualization (implemented in visualize.py) ------------------------
    def to_dot(self, title: str = "") -> str:
        """Graphviz DOT source of a figure: old automaton, its current state,
        new automaton and the found correspondence."""
        from prev.complete_automata.visualize import to_dot
        return to_dot(self, title)

    def save_png(self, path: str, title: str = "", dpi: int = 130) -> None:
        """Render the figure to a PNG file (needs the Graphviz `dot` program)."""
        from prev.complete_automata.visualize import render_png
        render_png(self, path, title, dpi)

    # ---- human-readable explanation --------------------------------------
    def _evidence(self, word: Word, indent: str = "    ") -> List[str]:
        return [f"{indent}history '{fmt_word(word)}'",
                f"{indent}  in A: {_trace(self.old, word)}",
                f"{indent}  in B: {_trace(self.new, word, self.error_states)}"]

    @property
    def notes(self) -> List[str]:
        """Hints about answers that may be misleading (they are not errors)."""
        lines: List[str] = []
        if self.old.is_absorbing(self.current):
            return lines
        for cand in self.candidates:
            if self.new.is_absorbing(cand):
                lines += [f"NOTE: B state '{cand}' is absorbing (every transition loops back), "
                          f"but A state '{self.current}'",
                          "      can still move on. If it is a trap/error state of B, declare it "
                          "with",
                          f"      error_states={{'{cand}'}}: histories that end there are then "
                          "treated as rejected by B."]
        return lines

    def _stuck_lines(self, indent: str = "    ") -> List[str]:
        s = self.stuck
        assert s is not None
        where = (f"after '{fmt_word(s.replayed)}'" if s.replayed
                 else "at the very first event")
        return [f"{indent}history '{fmt_word(s.history)}' is possible in A:",
                f"{indent}  in A: {_trace(self.old, s.history)}",
                f"{indent}  in B: {_trace(self.new, s.history, self.error_states)}",
                f"{indent}B rejects it {where}: event '{s.event}' is not "
                + (f"allowed in B state '{s.new_state}'." if s.into_error is None else
                   f"allowed in B state '{s.new_state}' (it leads to the error state "
                   f"'{s.into_error}').")]

    def explain(self) -> str:
        q = self.current
        out: List[str] = []

        if self.status is Status.UNREACHABLE:
            out.append(f"UNREACHABLE: state '{q}' cannot be reached from the "
                       f"start state of A.")
            out.append("  It has no history, so there is nothing to replay in B; "
                       "the question is meaningless for this state.")

        elif self.status is Status.UNIQUE:
            p = self.answer
            out.append(f"UNIQUE: state '{q}' of A corresponds to state '{p}' of B.")
            if self.stuck is None:
                out.append(f"  Every history of '{q}' in A (every event sequence "
                           f"from A's start to '{q}'; possibly infinitely many)")
                out.append(f"  is replayable in B and ends in '{p}'.")
            else:
                out.append(f"  Every history of '{q}' that B can replay ends in '{p}'.")
            out.append("  Shortest history as evidence:")
            out += self._evidence(self.candidates[p])      # type: ignore[index]
            if self.stuck is not None:
                out.append("  WARNING (lenient mode): some histories of "
                           f"'{q}' cannot be replayed by B at all:")
                out += self._stuck_lines()
                out.append("  If the instance really followed such a history, "
                           "it is not valid in B.")

        elif self.status is Status.AMBIGUOUS:
            out.append(f"AMBIGUOUS: no single state of B corresponds to '{q}'.")
            out.append(f"  A merged several different histories into '{q}', but B "
                       f"keeps them apart.")
            out.append("  They end in different B states:")
            for cand, word in self.candidates.items():
                out.append(f"  - B state '{cand}', reached e.g. by:")
                out += self._evidence(word, indent="      ")
            out += self._future_difference()
            if self.stuck is not None:
                out.append("  Moreover, some histories cannot be replayed by B at all:")
                out += self._stuck_lines()
            out.append(f"  Any single choice is a guess: it is wrong for at least one "
                       f"possible history.")
            out.append("  The information needed to choose was lost in A; use "
                       "external knowledge (logs, policy, user input).")

        else:  # STUCK
            out.append(f"STUCK: B cannot replay some histories of '{q}'.")
            out += self._stuck_lines(indent="  ")
            if self.candidates:
                names = ", ".join(f"'{c}'" for c in self.candidates)
                out.append(f"  Other histories of '{q}' do end in B state(s) {names}.")
                out.append("  (Use lenient=True / --lenient to accept that answer "
                           "and only get a warning.)")
            else:
                out.append(f"  In fact no history of '{q}' can be replayed in B.")

        out += [f"  {line}" for line in self.notes]
        out.append(f"  [product states explored: {self.explored_pairs}]")
        return "\n".join(out)

    def _future_difference(self) -> List[str]:
        """How the candidate B states differ in their FUTURE behaviour."""
        cands = list(self.candidates)
        lines: List[str] = []
        any_diff = False
        shown = 0
        for p1, p2 in itertools.combinations(cands, 2):
            word = distinguishing_word(self.new, p1, p2, self.error_states)
            if word is None:
                continue
            any_diff = True
            if shown < 6:
                allowed_in_1 = self.new.run(word, p1, self.error_states) is not None
                yes, no = (p1, p2) if allowed_in_1 else (p2, p1)
                lines.append(f"    '{fmt_word(word)}' is possible from '{yes}' "
                             f"but not from '{no}'")
                shown += 1
        if any_diff:
            return ["  How these B states differ in the future:"] + lines
        if not self.error_states and self.new.is_complete():
            # In a complete automaton every state allows every event, so
            # "allowed events" says nothing about how the states differ.
            return ["  Note: B is completely defined (every state allows every event), so the "
                    "FUTURE of these",
                    "  states cannot be compared by allowed events. Declare trap states with "
                    "error_states to",
                    "  make such a comparison possible."]
        return ["  Note: these B states allow exactly the same event sequences, so "
                "for the FUTURE any",
                "  of them behaves identically; they still differ in the PAST "
                "(any choice is a guess about it)."]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def _stuck_witness(new: DFA, history: Word,
                   error_states: FrozenSet[State] = frozenset()) -> StuckWitness:
    state = new.start
    for i, sym in enumerate(history):
        nxt = new.step(state, sym)
        if nxt is None:
            return StuckWitness(history, history[:i], sym, state)
        if nxt in error_states:
            return StuckWitness(history, history[:i], sym, state, into_error=nxt)
        state = nxt
    raise AssertionError("history is replayable, so it cannot be a stuck witness")


def _check_error_states(new: DFA, error_states: Iterable[State]) -> FrozenSet[State]:
    errors = frozenset(error_states)
    unknown = errors - new.states
    if unknown:
        raise ValueError(f"error states not in the new automaton: {sorted(map(str, unknown))}")
    if new.start in errors:
        raise ValueError("the start state of the new automaton cannot be an error state")
    return errors


def _build_result(old: DFA, new: DFA, q: State, parent: Parent,
                  pairs: List[Pair], lenient: bool,
                  errors: FrozenSet[State] = frozenset()) -> MappingResult:
    explored = len(parent)
    if not pairs:
        return MappingResult(Status.UNREACHABLE, q, None, {}, None,
                             explored, old, new, lenient, errors)
    candidates: Dict[State, Word] = {}
    stuck: Optional[StuckWitness] = None
    for pair in pairs:
        word = _word_to(parent, pair)
        if pair[1] is None:
            stuck = _stuck_witness(new, word, errors)
        else:
            candidates[pair[1]] = word

    answer: Optional[State] = None
    if len(candidates) >= 2:
        status = Status.AMBIGUOUS
    elif stuck is not None and not (lenient and len(candidates) == 1):
        status = Status.STUCK
    else:
        status = Status.UNIQUE
        answer = next(iter(candidates))
    return MappingResult(status, q, answer, candidates, stuck,
                         explored, old, new, lenient, errors)


def map_state(old: DFA, current: State, new: DFA, *, lenient: bool = False,
              error_states: Iterable[State] = ()) -> MappingResult:
    """Find the state of `new` that corresponds to `current` of `old` by history.

    lenient=False (default): any history of `current` that `new` cannot replay
        makes the result STUCK.
    lenient=True: if all *replayable* histories agree on one state p, return
        UNIQUE(p) (the unreplayable history is still reported in `.stuck`).
    error_states: states of `new` that mean "error / trap" (typical for a
        completely defined `new`).  A history that enters one of them counts
        as not replayable, exactly like a missing transition.
    """
    if current not in old.states:
        raise ValueError(f"state {current!r} does not exist in the old automaton")
    errors = _check_error_states(new, error_states)
    keep = old.can_reach(current)           # trim: only states on paths to q
    if old.start not in keep:
        return _build_result(old, new, current, {(old.start, new.start): None},
                             [], lenient, errors)
    parent = _explore(old, new, keep, errors)
    pairs = [pair for pair in parent if pair[0] == current]
    return _build_result(old, new, current, parent, pairs, lenient, errors)


def map_all(old: DFA, new: DFA, *, lenient: bool = False,
            error_states: Iterable[State] = ()) -> Dict[State, MappingResult]:
    """Same as map_state for every state of `old` in a single product BFS."""
    errors = _check_error_states(new, error_states)
    parent = _explore(old, new, None, errors)
    by_state: Dict[State, List[Pair]] = {}
    for pair in parent:
        by_state.setdefault(pair[0], []).append(pair)
    results: Dict[State, MappingResult] = {}
    for q, pairs in by_state.items():
        results[q] = _build_result(old, new, q, parent, pairs, lenient, errors)
    for q in sorted(old.states - set(by_state), key=str):
        results[q] = _build_result(old, new, q, parent, [], lenient, errors)
    return results


def format_table(results: Dict[State, MappingResult]) -> str:
    """Compact table: old state | status | corresponding new state(s)."""
    rows = [("A state", "status", "B state(s)")]
    for q, r in results.items():
        targets = ", ".join(str(c) for c in r.candidates) or "-"
        # Real candidates plus an unreplayable history: say so explicitly.
        note = "  [+ some histories not replayable by B]" if (r.stuck and r.candidates) else ""
        rows.append((str(q), r.status.value, targets + note))
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    lines = []
    for i, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row)).rstrip())
        if i == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Command line interface
# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Map the current state of an old DFA to a state of a new "
                    "DFA by history. Exit code 0 = UNIQUE answer, 1 = otherwise.")
    parser.add_argument("old", help="JSON file of the old automaton")
    parser.add_argument("new", help="JSON file of the new automaton")
    parser.add_argument("state", nargs="?", help="current state of the old automaton")
    parser.add_argument("--all", action="store_true",
                        help="print a table for every state of the old automaton")
    parser.add_argument("--lenient", action="store_true",
                        help="accept a unique answer even if B cannot replay "
                             "some other histories (a warning is printed)")
    parser.add_argument("--error-state", action="append", default=[], metavar="STATE",
                        help="state of the NEW automaton that means 'error/trap' "
                             "(repeatable); histories entering it count as rejected")
    args = parser.parse_args(argv)

    old = DFA.from_json_file(args.old)
    new = DFA.from_json_file(args.new)
    if args.all:
        results = map_all(old, new, lenient=args.lenient, error_states=args.error_state)
        print(format_table(results))
        return 0 if all(r.status is Status.UNIQUE for r in results.values()) else 1
    if args.state is None:
        parser.error("state is required unless --all is given")
    result = map_state(old, args.state, new, lenient=args.lenient,
                       error_states=args.error_state)
    print(result.explain())
    return 0 if result.status is Status.UNIQUE else 1


if __name__ == "__main__":
    sys.exit(main())
