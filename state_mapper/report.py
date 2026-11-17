"""Text reports for a Result: 'short' (verdict + witnesses) and 'explain' (step by step)."""
from __future__ import annotations

from mapping import (AGREE, AMBIGUOUS, EXISTENCE, EXISTENCE_ADDS, INCONSISTENT, LENIENT, NO_MATCH, SAME_CANDIDATES,
                     SAME_ENDINGS, SIMPLE, SIMPLE_ADDS, SIMPLE_SEES_LESS, STRICT, STRONG, STUCK, UNIQUE,
                     UNREACHABLE, run_word)

DEF_TEXT = {
    STRONG: "strong    - FOR ALL words w in L(A) with delta_A*(a0,w) = q (cycles allowed):\n"
            "            all of them must lead B to the same state",
    SIMPLE: "simple    - the same, but only for the simple histories (runs of A without a repeated state);\n"
            "            it sees fewer histories, so it allows MORE corresponding states than strong",
    EXISTENCE: "existence - the same search, but with EXISTS instead of FOR ALL: every state of B that SOME\n"
               "            history of q can lead to is a candidate (all candidates are listed)",
}
POLICY_TEXT = {
    STRICT: "strict  - a letter without a transition => the automaton is STUCK",
    LENIENT: "lenient - a letter without a transition is skipped (the state stays)",
}


def fmt_word(w) -> str:
    return '"' + " ".join(w) + '"' if w else '"" (empty word)'


def fmt_trace(t) -> str:
    parts = [t.start]
    for _, c, dst, skip in t.steps:
        parts += [f"-{c}[skipped]->" if skip else f"-{c}->", dst]
    if t.stuck is not None:
        parts.append(f"-{t.stuck[2]}-> X")
    return " ".join(parts)


def _tag(r) -> str:
    return f"[{r.definition}/{r.policy}]"


def _stuck_info(w) -> str:
    i, s, c = w.b_trace.stuck
    return f"B has no transition on '{c}' in state '{s}' (letter #{i + 1} of the history)"


def _name(r, b) -> str:
    """A B-state for printing; non-accepting ones are marked when the files declare accepting states."""
    return f"{b} (not accepting)" if b in r.non_accepting else str(b)


def _cand_list(r) -> list:
    return [w.b_state for w in r.witnesses if w.b_trace is not None and w.b_state is not None]


def _braces(items) -> str:
    return "{" + ", ".join(map(str, items)) + "}"


# ------------------------------------------------------------------------ short
def format_short(r) -> str:
    t = _tag(r)
    rev = r.definition == EXISTENCE
    if r.verdict == UNIQUE:
        extra = "   (the only candidate)" if rev else ""
        lines = [f"{t} UNIQUE: {r.q} (A)  <->  {r.p} (B){extra}",
                 f"    witness: {fmt_word(r.witnesses[0].word)}"]
    elif r.verdict == AMBIGUOUS:
        lines = [f"{t} AMBIGUOUS: {r.q} (A)  ->  candidates in B: {', '.join(_name(r, c) for c in r.candidates)}"]
        lines += [f"    {w.b_state}: witness {fmt_word(w.word)}" for w in r.witnesses if w.b_trace is not None
                  and w.b_state is not None]
    elif r.verdict == STUCK:
        w = r.witnesses[0]
        why = "no history leads B to any state: " if rev else ""
        lines = [f"{t} STUCK: {why}{_stuck_info(w)}", f"    witness: {fmt_word(w.word)}"]
    elif r.verdict == UNREACHABLE:
        lines = [f"{t} UNREACHABLE: {r.q} cannot be reached from the start state of A",
                 f"    witness: none; the {len(r.reach_words)} reachable states "
                 f"({', '.join(r.reach_words)}) are closed under all transitions"]
    elif r.reason == "q_not_accepting":
        lines = [f"{t} NO_MATCH: {r.q} is not an accepting state of A, so it has no histories",
                 f"    witness: {fmt_word(r.witnesses[0].word)} reaches {r.q}, but is not in L(A)"]
    else:
        what = f"the only candidate {r.p} is" if rev else f"every history leads B to {r.p}, which is"
        lines = [f"{t} NO_MATCH: {what} not accepting (not in L(B))",
                 f"    witness: {fmt_word(r.witnesses[0].word)}"]
    if r.ignored_stuck:
        lines.append(f"    note: B also gets stuck on some histories, e.g. {fmt_word(r.ignored_stuck[0].word)} "
                     "(the existence mode ignores them: they lead nowhere)")
    return "\n".join(lines)


