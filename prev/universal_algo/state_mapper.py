#!/usr/bin/env python3
"""
state_mapper - find the state of a NEW DFA that corresponds, "by the past", to
the current state of an OLD DFA.  Partial and completely defined automata are
handled in the same way: a complete automaton is just a partial one in which
every transition happens to be defined.

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
  * q is a declared trap of A and trap_mode='forbid-both'
                                    -> TRAP        (not mapped by policy)

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

Trap states (trap_mode)
-----------------------
By default a trap (sink, error state) is an ordinary state: histories may
lead into it, and it can be the corresponding state p or the asked state q.
You may DECLARE traps (new_traps=... for B, old_traps=... for A) and choose
what the declaration means:

  trap_mode='ordinary'    (default) declarations change nothing in the logic
                          (they only produce hints and drawings);
  trap_mode='forbid-new'  a history that enters a declared trap of B counts
                          as NOT replayable (STUCK), like a missing transition;
  trap_mode='forbid-both' additionally: entering a declared trap of A is not
                          a valid history step (those transitions are ignored),
                          and if q itself is a declared trap of A the result is
                          TRAP (such a state is not mapped by history).

Events: plain names, '*' (any event) and '!a,!b' (any event except a, b)
------------------------------------------------------------------------
A transition may carry a wildcard instead of a name: 's -*-> t' fires on every
event, 's -!a,!b-> t' on every event except a and b.  An explicit transition
of the same state wins over a wildcard ("else" semantics).  A state may have
only one wildcard target.  Wildcards cover events that are not named anywhere
too: they are represented by the pseudo event '<other>'.  Declare
'alphabet=a,b,c' to close the universe (no '<other>').

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
from typing import Dict, FrozenSet, Hashable, Iterable, List, Optional, Tuple, Union

State = Hashable
Symbol = str
Word = Tuple[Symbol, ...]
Pair = Tuple[State, Optional[State]]      # (state of A, state of B or None)
Parent = Dict[Pair, Optional[Tuple[Pair, Symbol]]]

OTHER = "<other>"      # pseudo event: "any event that no transition names"


# --------------------------------------------------------------------------
# Event specifications: 'a', '*', '!a,!b'
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Except:
    """'Every event except these'.  Except() (nothing excluded) means any event."""
    names: FrozenSet[Symbol] = frozenset()

    def __str__(self) -> str:
        return ",".join("!" + n for n in sorted(self.names)) if self.names else "*"


ANY = Except()


def parse_events(text: str) -> Union[List[Symbol], Except]:
    """'a,b' -> ['a', 'b'];  '*' -> ANY;  '!a,!b' -> Except({'a', 'b'})."""
    tokens = [t.strip() for t in text.split(",")]
    if not all(tokens):
        raise ValueError(f"empty event name in {text!r}")
    if "*" in tokens:
        if tokens != ["*"]:
            raise ValueError(f"'*' cannot be combined with other events: {text!r}")
        return ANY
    negated = [t for t in tokens if t.startswith("!")]
    if negated:
        if len(negated) != len(tokens):
            raise ValueError(f"cannot mix 'x' and '!x' in one transition: {text!r}")
        names = frozenset(t[1:] for t in negated)
        if "" in names or "*" in names:
            raise ValueError(f"bad negation in {text!r}")
        return Except(names)
    return tokens


# --------------------------------------------------------------------------
# DFA (partial, or complete as a special case)
# --------------------------------------------------------------------------
class DFA:
    """Deterministic finite automaton, possibly partial (immutable after construction).

    `transitions` are triples (source, event, target) where `event` is a plain
    event name or an `Except` object (wildcard).  `alphabet`, if given,
    declares the closed set of all events; without it the universe is open and
    wildcards also cover the pseudo event OTHER.
    """

    _EDGE_RE = re.compile(r"^(\S+)\s+-(\S+?)->\s+(\S+)$")

    def __init__(self, start: State,
                 transitions: Iterable[Tuple[State, Union[Symbol, Except], State]],
                 states: Iterable[State] = (),
                 alphabet: Optional[Iterable[Symbol]] = None):
        self.start = start
        self._raw: List[Tuple[State, Union[Symbol, Except], State]] = []
        explicit: Dict[State, Dict[Symbol, State]] = {start: {}}
        wild: Dict[State, Tuple[FrozenSet[Symbol], State]] = {}
        for s in states:
            explicit.setdefault(s, {})
        for src, event, dst in transitions:
            self._raw.append((src, event, dst))
            row = explicit.setdefault(src, {})
            explicit.setdefault(dst, {})
            if isinstance(event, Except):
                if src in wild:
                    excluded, other_dst = wild[src]
                    if other_dst != dst:
                        raise ValueError(
                            f"not deterministic: state {src!r} has two wildcard transitions "
                            f"to different targets ({other_dst!r} and {dst!r})")
                    wild[src] = (excluded & event.names, dst)   # 'all but X' or 'all but Y'
                else:
                    wild[src] = (event.names, dst)
                continue
            if event == "*" or event.startswith("!") or "," in event:
                raise ValueError(f"bad event name {event!r}: use Except(...) or "
                                 f"DFA.from_text for wildcards")
            if event in row and row[event] != dst:
                raise ValueError(
                    f"not deterministic: state {src!r} has two transitions "
                    f"on {event!r}: -> {row[event]!r} and -> {dst!r}")
            row[event] = dst

        self._explicit = explicit
        self._wild = wild
        self._all_states = frozenset(explicit)
        self._declared = None if alphabet is None else frozenset(alphabet)
        mentioned = {e for row in explicit.values() for e in row}
        for excluded, _ in wild.values():
            mentioned |= excluded
        self._mentioned = frozenset(mentioned)
        if self._declared is not None:
            outside = self._mentioned - self._declared
            if outside:
                raise ValueError(f"events not in the declared alphabet: {sorted(outside)}")
            sigma = self._declared
        elif wild:
            sigma = self._mentioned | {OTHER}
        else:
            sigma = self._mentioned
        self._sigma = frozenset(sigma)

        delta = {s: dict(row) for s, row in explicit.items()}
        for s, (excluded, dst) in wild.items():          # explicit beats wildcard
            for e in self._sigma:
                if e not in excluded and e not in delta[s]:
                    delta[s][e] = dst
        self._delta: Dict[State, Dict[Symbol, State]] = delta
        # Cache sorted edge lists: gives deterministic BFS order and output.
        self._edges: Dict[State, Tuple[Tuple[Symbol, State], ...]] = {
            s: tuple(sorted(row.items(), key=lambda kv: str(kv[0])))
            for s, row in delta.items()
        }

    # ---- construction helpers ------------------------------------------
    @classmethod
    def from_text(cls, text: str) -> "DFA":
        """Parse 'start=s; s -a-> x; x -b,c-> q; q -*-> s; s -!a,!b-> x'.

        Items are split by ';' or newline.  An item is `start=NAME`,
        `alphabet=a,b,c` (closes the universe of events) or a transition
        `SOURCE -EVENTS-> TARGET`, where EVENTS is a comma list of names,
        `*` (any event) or `!a,!b` (any event except a and b).  If `start=` is
        omitted, the source of the first transition is the start state.
        State and event names must not contain whitespace or commas.
        """
        start: Optional[str] = None
        alphabet: Optional[List[str]] = None
        edges: List[Tuple[str, Union[str, Except], str]] = []
        for item in re.split(r"[;\n]", text):
            item = item.strip()
            if not item or item.startswith("#"):
                continue
            if item.startswith("start="):
                start = item[len("start="):].strip()
                continue
            if item.startswith("alphabet="):
                alphabet = [e.strip() for e in item[len("alphabet="):].split(",") if e.strip()]
                continue
            match = cls._EDGE_RE.match(item)
            if not match:
                raise ValueError(f"cannot parse transition: {item!r}")
            src, events, dst = match.groups()
            spec = parse_events(events)
            if isinstance(spec, Except):
                edges.append((src, spec, dst))
            else:
                edges.extend((src, e, dst) for e in spec)
        if start is None:
            if not edges:
                raise ValueError("start state is required")
            start = edges[0][0]
        return cls(start, edges, alphabet=alphabet)

    @classmethod
    def from_json_file(cls, path: str) -> "DFA":
        """Load {"start": "s", "transitions": [["s","a","x"], ["x","!a","s"], ...]}.
        Optional keys: "states" (states without transitions), "alphabet"."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        edges: List[Tuple[str, Union[str, Except], str]] = []
        for src, events, dst in data["transitions"]:
            spec = parse_events(events)
            if isinstance(spec, Except):
                edges.append((src, spec, dst))
            else:
                edges.extend((src, e, dst) for e in spec)
        return cls(data["start"], edges, data.get("states", ()), data.get("alphabet"))

    # ---- basic queries ---------------------------------------------------
    @property
    def states(self) -> FrozenSet[State]:
        return frozenset(self._delta)

    @property
    def alphabet(self) -> FrozenSet[Symbol]:
        """Events the automaton works with (for wildcards: including OTHER
        unless the alphabet was declared)."""
        return self._sigma

    @property
    def mentioned(self) -> FrozenSet[Symbol]:
        """Event names that occur in some transition (as a name or an exclusion)."""
        return self._mentioned

    @property
    def declared_alphabet(self) -> Optional[FrozenSet[Symbol]]:
        return self._declared

    @property
    def is_symbolic(self) -> bool:
        """True if the automaton uses wildcard transitions ('*' or '!a')."""
        return bool(self._wild)

    @property
    def num_transitions(self) -> int:
        return sum(len(row) for row in self._delta.values())

    def step(self, state: State, symbol: Symbol) -> Optional[State]:
        """Next state, or None if the transition is not defined."""
        row = self._delta.get(state)
        if row is None:
            return None
        nxt = row.get(symbol)
        if nxt is None and self._declared is None and symbol not in self._sigma:
            wildcard = self._wild.get(state)          # an event nobody named: like OTHER
            if wildcard is not None and symbol not in wildcard[0]:
                nxt = wildcard[1]
        return nxt

    def edges_from(self, state: State) -> Tuple[Tuple[Symbol, State], ...]:
        return self._edges.get(state, ())

    def run(self, word: Iterable[Symbol], state: Optional[State] = None,
            forbidden: FrozenSet[State] = frozenset()) -> Optional[State]:
        """State reached by `word` (from the start state by default), or
        None if some transition on the way is undefined or enters one of
        the `forbidden` states."""
        current = self.start if state is None else state
        for sym in word:
            current = self.step(current, sym)
            if current is None or current in forbidden:
                return None
        return current

    def can_reach(self, target: State, avoid: FrozenSet[State] = frozenset()) -> set:
        """All states from which `target` is reachable (including itself),
        never passing through the states in `avoid`."""
        reverse: Dict[State, List[State]] = {}
        for src, row in self._delta.items():
            if src in avoid:
                continue
            for dst in row.values():
                if dst not in avoid:
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
        To treat the sink as "B rejects this" when mapping into the copy,
        declare it: new_traps={sink}, trap_mode='forbid-new'."""
        symbols = sorted(self.alphabet if alphabet is None else alphabet, key=str)
        edges = [(s, sym, dst) for s, row in self._delta.items() for sym, dst in row.items()]
        missing = [(s, sym, sink) for s, row in self._delta.items()
                   for sym in symbols if sym not in row]
        if missing:
            if sink in self._delta:
                raise ValueError(f"sink name {sink!r} is already a state")
            edges += missing + [(sink, sym, sink) for sym in symbols]
        return DFA(self.start, edges, self._delta.keys())

    def expanded(self, alphabet: Iterable[Symbol]) -> "DFA":
        """Copy in which wildcards are resolved against the closed set
        `alphabet` (automata without wildcards are returned unchanged)."""
        if not self._wild:
            return self
        return DFA(self.start, self._raw, self._all_states, alphabet=alphabet)

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
        """One line per (source, target); parallel events are joined as 'a,b',
        wildcard transitions are shown as written ('*', '!a,!b')."""
        lines = []
        for src in self._bfs_order():
            grouped: Dict[State, List[str]] = {}
            for sym, dst in sorted(self._explicit[src].items(), key=lambda kv: str(kv[0])):
                grouped.setdefault(dst, []).append(sym)
            wildcard = self._wild.get(src)
            if wildcard is not None:
                excluded, dst = wildcard
                label = ",".join("!" + n for n in sorted(excluded)) if excluded else "*"
                grouped.setdefault(dst, []).append(label)
            for dst, labels in grouped.items():
                lines.append(f"{indent}{src} -{','.join(labels)}-> {dst}")
        return "\n".join(lines) if lines else f"{indent}(no transitions)"


# --------------------------------------------------------------------------
# Words and traces (for readable output)
# --------------------------------------------------------------------------
def fmt_word(word: Word) -> str:
    return " ".join(str(s) for s in word) if word else "<empty>"


def _trace(dfa: DFA, word: Word, forbidden: FrozenSet[State] = frozenset()) -> str:
    """'s -a-> x -b-> q'; shows '<undefined>' where the automaton gets stuck and
    marks the first forbidden trap that is entered."""
    state = dfa.start
    parts = [str(state)]
    for sym in word:
        nxt = dfa.step(state, sym)
        if nxt is None:
            parts += [f"-{sym}->", "<undefined>"]
            break
        if nxt in forbidden:
            parts += [f"-{sym}->", f"{nxt} (trap)"]
            break
        parts += [f"-{sym}->", str(nxt)]
        state = nxt
    return " ".join(parts)


# --------------------------------------------------------------------------
# Product exploration
# --------------------------------------------------------------------------
def _explore(old: DFA, new: DFA, keep: Optional[set] = None,
             forbidden_new: FrozenSet[State] = frozenset(),
             forbidden_old: FrozenSet[State] = frozenset()) -> Parent:
    """BFS over the product old x new (new is completed with UNDEFINED=None).

    Entering a state of `forbidden_new` counts as "B has no transition": the
    second component becomes UNDEFINED (None) and stays there.  Transitions of
    `old` into `forbidden_old` states are ignored.
    Returns a parent map: pair -> (previous pair, symbol) or None for the
    root.  If `keep` is given, only old-states in `keep` are visited.
    """
    root: Pair = (old.start, new.start)
    parent: Parent = {root: None}
    queue = deque([root])
    while queue:
        a, b = queue.popleft()
        for sym, a2 in old.edges_from(a):
            if a2 in forbidden_old:
                continue
            if keep is not None and a2 not in keep:
                continue
            b2 = None if b is None else new.step(b, sym)
            if b2 in forbidden_new:
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
                        forbidden: FrozenSet[State] = frozenset()) -> Optional[Word]:
    """Shortest event sequence allowed from exactly one of p1, p2 (or None
    if both states allow exactly the same event sequences).  A transition
    into one of the `forbidden` states counts as "not allowed"."""
    root: Pair = (p1, p2)
    parent: Parent = {root: None}
    queue = deque([root])
    while queue:
        x, y = queue.popleft()
        symbols = sorted({s for s, _ in dfa.edges_from(x)} |
                         {s for s, _ in dfa.edges_from(y)}, key=str)
        for sym in symbols:
            x2, y2 = dfa.step(x, sym), dfa.step(y, sym)
            if x2 in forbidden:
                x2 = None
            if y2 in forbidden:
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
    TRAP = "TRAP"                # q is a declared trap of A (trap_mode='forbid-both')


class TrapMode(Enum):
    """What a declaration of trap states means (see the module docstring)."""
    ORDINARY = "ordinary"          # traps are ordinary states (default)
    FORBID_NEW = "forbid-new"      # entering a declared trap of B = B rejects the event
    FORBID_BOTH = "forbid-both"    # also: traps of A are not entered / not mapped


@dataclass
class StuckWitness:
    """A history of q in A that B cannot replay."""
    history: Word       # shortest such history
    replayed: Word      # the part of it that B can replay
    event: Symbol       # first event that B rejects
    new_state: State    # B state in which `event` is not allowed
    into_trap: Optional[State] = None    # declared trap the event leads to
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
    new_traps: FrozenSet[State] = frozenset()      # declared traps of B
    old_traps: FrozenSet[State] = frozenset()      # declared traps of A
    trap_mode: TrapMode = TrapMode.ORDINARY

    @property
    def forbidden_new(self) -> FrozenSet[State]:
        """Traps of B that count as 'B rejects the event' in the chosen mode."""
        return self.new_traps if self.trap_mode is not TrapMode.ORDINARY else frozenset()

    @property
    def forbidden_old(self) -> FrozenSet[State]:
        """Traps of A that are not entered / not mapped in the chosen mode."""
        return self.old_traps if self.trap_mode is TrapMode.FORBID_BOTH else frozenset()

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
        from prev.universal_algo.visualize import to_dot
        return to_dot(self, title)

    def save_png(self, path: str, title: str = "", dpi: int = 130) -> None:
        """Render the figure to a PNG file (needs the Graphviz `dot` program)."""
        from prev.universal_algo.visualize import render_png
        render_png(self, path, title, dpi)

    # ---- human-readable explanation --------------------------------------
    def _evidence(self, word: Word, indent: str = "    ") -> List[str]:
        return [f"{indent}history '{fmt_word(word)}'",
                f"{indent}  in A: {_trace(self.old, word, self.forbidden_old)}",
                f"{indent}  in B: {_trace(self.new, word, self.forbidden_new)}"]

    def _hints(self) -> List[Tuple[str, List[str]]]:
        """Hints about answers that may be misleading (they are not errors):
        a list of (one-line summary, detailed lines)."""
        hints: List[Tuple[str, List[str]]] = []
        q = self.current
        mode = self.trap_mode.value
        if self.trap_mode is TrapMode.ORDINARY:
            for cand in self.candidates:
                if cand in self.new_traps:
                    hints.append((
                        f"NOTE: '{cand}' is a declared trap of B; trap_mode 'ordinary' allows "
                        f"mapping into it.",
                        [f"NOTE: B state '{cand}' is a declared trap, but trap_mode is "
                         f"'ordinary', so mapping into it is allowed.",
                         "      Use trap_mode='forbid-new' to treat histories that end "
                         "there as rejected by B."]))
            if q in self.old_traps:
                hints.append((
                    f"NOTE: '{q}' is a declared trap of A; trap_mode 'ordinary' maps it like "
                    f"any state.",
                    [f"NOTE: A state '{q}' is a declared trap; in trap_mode 'ordinary' it is "
                     f"mapped like any state.",
                     "      Use trap_mode='forbid-both' to refuse mapping a trap of A."]))
        elif self.trap_mode is TrapMode.FORBID_NEW and q in self.old_traps:
            hints.append((
                f"NOTE: '{q}' is declared as a trap of A, but mode 'forbid-new' ignores traps of A.",
                [f"NOTE: A state '{q}' is declared as a trap, but trap_mode='{mode}' ignores "
                 f"traps of A.",
                 "      Use trap_mode='forbid-both' to refuse mapping a trap of A."]))
        # Heuristic: an UNdeclared absorbing B state chosen for a state that can move on.
        if not self.old.is_absorbing(q) and q not in self.old_traps:
            for cand in self.candidates:
                if cand not in self.new_traps and self.new.is_absorbing(cand):
                    hints.append((
                        f"NOTE: '{cand}' looks like an undeclared trap of B (absorbing). If it is "
                        f"one, declare it (new_traps + trap_mode='forbid-new').",
                        [f"NOTE: B state '{cand}' is absorbing (every transition loops back), "
                         f"but A state '{q}'",
                         "      can still move on. If it is a trap of B, declare it "
                         "(new_traps and",
                         f"      trap_mode='forbid-new', e.g. new_traps={{'{cand}'}}): "
                         "histories that end there are then rejected by B."]))
        return hints

    @property
    def notes(self) -> List[str]:
        """Detailed hint lines (see _hints); empty if there is nothing to point out."""
        return [line for _, lines in self._hints() for line in lines]

    @property
    def note_summaries(self) -> List[str]:
        """One-line versions of the hints (used in drawings)."""
        return [short for short, _ in self._hints()]

    def _stuck_lines(self, indent: str = "    ") -> List[str]:
        s = self.stuck
        assert s is not None
        where = (f"after '{fmt_word(s.replayed)}'" if s.replayed
                 else "at the very first event")
        return [f"{indent}history '{fmt_word(s.history)}' is possible in A:",
                f"{indent}  in A: {_trace(self.old, s.history, self.forbidden_old)}",
                f"{indent}  in B: {_trace(self.new, s.history, self.forbidden_new)}",
                f"{indent}B rejects it {where}: event '{s.event}' is not "
                + (f"allowed in B state '{s.new_state}'." if s.into_trap is None else
                   f"allowed in B state '{s.new_state}' (it leads to the trap state "
                   f"'{s.into_trap}').")]

    def explain(self) -> str:
        q = self.current
        out: List[str] = []

        if self.status is Status.TRAP:
            out.append(f"TRAP: state '{q}' is a declared trap of A "
                       f"(trap_mode='{self.trap_mode.value}').")
            out.append("  In this mode trap states of A are not mapped by history: they mean "
                       "'the instance is already in error',")
            out.append("  and their \"history\" is just the set of invalid event sequences. "
                       "Handle such instances separately")
            out.append("  (for example: trap of A -> trap of B), or use trap_mode='ordinary' "
                       "to map it like any state.")

        elif self.status is Status.UNREACHABLE:
            out.append(f"UNREACHABLE: state '{q}' cannot be reached from the "
                       f"start state of A.")
            out.append("  It has no history, so there is nothing to replay in B; "
                       "the question is meaningless for this state.")
            if self.forbidden_old:
                names = ", ".join(f"'{t}'" for t in sorted(self.forbidden_old, key=str))
                out.append(f"  (In this trap mode transitions into the declared traps of A "
                           f"({names}) are not followed.)")

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
        if self.trap_mode is not TrapMode.ORDINARY or self.new_traps or self.old_traps:
            decl = []
            if self.new_traps:
                decl.append("traps of B: " + ", ".join(sorted(map(str, self.new_traps))))
            if self.old_traps:
                decl.append("traps of A: " + ", ".join(sorted(map(str, self.old_traps))))
            out.append(f"  [trap_mode: {self.trap_mode.value}"
                       + ("; " + "; ".join(decl) if decl else "") + "]")
        out.append(f"  [product states explored: {self.explored_pairs}]")
        return "\n".join(out)

    def _future_difference(self) -> List[str]:
        """How the candidate B states differ in their FUTURE behaviour."""
        cands = list(self.candidates)
        lines: List[str] = []
        any_diff = False
        shown = 0
        for p1, p2 in itertools.combinations(cands, 2):
            word = distinguishing_word(self.new, p1, p2, self.forbidden_new)
            if word is None:
                continue
            any_diff = True
            if shown < 6:
                allowed_in_1 = self.new.run(word, p1, self.forbidden_new) is not None
                yes, no = (p1, p2) if allowed_in_1 else (p2, p1)
                lines.append(f"    '{fmt_word(word)}' is possible from '{yes}' "
                             f"but not from '{no}'")
                shown += 1
        if any_diff:
            return ["  How these B states differ in the future:"] + lines
        if not self.forbidden_new and self.new.is_complete():
            # In a complete automaton every state allows every event, so
            # "allowed events" says nothing about how the states differ.
            return ["  Note: B is completely defined (every state allows every event), so the "
                    "FUTURE of these",
                    "  states cannot be compared by allowed events. Declare the trap states of B "
                    "and use",
                    "  trap_mode='forbid-new' to make such a comparison possible."]
        return ["  Note: these B states allow exactly the same event sequences, so "
                "for the FUTURE any",
                "  of them behaves identically; they still differ in the PAST "
                "(any choice is a guess about it)."]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _Traps:
    new_traps: FrozenSet[State]
    old_traps: FrozenSet[State]
    mode: TrapMode

    @property
    def forbidden_new(self) -> FrozenSet[State]:
        return self.new_traps if self.mode is not TrapMode.ORDINARY else frozenset()

    @property
    def forbidden_old(self) -> FrozenSet[State]:
        return self.old_traps if self.mode is TrapMode.FORBID_BOTH else frozenset()


def _unify(old: DFA, new: DFA) -> Tuple[DFA, DFA]:
    """Resolve wildcards of both automata against ONE common set of events:
    everything either automaton names, plus the pseudo event OTHER (events
    nobody names) unless an alphabet was declared."""
    if not (old.is_symbolic or new.is_symbolic):
        return old, new
    declared = [d for d in (old.declared_alphabet, new.declared_alphabet) if d is not None]
    mentioned = old.mentioned | new.mentioned
    if declared:
        sigma = frozenset().union(*declared) | mentioned
    else:
        sigma = mentioned | {OTHER}
    return old.expanded(sigma), new.expanded(sigma)


def _prepare(old: DFA, new: DFA, new_traps: Iterable[State], old_traps: Iterable[State],
             trap_mode: Union[TrapMode, str]) -> Tuple[DFA, DFA, _Traps]:
    try:
        mode = trap_mode if isinstance(trap_mode, TrapMode) else TrapMode(trap_mode)
    except ValueError:
        raise ValueError(f"unknown trap_mode {trap_mode!r}; expected one of "
                         f"{[m.value for m in TrapMode]}") from None
    old, new = _unify(old, new)
    nt, ot = frozenset(new_traps), frozenset(old_traps)
    if nt - new.states:
        raise ValueError(f"new_traps not in the new automaton: {sorted(map(str, nt - new.states))}")
    if ot - old.states:
        raise ValueError(f"old_traps not in the old automaton: {sorted(map(str, ot - old.states))}")
    if new.start in nt:
        raise ValueError("the start state of the new automaton cannot be a trap")
    if old.start in ot:
        raise ValueError("the start state of the old automaton cannot be a trap")
    return old, new, _Traps(nt, ot, mode)


def _stuck_witness(new: DFA, history: Word,
                   forbidden: FrozenSet[State] = frozenset()) -> StuckWitness:
    state = new.start
    for i, sym in enumerate(history):
        nxt = new.step(state, sym)
        if nxt is None:
            return StuckWitness(history, history[:i], sym, state)
        if nxt in forbidden:
            return StuckWitness(history, history[:i], sym, state, into_trap=nxt)
        state = nxt
    raise AssertionError("history is replayable, so it cannot be a stuck witness")


def _special(status: Status, old: DFA, new: DFA, q: State, lenient: bool,
             traps: _Traps, explored: int = 0) -> MappingResult:
    return MappingResult(status, q, None, {}, None, explored, old, new, lenient,
                         traps.new_traps, traps.old_traps, traps.mode)


def _build_result(old: DFA, new: DFA, q: State, parent: Parent,
                  pairs: List[Pair], lenient: bool, traps: _Traps) -> MappingResult:
    explored = len(parent)
    if not pairs:
        return _special(Status.UNREACHABLE, old, new, q, lenient, traps, explored)
    candidates: Dict[State, Word] = {}
    stuck: Optional[StuckWitness] = None
    for pair in pairs:
        word = _word_to(parent, pair)
        if pair[1] is None:
            stuck = _stuck_witness(new, word, traps.forbidden_new)
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
    return MappingResult(status, q, answer, candidates, stuck, explored, old, new, lenient,
                         traps.new_traps, traps.old_traps, traps.mode)


def map_state(old: DFA, current: State, new: DFA, *, lenient: bool = False,
              new_traps: Iterable[State] = (), old_traps: Iterable[State] = (),
              trap_mode: Union[TrapMode, str] = TrapMode.ORDINARY) -> MappingResult:
    """Find the state of `new` that corresponds to `current` of `old` by history.

    lenient=False (default): any history of `current` that `new` cannot replay
        makes the result STUCK.
    lenient=True: if all *replayable* histories agree on one state p, return
        UNIQUE(p) (the unreplayable history is still reported in `.stuck`).
    new_traps / old_traps: states of `new` / `old` that you declare as traps
        (sinks, error states).  What the declaration means depends on
        trap_mode:
          'ordinary'     (default) nothing changes: traps are ordinary states;
          'forbid-new'   entering a declared trap of `new` counts as "B
                         rejects this event" (like a missing transition);
          'forbid-both'  additionally, transitions of `old` into its declared
                         traps are ignored, and a declared trap of `old` asked
                         about as `current` gives Status.TRAP.
    Wildcard transitions ('*', '!a') of either automaton are resolved against
    the common set of events (see the module docstring).
    """
    old, new, traps = _prepare(old, new, new_traps, old_traps, trap_mode)
    if current not in old.states:
        raise ValueError(f"state {current!r} does not exist in the old automaton")
    if current in traps.forbidden_old:
        return _special(Status.TRAP, old, new, current, lenient, traps)
    keep = old.can_reach(current, avoid=traps.forbidden_old)   # trim: states on paths to q
    if old.start not in keep:
        return _special(Status.UNREACHABLE, old, new, current, lenient, traps, explored=1)
    parent = _explore(old, new, keep, traps.forbidden_new, traps.forbidden_old)
    pairs = [pair for pair in parent if pair[0] == current]
    return _build_result(old, new, current, parent, pairs, lenient, traps)


def map_all(old: DFA, new: DFA, *, lenient: bool = False,
            new_traps: Iterable[State] = (), old_traps: Iterable[State] = (),
            trap_mode: Union[TrapMode, str] = TrapMode.ORDINARY) -> Dict[State, MappingResult]:
    """Same as map_state for every state of `old` in a single product BFS."""
    old, new, traps = _prepare(old, new, new_traps, old_traps, trap_mode)
    parent = _explore(old, new, None, traps.forbidden_new, traps.forbidden_old)
    by_state: Dict[State, List[Pair]] = {}
    for pair in parent:
        by_state.setdefault(pair[0], []).append(pair)
    results: Dict[State, MappingResult] = {}
    for q, pairs in by_state.items():
        results[q] = _build_result(old, new, q, parent, pairs, lenient, traps)
    for q in sorted(old.states - set(by_state), key=str):
        if q in traps.forbidden_old:
            results[q] = _special(Status.TRAP, old, new, q, lenient, traps)
        else:
            results[q] = _build_result(old, new, q, parent, [], lenient, traps)
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
    parser.add_argument("--new-trap", action="append", default=[], metavar="STATE",
                        help="declare a trap (sink/error) state of the NEW automaton (repeatable)")
    parser.add_argument("--old-trap", action="append", default=[], metavar="STATE",
                        help="declare a trap (sink/error) state of the OLD automaton (repeatable)")
    parser.add_argument("--trap-mode", choices=[m.value for m in TrapMode], default="ordinary",
                        help="ordinary: traps are ordinary states (default); "
                             "forbid-new: entering a declared trap of B counts as rejected; "
                             "forbid-both: also ignore/refuse declared traps of A")
    args = parser.parse_args(argv)

    old = DFA.from_json_file(args.old)
    new = DFA.from_json_file(args.new)
    kwargs = dict(lenient=args.lenient, new_traps=args.new_trap, old_traps=args.old_trap,
                  trap_mode=args.trap_mode)
    if args.all:
        results = map_all(old, new, **kwargs)
        print(format_table(results))
        return 0 if all(r.status is Status.UNIQUE for r in results.values()) else 1
    if args.state is None:
        parser.error("state is required unless --all is given")
    result = map_state(old, args.state, new, **kwargs)
    print(result.explain())
    return 0 if result.status is Status.UNIQUE else 1


if __name__ == "__main__":
    sys.exit(main())
