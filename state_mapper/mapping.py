"""Core algorithm: which state p of B corresponds to the current state q of A?

Definitions (see the formal text):
  H(q)      = { w in L(A) : delta_A*(a0, w) = q }                  (histories)
  Hsimple(q)= { w in H(q) : the run of A on w visits no state twice }
  p ~ q     <=>  H(q) != {}  and  every w in H(q) is in L(B) and ends B in p.
  strong uses H(q); weak uses Hsimple(q).

Relation between the definitions (the Proposition "strong implies weak" of the formal text)
  Hsimple(q) is a subset of H(q), hence  O_weak(q) <= O_strong(q)  where O(q) is the set of
  B-states (or "stuck") that histories of q lead to.  p ~ q means O(q) = {p} (and p accepting),
  so a state that is equivalent by the strong definition is always equivalent by the weak one:
      p ~strong q  ==>  p ~weak q        (never the other way round)
  The weak definition looks at fewer histories, therefore it allows MORE corresponding states:
  e.g. O_strong = {s2, e} (AMBIGUOUS) but O_weak = {s2} (UNIQUE s2).  compare_definitions()
  checks these facts for a pair of results.

How it is computed
  strong : breadth-first search in the product automaton A x B (polynomial).
  weak   : hybrid.  (1) the strong analysis gives every B-state that some history can reach;
           simple histories are histories, so O_weak <= O_strong: strong supplies an UPPER bound
           for the candidates, which weak then filters (it never has a candidate that strong lacks).
           (2) a candidate is confirmed at once if its shortest history is already simple;
           otherwise (3) an exact depth-first search looks for a simple history ending there,
           pruned with product distances.  Finding simple paths is NP-hard in general, so step (3)
           is exponential only in the worst case.

Policies for a letter without transition:
  strict  : the automaton gets STUCK (delta* is undefined)
  lenient : the letter is skipped, the state does not change
            (i.e. delta is replaced by its total extension with self-loops).

Verdicts: UNIQUE, AMBIGUOUS, STUCK, UNREACHABLE and - only when the files declare
accepting states - NO_MATCH (the definition demands w in L(A) and w in L(B)).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

STRONG, WEAK = "strong", "weak"
STRICT, LENIENT = "strict", "lenient"

UNIQUE, AMBIGUOUS, STUCK, UNREACHABLE, NO_MATCH = (
    "UNIQUE", "AMBIGUOUS", "STUCK", "UNREACHABLE", "NO_MATCH")

BOT = None                      # "B is stuck" (delta_B* undefined)
ENUM_BUDGET = 20_000            # DFS nodes spent on listing ALL simple histories (for explain / pictures)
MAX_SEARCH_NODES = 3_000_000    # safety cap for the exact search of one simple history


class TooManyHistories(RuntimeError):
    pass


class _Budget(Exception):
    pass


# ----------------------------------------------------------------- data classes
@dataclass
class Trace:
    """Run of an automaton on a word. steps = [(src, letter, dst, skipped)]."""
    start: str
    steps: list
    stuck: Optional[tuple] = None        # (letter_index, state, letter) if undefined

    @property
    def end(self):
        if self.stuck is not None:
            return None
        return self.steps[-1][2] if self.steps else self.start


@dataclass
class Witness:
    word: tuple
    a_trace: Trace
    b_trace: Optional[Trace]
    b_state: Optional[str]               # None => B is stuck on this word


@dataclass
class Live:
    """Parts of the automata lying on some history of q (None = everything)."""
    a_states: Optional[set] = None
    a_edges: Optional[set] = None        # (src, letter, dst)
    b_states: Optional[set] = None
    b_edges: Optional[set] = None


@dataclass
class Result:
    definition: str
    policy: str
    q: str
    verdict: str
    p: Optional[str] = None
    candidates: list = field(default_factory=list)
    witnesses: list = field(default_factory=list)
    reason: str = ""                      # sub-reason, used by NO_MATCH
    reach_words: dict = field(default_factory=dict)
    histories: list = field(default_factory=list)       # weak: [(word, b_end)]
    n_histories: Optional[int] = None                    # weak
    n_pairs: Optional[int] = None                        # strong
    pairs_with_q: list = field(default_factory=list)     # strong
    live: Live = field(default_factory=Live)
    live_exact: bool = True                              # weak: False if `live` is the strong over-approximation
    strong_ends: dict = field(default_factory=dict)      # weak: B-state (None = stuck) -> shortest history, all histories
    weak_notes: list = field(default_factory=list)       # weak: [(b_state, "shortest"|"search"|"none", word)]

    def signature(self) -> str:
        """Compact comparable form, e.g. 'UNIQUE odd' or 'AMBIGUOUS e s2'."""
        if self.verdict == UNIQUE:
            return f"UNIQUE {self.p}"
        if self.verdict == AMBIGUOUS:
            return "AMBIGUOUS " + " ".join(sorted(self.candidates))
        return self.verdict


# ------------------------------------------------------------------ primitives
def run_word(M, word, policy) -> Trace:
    """Run automaton M on word under the given policy."""
    q, steps = M.start, []
    for i, c in enumerate(word):
        t = M.delta.get((q, c))
        if t is None:
            if policy == LENIENT:
                steps.append((q, c, q, True))
                continue
            return Trace(M.start, steps, (i, q, c))
        steps.append((q, c, t, False))
        q = t
    return Trace(M.start, steps, None)


def _a_next(A, a, c, policy):
    """(next state, skipped) or None when A is stuck (strict): not a history."""
    t = A.delta.get((a, c))
    if t is not None:
        return t, False
    return (a, True) if policy == LENIENT else None


def _b_next(B, b, c, policy):
    """(next state | BOT, skipped)."""
    if b is BOT:
        return BOT, False
    t = B.delta.get((b, c))
    if t is not None:
        return t, False
    return (b, True) if policy == LENIENT else (BOT, False)


def reachable_words(A) -> dict:
    """Shortest (then lexicographically smallest) word to every reachable state."""
    words = {A.start: ()}
    dq = deque([A.start])
    while dq:
        a = dq.popleft()
        for c in A.sigma:
            t = A.delta.get((a, c))
            if t is not None and t not in words:
                words[t] = words[a] + (c,)
                dq.append(t)
    return words


# ---------------------------------------------------------------------- strong
class Product:
    """Reachable part of the product automaton A x B (B may be BOT = stuck)."""

    def __init__(self, parent, edges):
        self.parent, self.edges = parent, edges
        self.rev = defaultdict(list)
        for u, c, v, _, _ in edges:
            self.rev[v].append(u)

    def word_of(self, node):
        w = []
        while self.parent[node] is not None:
            node, c = self.parent[node]
            w.append(c)
        return tuple(reversed(w))

    def dist_to(self, target) -> dict:
        """Number of steps from every pair to `target` (backward BFS)."""
        dist, dq = {target: 0}, deque([target])
        while dq:
            v = dq.popleft()
            for u in self.rev[v]:
                if u not in dist:
                    dist[u] = dist[v] + 1
                    dq.append(u)
        return dist


def _strong(A, B, q, policy):
    """BFS over the product A x B.  Histories = all words reaching a pair (q, *)."""
    start = (A.start, B.start)
    parent = {start: None}
    edges = []
    dq = deque([start])
    while dq:
        u = dq.popleft()
        a, b = u
        for c in A.sigma:
            na = _a_next(A, a, c, policy)
            if na is None:
                continue
            a2, a_skip = na
            b2, b_skip = _b_next(B, b, c, policy)
            v = (a2, b2)
            edges.append((u, c, v, a_skip, b_skip))
            if v not in parent:
                parent[v] = (u, c)
                dq.append(v)
    prod = Product(parent, edges)

    targets = [n for n in parent if n[0] == q]
    outcomes = {n[1]: prod.word_of(n) for n in targets}

    co, stack = set(targets), list(targets)
    while stack:
        v = stack.pop()
        for u in prod.rev[v]:
            if u not in co:
                co.add(u)
                stack.append(u)

    live = Live(set(), set(), set(), set())
    for u, c, v, a_skip, b_skip in edges:
        if v not in co:
            continue
        live.a_states.update((u[0], v[0]))
        if not a_skip:
            live.a_edges.add((u[0], c, v[0]))
        if u[1] is not BOT:
            live.b_states.add(u[1])
        if v[1] is not BOT:
            live.b_states.add(v[1])
            if u[1] is not BOT and not b_skip:
                live.b_edges.add((u[1], c, v[1]))
    if A.start == q:                      # the empty word
        live.a_states.add(q)
        live.b_states.add(B.start)
    extra = dict(n_pairs=len(parent),
                 pairs_with_q=sorted(targets, key=lambda n: (len(prod.word_of(n)), str(n[1]))))
    return outcomes, live, extra, prod


# ------------------------------------------------------------------------ weak
def _is_simple(trace) -> bool:
    seq = [trace.start] + [s[2] for s in trace.steps]
    return len(set(seq)) == len(seq)


def _search_simple(A, B, q, policy, target_b, dist):
    """Shortest simple history of q that ends B in `target_b`, or None.

    Iterative deepening DFS over simple runs of A.  `dist` (product distances to the target
    pair) is an admissible bound: branches that cannot finish within the limit are cut."""
    start = (A.start, B.start)
    d0 = dist.get(start)
    if d0 is None:
        return None
    nodes = 0

    def dfs(a, b, visited, word, limit):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_SEARCH_NODES:
            raise TooManyHistories(
                "the exact search for simple histories became too large; "
                "use --definition strong, or a smaller automaton")
        if a == q:                         # a simple run must stop at its first visit of q
            return tuple(word) if b == target_b else None
        remaining = limit - len(word)
        for c in A.sigma:
            a2 = A.delta.get((a, c))
            if a2 is None or a2 in visited:
                continue
            b2, _ = _b_next(B, b, c, policy)
            dd = dist.get((a2, b2))
            if dd is None or dd + 1 > remaining:
                continue
            word.append(c)
            visited.add(a2)
            found = dfs(a2, b2, visited, word, limit)
            visited.discard(a2)
            word.pop()
            if found is not None:
                return found
        return None

    for limit in range(d0, len(A.states)):          # a simple run has at most |Q_A|-1 steps
        found = dfs(A.start, B.start, {A.start}, [], limit)
        if found is not None:
            return found
    return None


def _weak_hybrid(A, B, q, policy, prod, strong_ends):
    """Candidates come from the strong analysis; each is confirmed by a simple history."""
    outcomes, notes = {}, []
    order = sorted(strong_ends, key=lambda k: (len(strong_ends[k]), -1 if k is BOT else B.states.index(k)))
    for b in order:
        w = strong_ends[b]
        if _is_simple(run_word(A, w, policy)):
            outcomes[b] = w
            notes.append((b, "shortest", w))
            continue
        found = _search_simple(A, B, q, policy, b, prod.dist_to((q, b)))
        if found is None:
            notes.append((b, "none", w))
        else:
            outcomes[b] = found
            notes.append((b, "search", found))
    return outcomes, notes


def _weak_enumerate(A, B, q, policy, budget):
    """List ALL simple histories (for explanations and the grey parts of pictures).

    Returns None if more than `budget` DFS nodes would be needed."""
    rev = defaultdict(list)
    for (s, c), t in A.delta.items():
        rev[t].append(s)
    can, stack = {q}, [q]                 # states that can still reach q
    while stack:
        v = stack.pop()
        for u in rev[v]:
            if u not in can:
                can.add(u)
                stack.append(u)

    outcomes, histories = {}, []
    live = Live(set(), set(), set(), set())
    nodes = 0

    def mark(path):
        live.a_states.add(q)
        live.b_states.add(B.start)
        for (a, c, a2, b, b2, b_skip) in path:
            live.a_states.add(a)
            live.a_edges.add((a, c, a2))
            if b is not BOT:
                live.b_states.add(b)
                if b2 is not BOT:
                    live.b_states.add(b2)
                    if not b_skip:
                        live.b_edges.add((b, c, b2))

    def dfs(a, b, visited, word, path):
        nonlocal nodes
        nodes += 1
        if nodes > budget:
            raise _Budget
        if a == q:
            w = tuple(word)
            histories.append((w, b))
            if b not in outcomes or len(w) < len(outcomes[b]):
                outcomes[b] = w
            mark(path)
            return
        for c in A.sigma:
            a2 = A.delta.get((a, c))
            if a2 is None or a2 in visited or a2 not in can:
                continue
            b2, b_skip = _b_next(B, b, c, policy)
            word.append(c)
            path.append((a, c, a2, b, b2, b_skip))
            visited.add(a2)
            dfs(a2, b2, visited, word, path)
            visited.discard(a2)
            path.pop()
            word.pop()

    try:
        dfs(A.start, B.start, {A.start}, [], [])
    except _Budget:
        return None
    return outcomes, live, dict(histories=histories, n_histories=len(histories))


# ---------------------------------------------------------------------- driver
def analyze(A, B, q, definition=WEAK, policy=STRICT) -> Result:
    if definition not in (STRONG, WEAK) or policy not in (STRICT, LENIENT):
        raise ValueError("definition must be strong|weak, policy must be strict|lenient")
    if q not in A.states:
        raise ValueError(f"state '{q}' does not exist in the old automaton "
                         f"(states: {', '.join(A.states)})")
    words = reachable_words(A)
    res = Result(definition, policy, q, UNREACHABLE, reach_words=words)

    if q not in words:
        reach = set(words)
        res.live = Live(a_states=reach,
                        a_edges={(s, c, t) for (s, c), t in A.delta.items() if s in reach})
        return res

    if q not in A.accepting:               # H(q) is empty: histories must lie in L(A)
        w = words[q]
        res.verdict, res.reason = NO_MATCH, "q_not_accepting"
        res.witnesses = [Witness(w, run_word(A, w, policy), None, None)]
        return res

    strong_ends, live_strong, extra, prod = _strong(A, B, q, policy)
    res.n_pairs, res.pairs_with_q = extra["n_pairs"], extra["pairs_with_q"]
    if definition == STRONG:
        outcomes, res.live = strong_ends, live_strong
    else:
        res.strong_ends = dict(strong_ends)
        outcomes, res.weak_notes = _weak_hybrid(A, B, q, policy, prod, strong_ends)
        enum = _weak_enumerate(A, B, q, policy, ENUM_BUDGET)
        if enum is None:                   # too many simple histories to list: show the strong parts
            res.live, res.live_exact = live_strong, False
        else:
            e_out, res.live, e_extra = enum
            assert {k: len(v) for k, v in e_out.items()} == {k: len(v) for k, v in outcomes.items()}, \
                "internal error: hybrid search and full enumeration disagree"
            res.histories, res.n_histories = e_extra["histories"], e_extra["n_histories"]
    assert outcomes, "q is reachable and accepting, so a history must exist"

    def witness(b_end):
        w = outcomes[b_end]
        return Witness(w, run_word(A, w, policy), run_word(B, w, policy), b_end)

    states = [k for k in outcomes if k is not BOT]
    states.sort(key=lambda k: (len(outcomes[k]), B.states.index(k)))
    stuck = [witness(BOT)] if BOT in outcomes else []
    res.witnesses = stuck + [witness(k) for k in states]
    res.candidates = states

    if stuck:
        res.verdict = STUCK
    elif len(states) >= 2:
        res.verdict = AMBIGUOUS
    else:
        res.p = states[0]
        if res.p in B.accepting:
            res.verdict = UNIQUE
        else:
            res.verdict, res.reason = NO_MATCH, "b_rejects"
    return res


# ------------------------------------------------------ strong => weak, weak is more permissive
AGREE = "AGREE"                      # strong has at most one ending, weak must give the same answer
WEAK_ADDS = "WEAK_ADDS"              # weak has a unique counterpart that strong does not have
SAME_ENDINGS = "SAME_ENDINGS"        # both see the same endings, no unique counterpart in either
WEAK_SEES_LESS = "WEAK_SEES_LESS"    # weak sees fewer endings but still no unique counterpart
INCONSISTENT = "INCONSISTENT"        # impossible; would mean a bug


@dataclass
class Relation:
    kind: str
    strong: Result
    weak: Result
    only_strong: list = field(default_factory=list)   # Witness of endings that only strong sees
    problem: str = ""


def outcome_set(r: Result) -> set:
    """The endings O(q) of all histories: B-states, None = "B is stuck". Empty if there is no history."""
    if r.verdict == UNREACHABLE or (r.verdict == NO_MATCH and r.reason == "q_not_accepting"):
        return set()
    return {w.b_state for w in r.witnesses}


def compare_definitions(rs: Result, rw: Result) -> Relation:
    """Relation between the strong result ``rs`` and the weak result ``rw`` (same state, same policy).

    Facts guaranteed by the theory (violations are reported as INCONSISTENT):
      * O_weak is a subset of O_strong;
      * if strong has at most one ending, weak gives exactly the same answer
        (in particular p ~strong q  implies  p ~weak q);
    and what may differ: weak can have a unique counterpart where strong has several endings."""
    assert (rs.definition, rw.definition) == (STRONG, WEAK) and rs.q == rw.q and rs.policy == rw.policy
    o_s, o_w = outcome_set(rs), outcome_set(rw)
    only = [w for w in rs.witnesses if w.b_trace is not None and w.b_state not in o_w]

    def bad(msg):
        return Relation(INCONSISTENT, rs, rw, only, msg)

    if not o_w <= o_s:
        return bad(f"weak sees endings {sorted(map(str, o_w - o_s))} that strong does not see")
    if len(o_s) <= 1:                                    # nothing for weak to filter out
        if rs.signature() != rw.signature() or o_s != o_w:
            return bad(f"strong says {rs.signature()}, but weak says {rw.signature()}")
        return Relation(AGREE, rs, rw)
    if rw.verdict == UNIQUE:
        return Relation(WEAK_ADDS, rs, rw, only)
    return Relation(SAME_ENDINGS if o_w == o_s else WEAK_SEES_LESS, rs, rw, only)