# ---------------------------------------------------------------------- explain
def _outcome_block(r, w, lines, indent="    "):
    target = "STUCK" if w.b_state is None else _name(r, w.b_state)
    lines.append(f"  -> B ends in {target}; shortest such history: {fmt_word(w.word)}")
    lines.append(f"{indent}A: {fmt_trace(w.a_trace)}")
    lines.append(f"{indent}B: {fmt_trace(w.b_trace)}")


def format_explain(r, A, B) -> str:
    L = [f"{_tag(r)} current state of A: '{r.q}'",
         f"  definition: {DEF_TEXT[r.definition]}",
         f"  policy    : {POLICY_TEXT[r.policy]}", ""]

    L.append("Step 1. Is the state reachable in A?")
    if r.verdict == UNREACHABLE:
        L.append(f"  No. States reachable from '{A.start}' (shortest word to each):")
        for s, w in r.reach_words.items():
            L.append(f"    {s:<12}{fmt_word(w)}")
        L.append(f"  This set is closed under all transitions of A and does not contain '{r.q}',")
        L.append("  so no word leads A from its start state to it: there are no histories.")
        L += ["", "Verdict: UNREACHABLE.  Witness: none (the closed set above is the certificate)."]
        return "\n".join(L)
    w0 = r.reach_words[r.q]
    L.append(f"  Yes. Shortest word: {fmt_word(w0)}")
    L.append(f"    A: {fmt_trace(run_word(A, w0, r.policy))}")

    L += ["", "Step 2. Is it an accepting state of A (histories must lie in L(A))?"]
    acc = sorted(A.accepting, key=A.states.index)
    if not A.explicit_accepting:
        L.append("  The file declares no accepting states, so every state of A is accepting.")
    elif r.reason == "q_not_accepting":
        L.append(f"  F_A = {{{', '.join(acc)}}}: '{r.q}' is NOT accepting, so H_A('{r.q}') is empty.")
        L += ["", "Verdict: NO_MATCH - the definition needs a non-empty set of histories inside L(A).",
              f"  Witness: {fmt_word(w0)} reaches '{r.q}' but is not in L(A)."]
        return "\n".join(L)
    else:
        L.append(f"  F_A = {{{', '.join(acc)}}}: '{r.q}' is accepting.")

    L += ["", "Step 3. Collect the histories of the state"]
    if r.definition in (STRONG, EXISTENCE):
        L.append(f"  Searched the product A x B from ({A.start}, {B.start}): "
                 f"{r.n_pairs} reachable pairs (state of A, state of B).")
        L.append(f"  Pairs whose A-component is '{r.q}' "
                 f"(X = B stuck), i.e. all possible endings of a history in B:")
        for a, b in r.pairs_with_q:
            L.append(f"    ({a}, {'X' if b is None else b})")
        if r.definition == STRONG:
            L.append("  (strong: the set of histories may be infinite, the product covers all of them)")
        else:
            L.append("  (existence: a pair (q, b) here means that SOME history of q leads B to b; "
                     "that is all that is needed)")
    else:
        L.append("  simple: only simple histories count (runs of A without a repeated state).")
        L.append(f"  3a. Polynomial pre-check (product A x B, {r.n_pairs} reachable pairs): "
                 "histories, simple or not, can end B only in")
        L.append("      " + ", ".join("X (stuck)" if b is None else b for b in r.strong_ends) + ".")
        L.append("      (simple histories are histories, so simple sees a SUBSET of these endings)")
        L.append("  3b. A candidate stays only if some SIMPLE history leads there:")
        for b, how, w in r.simple_notes:
            name = "X (stuck)" if b is None else b
            if how == "shortest":
                L.append(f"      {name}: yes - its shortest history {fmt_word(w)} is already simple")
            elif how == "search":
                L.append(f"      {name}: yes - the shortest history repeats a state of A, but the exact "
                         f"search found the simple history {fmt_word(w)}")
            else:
                L.append(f"      {name}: NO  - the shortest history {fmt_word(w)} repeats a state of A and "
                         "the exact search finds no simple history ending there")
        if r.n_histories is not None:
            L.append(f"  3c. For reference, all {r.n_histories} simple histories:")
            for w, b in r.histories[:12]:
                L.append(f"      {fmt_word(w):<24} -> B: {'X (stuck)' if b is None else b}")
            if r.n_histories > 12:
                L.append(f"      ... and {r.n_histories - 12} more")
        else:
            L.append("  (too many simple histories to list them all; the search above does not need that)")

    if r.definition == EXISTENCE:
        L += ["", "Step 4. Which states of B can a history lead to (the candidates)?"]
    else:
        L += ["", "Step 4. Where do the histories end in B?"]
    for w in r.witnesses:
        _outcome_block(r, w, L)
    if r.ignored_stuck:
        L.append("  Histories on which B gets stuck lead nowhere, so they give no candidate (ignored):")
        _outcome_block(r, r.ignored_stuck[0], L)

    L.append("")
    rev = r.definition == EXISTENCE
    if r.verdict == UNIQUE:
        L.append(f"Verdict: UNIQUE.  State '{r.q}' of A corresponds to state '{r.p}' of B.")
        if rev:
            L.append(f"  '{r.p}' is the only state of B that a history of '{r.q}' can lead to "
                     f"(witness {fmt_word(r.witnesses[0].word)}).")
        else:
            L.append(f"  Every history ends in '{r.p}' and B accepts them all "
                     f"(witness {fmt_word(r.witnesses[0].word)}).")
    elif r.verdict == AMBIGUOUS:
        L.append(f"Verdict: AMBIGUOUS.  Candidates: {', '.join(_name(r, c) for c in r.candidates)}.")
        if rev:
            L.append("  Each candidate is reached by at least one history of the state. Witnesses:")
        else:
            L.append("  Different histories of the same state of A lead B to different states,")
            L.append("  so no single state of B corresponds to it. Witnesses:")
        for w in r.witnesses:
            if w.b_state is not None:
                L.append(f"    {w.b_state}: {fmt_word(w.word)}")
    elif r.verdict == STUCK:
        if rev:
            L.append("Verdict: STUCK.  No history leads B to any state: every history makes B stuck.")
            L.append(f"  {_stuck_info(r.witnesses[0])}.")
        else:
            L.append(f"Verdict: STUCK.  {_stuck_info(r.witnesses[0])}.")
        L.append(f"  Witness history: {fmt_word(r.witnesses[0].word)}.  "
                 "(Use the lenient policy to skip such letters instead.)")
    else:   # NO_MATCH, B side
        if rev:
            L.append(f"Verdict: NO_MATCH.  The only candidate '{r.p}' is not accepting,")
        else:
            L.append(f"Verdict: NO_MATCH.  All histories lead B to '{r.p}', but '{r.p}' is not accepting,")
        L.append("  so the histories are not in L(B), which the definition requires.")
        L.append(f"  Witness: {fmt_word(r.witnesses[0].word)}.")
    return "\n".join(L)


