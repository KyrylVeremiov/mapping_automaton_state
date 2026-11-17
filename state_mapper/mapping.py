"""Core algorithm: which state p of B corresponds to the current state q of A?

Notation (the formal text calls the "simple" definition below "weak")
  H(q)       = { w in L(A) : delta_A*(a0, w) = q }                     histories of q
  Hsimple(q) = { w in H(q) : the run of A on w visits no state twice }   simple histories
  O(q)       = { delta_B*(b0, w) : w in H(q) }   (undefined = "stuck")   endings of the histories

Three definitions (modes) of the criterion
  strong     p ~ q  <=>  H(q) != {}  and  FOR ALL w in H(q):  w in L(B) and delta_B*(b0, w) = p
  simple     the same, but only FOR ALL simple histories w in Hsimple(q)
  existence  p is a CANDIDATE  <=>  THERE EXISTS w in H(q) with delta_B*(b0, w) = p
             i.e. the criterion of "strong" with the quantifier over the words turned from "for all"
             into "exists": the result is the list of ALL states of B that some history of q can lead to.
             (Histories on which B gets stuck lead nowhere and give no candidate; they are only reported.
             If accepting states are declared, a candidate that is not accepting is marked as such.)

Relations between the definitions  (Hsimple(q) is a subset of H(q))
  * Endings:  O_simple(q) is a subset of O_strong(q);  the candidates of existence are exactly the
    defined (not stuck) endings of ALL histories, i.e. of O_strong(q).
  * Corresponding states:  C(q) = { p : p ~ q }  has at most one element for strong and for simple, and
    C_strong(q) <= C_simple(q) <= C_existence(q):   p ~strong q  ==>  p ~simple q  ==>  p is a candidate of existence.
    None of the inclusions can be reversed:  O_strong = {s2, e}: strong says AMBIGUOUS, simple (which sees
    only the simple history leading to s2) says UNIQUE s2, existence lists both s2 and e.  And a single
    candidate of existence is no proof of ~strong: histories on which B gets stuck are invisible to existence.
  compare_strong_simple(), compare_simple_existence() and compare_all() check these facts for results.

How it is computed        n = |Q_A|, m = |Q_B|, k = |alphabet|
  strong, existence: breadth-first search in the product automaton A x B (at most n(m+1) pairs and
           n(m+1)k edges):  O(n*m*k) time for the search plus O(n*m^2) for the shortest witness words,
           O(n*m) memory.  Polynomial (the question is a reachability question, so it is even in NL).
  simple : hybrid.  (1) the strong analysis gives every B-state that some history can reach; simple
           histories are histories, so O_simple <= O_strong: strong supplies an UPPER bound for the
           candidates, which simple then filters (it never has a candidate that strong lacks).
           (2) a candidate is confirmed at once if its shortest history is already simple;
           otherwise (3) an exact depth-first search looks for a simple history ending there,
           pruned with product distances.  Finding simple paths is NP-hard in general, so step (3)
           is exponential only in the worst case: O(n*m*(k+m)) for steps (1)-(2) plus at most
           m+1 exact searches of O(n * k^n) each.

Policies for a letter without transition:
  strict  : the automaton gets STUCK (delta* is undefined)
  lenient : the letter is skipped, the state does not change
            (i.e. delta is replaced by its total extension with self-loops).

Verdicts: UNIQUE, AMBIGUOUS, STUCK, UNREACHABLE and - only when the files declare
accepting states - NO_MATCH (the definition demands w in L(A) and w in L(B)).
For existence, UNIQUE means "exactly one candidate" and AMBIGUOUS "several candidates" (all listed).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

STRONG, SIMPLE, EXISTENCE = "strong", "simple", "existence"
DEFINITION_NAMES = (STRONG, SIMPLE, EXISTENCE)
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
    histories: list = field(default_factory=list)       # simple: [(word, b_end)]
    n_histories: Optional[int] = None                    # simple
    n_pairs: Optional[int] = None                        # strong
    pairs_with_q: list = field(default_factory=list)     # strong
    live: Live = field(default_factory=Live)
    live_exact: bool = True                              # simple: False if `live` is the strong over-approximation
    strong_ends: dict = field(default_factory=dict)      # simple: B-state (None = stuck) -> shortest history, all histories
    simple_notes: list = field(default_factory=list)       # simple: [(b_state, "shortest"|"search"|"none", word)]
    ignored_stuck: list = field(default_factory=list)    # existence: histories on which B gets stuck (not candidates)
    non_accepting: list = field(default_factory=list)    # candidates that are not accepting in B (if declared)

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


# ------------------------------------------------------------------------ simple
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


def _simple_hybrid(A, B, q, policy, prod, strong_ends):
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


def _simple_enumerate(A, B, q, policy, budget):
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
def analyze(A, B, q, definition=SIMPLE, policy=STRICT) -> Result:
    if definition not in DEFINITION_NAMES or policy not in (STRICT, LENIENT):
        raise ValueError("definition must be strong|simple|existence, policy must be strict|lenient")
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
    if definition in (STRONG, EXISTENCE):     # the same product search; only the quantifier differs
        outcomes, res.live = strong_ends, live_strong
    else:
        res.strong_ends = dict(strong_ends)
        outcomes, res.simple_notes = _simple_hybrid(A, B, q, policy, prod, strong_ends)
        enum = _simple_enumerate(A, B, q, policy, ENUM_BUDGET)
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
    res.candidates = states
    res.non_accepting = [k for k in states if k not in B.accepting]

    if definition == EXISTENCE:               # "exists": every state some history leads to is a candidate
        if not states:                      # no history leads B anywhere: all of them get B stuck
            res.witnesses, res.verdict = stuck, STUCK
            return res
        res.witnesses, res.ignored_stuck = [witness(k) for k in states], stuck
        if len(states) >= 2:
            res.verdict = AMBIGUOUS
        else:
            res.p = states[0]
            if res.p in B.accepting:
                res.verdict = UNIQUE
            else:
                res.verdict, res.reason = NO_MATCH, "b_rejects"
        return res

    res.witnesses = stuck + [witness(k) for k in states]
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


# ------------------------------------- relations: strong => simple => existence (never the other way)
AGREE = "AGREE"                          # strong has at most one ending: simple must say the same
SIMPLE_ADDS = "SIMPLE_ADDS"              # simple has a unique counterpart that strong does not have
SAME_ENDINGS = "SAME_ENDINGS"            # both see the same endings, no unique counterpart in either
SIMPLE_SEES_LESS = "SIMPLE_SEES_LESS"    # simple sees fewer endings but still no unique counterpart
SAME_CANDIDATES = "SAME_CANDIDATES"      # the two modes list the same candidates
EXISTENCE_ADDS = "EXISTENCE_ADDS"            # existence lists candidates that simple does not reach
INCONSISTENT = "INCONSISTENT"            # impossible; would mean a bug


@dataclass
class Relation:
    """Relation of two results for the same state and policy; pair = (lower, higher) definition."""
    pair: tuple
    kind: str
    lo: Result                           # result of pair[0]
    hi: Result                           # result of pair[1]
    extra: list = field(default_factory=list)   # Witnesses of what only strong (resp. only existence) sees
    problem: str = ""


def outcome_set(r: Result) -> set:
    """The endings O(q) of all histories: B-states, None = "B is stuck". Empty if there is no history."""
    if r.verdict == UNREACHABLE or (r.verdict == NO_MATCH and r.reason == "q_not_accepting"):
        return set()
    return {w.b_state for w in r.witnesses}


def candidate_set(r: Result) -> set:
    """B-states that some history (of the kind this result looks at) leads to; "stuck" is not a state."""
    return {w.b_state for w in r.witnesses if w.b_trace is not None and w.b_state is not None}


def _same_query(a: Result, b: Result, da: str, db: str):
    assert (a.definition, b.definition) == (da, db) and a.q == b.q and a.policy == b.policy, \
        "results must be for the same state and policy"


def compare_strong_simple(rs: Result, ri: Result) -> Relation:
    """Relation between the strong result ``rs`` and the simple result ``ri``.

    Guaranteed by the theory (violations are reported as INCONSISTENT):
      * O_simple is a subset of O_strong;
      * if strong has at most one ending, simple gives exactly the same answer
        (in particular p ~strong q  implies  p ~simple q);
    what may differ: simple can have a unique counterpart where strong has several endings."""
    _same_query(rs, ri, STRONG, SIMPLE)
    pair = (STRONG, SIMPLE)
    o_s, o_i = outcome_set(rs), outcome_set(ri)
    only = [w for w in rs.witnesses if w.b_trace is not None and w.b_state not in o_i]

    def bad(msg):
        return Relation(pair, INCONSISTENT, rs, ri, only, msg)

    if not o_i <= o_s:
        return bad(f"simple sees endings {sorted(map(str, o_i - o_s))} that strong does not see")
    if len(o_s) <= 1:                                    # nothing for simple to filter out
        if rs.signature() != ri.signature() or o_s != o_i:
            return bad(f"strong says {rs.signature()}, but simple says {ri.signature()}")
        return Relation(pair, AGREE, rs, ri)
    if ri.verdict == UNIQUE:
        return Relation(pair, SIMPLE_ADDS, rs, ri, only)
    return Relation(pair, SAME_ENDINGS if o_i == o_s else SIMPLE_SEES_LESS, rs, ri, only)


def compare_simple_existence(ri: Result, rx: Result) -> Relation:
    """Relation between the simple result ``ri`` and the existence result ``rx``.

    Guaranteed: every state that a simple history leads to is a candidate of existence (so a state
    p ~simple q is always among the candidates); existence may list more, namely the endings of
    histories that repeat a state of A (``extra``)."""
    _same_query(ri, rx, SIMPLE, EXISTENCE)
    pair = (SIMPLE, EXISTENCE)
    c_i, c_r = candidate_set(ri), candidate_set(rx)
    only = [w for w in rx.witnesses if w.b_trace is not None and w.b_state not in c_i]
    if not c_i <= c_r:
        return Relation(pair, INCONSISTENT, ri, rx, only,
                        f"simple reaches {sorted(map(str, c_i - c_r))}, which existence does not list")
    return Relation(pair, SAME_CANDIDATES if c_i == c_r else EXISTENCE_ADDS, ri, rx, only)


def compare_strong_existence(rs: Result, rx: Result) -> Relation:
    """strong and existence run the same product search, so they list the same states; existence differs
    only by ignoring histories on which B gets stuck.  Hence, unless strong says STUCK, both give the
    same answer, and strong UNIQUE p  gives  existence UNIQUE p."""
    _same_query(rs, rx, STRONG, EXISTENCE)
    pair = (STRONG, EXISTENCE)
    if candidate_set(rs) != candidate_set(rx):
        return Relation(pair, INCONSISTENT, rs, rx, [], "strong and existence list different states")
    if rs.verdict != STUCK and rs.signature() != rx.signature():
        return Relation(pair, INCONSISTENT, rs, rx, [],
                        f"strong says {rs.signature()}, but existence says {rx.signature()}")
    return Relation(pair, SAME_CANDIDATES, rs, rx, [])


def compare_all(results: dict, policy: str) -> list:
    """All checkable relations for one policy; results = {(definition, policy): Result}."""
    rs, ri, rx = (results.get((d, policy)) for d in (STRONG, SIMPLE, EXISTENCE))
    rels = []
    if rs and ri:
        rels.append(compare_strong_simple(rs, ri))
    if ri and rx:
        rels.append(compare_simple_existence(ri, rx))
    if rs and rx:
        rels.append(compare_strong_existence(rs, rx))
    return rels