def format_result(r, A, B, mode="short") -> str:
    return format_explain(r, A, B) if mode in ("explain", "explained") else format_short(r)


# ----------------------------------- strong => simple => existence: relations and the state table
def _ending(b) -> str:
    return "STUCK" if b is None else b


def short_verdict(r) -> str:
    """'UNIQUE s2' | 'AMBIGUOUS {e, s2}' | 'STUCK' | 'UNREACHABLE' | 'NO_MATCH'."""
    if r.verdict == UNIQUE:
        return f"UNIQUE {r.p}"
    if r.verdict == AMBIGUOUS:
        return "AMBIGUOUS {" + ", ".join(r.candidates) + "}"
    return r.verdict


def _why(mode, lines):
    return list(lines) if mode in ("explain", "explained") else []


def format_relation(rel, mode="short") -> str:
    """A block about the relation of two results of the same state/policy; '' if there is nothing to say."""
    lo, hi = rel.lo, rel.hi
    head = f"[{lo.policy}] relation {rel.pair[0]} -> {rel.pair[1]}: "
    lines = []
    if rel.kind == INCONSISTENT:
        return head + f"INCONSISTENT - {rel.problem}  (this is a bug)"

    if rel.pair == ("strong", "simple"):
        if rel.kind == AGREE:
            lines.append(head + f"holds, both say {short_verdict(lo)}")
        elif rel.kind == SIMPLE_ADDS:
            lines.append(head + f"simple is more permissive here: simple {short_verdict(hi)}, "
                                f"strong {short_verdict(lo)}")
        elif rel.kind == SAME_ENDINGS:
            lines.append(head + f"no difference here (both see the same endings, strong {short_verdict(lo)})")
        elif rel.kind == SIMPLE_SEES_LESS:
            lines.append(head + f"simple sees fewer endings (simple {short_verdict(hi)}, "
                                f"strong {short_verdict(lo)}), still no unique counterpart")
        if rel.extra:
            lines.append("    only strong sees (these histories repeat a state of A, so simple ignores them):")
            lines += [f"      {_ending(w.b_state)} via {fmt_word(w.word)}" for w in rel.extra]
        lines += _why(mode, ["    why: simple histories are histories, so simple sees a subset of the endings of strong;",
                             "         fewer endings make a single one more likely: strong UNIQUE p => simple UNIQUE p,",
                             "         but simple UNIQUE p does not imply strong UNIQUE p."])
    elif rel.pair == ("simple", "existence"):
        c_i, c_r = _cand_list(lo), _cand_list(hi)
        if rel.kind == SAME_CANDIDATES:
            what = _braces(c_r) if c_r else "none"
            lines.append(head + f"holds, both reach the same states: {what}")
        else:
            lines.append(head + f"existence lists more candidates: existence {_braces(c_r)}, simple {_braces(c_i)}")
            lines.append("    only existence reaches (these histories repeat a state of A, so simple ignores them):")
            lines += [f"      {w.b_state} via {fmt_word(w.word)}" for w in rel.extra]
        lines += _why(mode, ["    why: every simple history is a history, so every state it leads to is a candidate of existence;",
                             "         the converse fails: histories that repeat a state of A are seen only by existence."])
    else:                                              # strong -> existence: only interesting if it fails
        return ""
    return "\n".join(lines)


def format_state_table(rows, policy, A_name="A", mode="short") -> str:
    """rows: [(q, strong Result, simple Result, existence Result, [Relation, ...])] for all states of A."""
    cells = [(q, short_verdict(rs), short_verdict(ri), short_verdict(rx), rels) for q, rs, ri, rx, rels in rows]
    w0 = max(len("state"), *(len(c[0]) for c in cells))
    w1 = max(len("strong"), *(len(c[1]) for c in cells))
    w2 = max(len("simple"), *(len(c[2]) for c in cells))
    w3 = max(len("existence"), *(len(c[3]) for c in cells))
    out = [f"all states of {A_name}, policy {policy}",
           f"  {'state':<{w0}} | {'strong':<{w1}} | {'simple':<{w2}} | {'existence':<{w3}} | note"]
    out.append("  " + "-" * (w0 + w1 + w2 + w3 + 16))
    n_s = n_i = n_r = 0
    bad = []
    for (q, vs, vi, vr, rels), (_, rs, ri, rx, _) in zip(cells, rows):
        n_s += rs.verdict == UNIQUE
        n_i += ri.verdict == UNIQUE
        n_r += rx.verdict == UNIQUE
        notes = []
        for rel in rels:
            if rel.kind == INCONSISTENT:
                notes.append("INCONSISTENT (bug)")
                bad.append(q)
            elif rel.kind == SIMPLE_ADDS:
                notes.append(f"simple adds {ri.p}")
            elif rel.kind == EXISTENCE_ADDS:
                notes.append("existence also lists " + ", ".join(str(w.b_state) for w in rel.extra))
        out.append(f"  {q:<{w0}} | {vs:<{w1}} | {vi:<{w2}} | {vr:<{w3}} | {'; '.join(notes)}".rstrip())
    n = len(cells)
    out.append(f"  states with a unique counterpart: strong {n_s}/{n}, simple {n_i}/{n}; "
               f"existence has exactly one candidate for {n_r}/{n}")
    out.append("  " + ("(every strong pair is also a simple pair, and every simple pair is among the "
                       "existence candidates)" if not bad else f"INCONSISTENT at {sorted(set(bad))}"))
    if mode in ("explain", "explained"):
        for q, rs, ri, rx, rels in rows:
            for rel in rels:
                if rel.kind == SIMPLE_ADDS:
                    out.append(f"  {q}: simple adds {ri.p}; strong also sees (histories that repeat a state of A):")
                    out += [f"      {_ending(w.b_state)} via {fmt_word(w.word)}" for w in rel.extra]
                elif rel.kind == EXISTENCE_ADDS:
                    out.append(f"  {q}: existence also lists (histories that repeat a state of A):")
                    out += [f"      {w.b_state} via {fmt_word(w.word)}" for w in rel.extra]
    return "\n".join(out)
