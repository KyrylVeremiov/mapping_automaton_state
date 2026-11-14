"""Text reports for a Result: 'short' (verdict + witnesses) and 'explain' (step by step)."""
from __future__ import annotations

from mapping import (AGREE, AMBIGUOUS, INCONSISTENT, LENIENT, NO_MATCH, SAME_ENDINGS, STRICT, STRONG,
                     STUCK, UNIQUE, UNREACHABLE, WEAK, WEAK_ADDS, WEAK_SEES_LESS, run_word)

DEF_TEXT = {
    STRONG: "strong - every word w in L(A) with delta_A*(a0,w) = q (cycles allowed)",
    WEAK: "weak   - only such words whose run in A visits no state twice (simple histories);\n"
          "           it sees fewer histories, so it allows MORE corresponding states than strong",
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


# ------------------------------------------------------------------------ short
def format_short(r) -> str:
    t = _tag(r)
    if r.verdict == UNIQUE:
        return (f"{t} UNIQUE: {r.q} (A)  <->  {r.p} (B)\n"
                f"    witness: {fmt_word(r.witnesses[0].word)}")
    if r.verdict == AMBIGUOUS:
        lines = [f"{t} AMBIGUOUS: {r.q} (A)  ->  candidates in B: {', '.join(r.candidates)}"]
        lines += [f"    {w.b_state}: witness {fmt_word(w.word)}" for w in r.witnesses]
        return "\n".join(lines)
    if r.verdict == STUCK:
        w = r.witnesses[0]
        return (f"{t} STUCK: {_stuck_info(w)}\n"
                f"    witness: {fmt_word(w.word)}")
    if r.verdict == UNREACHABLE:
        return (f"{t} UNREACHABLE: {r.q} cannot be reached from the start state of A\n"
                f"    witness: none; the {len(r.reach_words)} reachable states "
                f"({', '.join(r.reach_words)}) are closed under all transitions")
    # NO_MATCH
    if r.reason == "q_not_accepting":
        return (f"{t} NO_MATCH: {r.q} is not an accepting state of A, so it has no histories\n"
                f"    witness: {fmt_word(r.witnesses[0].word)} reaches {r.q}, but is not in L(A)")
    w = r.witnesses[0]
    return (f"{t} NO_MATCH: every history leads B to {r.p}, which is not accepting (not in L(B))\n"
            f"    witness: {fmt_word(w.word)}")


# ---------------------------------------------------------------------- explain
def _outcome_block(r, w, lines, indent="    "):
    target = "STUCK" if w.b_state is None else w.b_state
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
        L += ["", f"Verdict: UNREACHABLE.  Witness: none (the closed set above is the certificate)."]
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
    if r.definition == STRONG:
        L.append(f"  Searched the product A x B from ({A.start}, {B.start}): "
                 f"{r.n_pairs} reachable pairs (state of A, state of B).")
        L.append(f"  Pairs whose A-component is '{r.q}' "
                 f"(X = B stuck), i.e. all possible endings of a history in B:")
        for a, b in r.pairs_with_q:
            L.append(f"    ({a}, {'X' if b is None else b})")
        L.append("  (strong: the set of histories may be infinite, the product covers all of them)")
    else:
        L.append("  weak: only simple histories count (runs of A without a repeated state).")
        L.append(f"  3a. Polynomial pre-check (product A x B, {r.n_pairs} reachable pairs): "
                 "histories, simple or not, can end B only in")
        L.append("      " + ", ".join("X (stuck)" if b is None else b for b in r.strong_ends) + ".")
        L.append("      (simple histories are histories, so weak sees a SUBSET of these endings)")
        L.append("  3b. A candidate stays only if some SIMPLE history leads there:")
        for b, how, w in r.weak_notes:
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
    L += ["", "Step 4. Where do the histories end in B?"]
    for w in r.witnesses:
        _outcome_block(r, w, L)

    L.append("")
    if r.verdict == UNIQUE:
        L.append(f"Verdict: UNIQUE.  State '{r.q}' of A corresponds to state '{r.p}' of B.")
        L.append(f"  Every history ends in '{r.p}' and B accepts them all (witness {fmt_word(r.witnesses[0].word)}).")
    elif r.verdict == AMBIGUOUS:
        L.append(f"Verdict: AMBIGUOUS.  Candidates: {', '.join(r.candidates)}.")
        L.append("  Different histories of the same state of A lead B to different states,")
        L.append("  so no single state of B corresponds to it. Witnesses:")
        for w in r.witnesses:
            L.append(f"    {w.b_state}: {fmt_word(w.word)}")
    elif r.verdict == STUCK:
        L.append(f"Verdict: STUCK.  {_stuck_info(r.witnesses[0])}.")
        L.append(f"  Witness history: {fmt_word(r.witnesses[0].word)}.  "
                 "(Use the lenient policy to skip such letters instead.)")
    else:   # NO_MATCH, B side
        L.append(f"Verdict: NO_MATCH.  All histories lead B to '{r.p}', but '{r.p}' is not accepting,")
        L.append("  so the histories are not in L(B), which the definition requires.")
        L.append(f"  Witness: {fmt_word(r.witnesses[0].word)}.")
    return "\n".join(L)


def format_result(r, A, B, mode="short") -> str:
    return format_explain(r, A, B) if mode in ("explain", "explained") else format_short(r)


# -------------------------------------------------- strong => weak: relation and state table
def _ending(b) -> str:
    return "STUCK" if b is None else b


def short_verdict(r) -> str:
    """'UNIQUE s2' | 'AMBIGUOUS {e, s2}' | 'STUCK' | 'UNREACHABLE' | 'NO_MATCH'."""
    if r.verdict == UNIQUE:
        return f"UNIQUE {r.p}"
    if r.verdict == AMBIGUOUS:
        return "AMBIGUOUS {" + ", ".join(r.candidates) + "}"
    return r.verdict


def format_relation(rel, mode="short") -> str:
    """One block about the relation of the strong and the weak result of the same state/policy."""
    rs, rw = rel.strong, rel.weak
    head = f"[{rs.policy}] relation strong -> weak: "
    lines = []
    if rel.kind == AGREE:
        lines.append(head + f"holds, both say {short_verdict(rs)}")
    elif rel.kind == WEAK_ADDS:
        lines.append(head + f"weak is more permissive here: weak {short_verdict(rw)}, strong {short_verdict(rs)}")
    elif rel.kind == SAME_ENDINGS:
        lines.append(head + f"no difference here (both see the same endings, strong {short_verdict(rs)})")
    elif rel.kind == WEAK_SEES_LESS:
        lines.append(head + f"weak sees fewer endings (weak {short_verdict(rw)}, strong {short_verdict(rs)}), "
                            "still no unique counterpart")
    else:
        lines.append(head + f"INCONSISTENT - {rel.problem}  (this is a bug)")
    if rel.only_strong:
        lines.append("    only strong sees (these histories repeat a state of A, so weak ignores them):")
        for w in rel.only_strong:
            lines.append(f"      {_ending(w.b_state)} via {fmt_word(w.word)}")
    if mode in ("explain", "explained") and rel.kind != INCONSISTENT:
        lines.append("    why: simple histories are histories, so weak sees a subset of the endings of strong;")
        lines.append("         fewer endings make a single one more likely: strong UNIQUE p => weak UNIQUE p,")
        lines.append("         but weak UNIQUE p does not imply strong UNIQUE p.")
    return "\n".join(lines)


def format_state_table(rows, policy, A_name="A", mode="short") -> str:
    """rows: [(q, strong Result|None, weak Result|None, Relation|None)] for all states of A."""
    cols = [(q, short_verdict(rs), short_verdict(rw), rel) for q, rs, rw, rel in rows]
    w0 = max(len("state"), *(len(c[0]) for c in cols))
    w1 = max(len("strong"), *(len(c[1]) for c in cols))
    w2 = max(len("weak"), *(len(c[2]) for c in cols))
    out = [f"all states of {A_name}, policy {policy}",
           f"  {'state':<{w0}} | {'strong':<{w1}} | {'weak':<{w2}} | note"]
    out.append("  " + "-" * (w0 + w1 + w2 + 12))
    n_s = n_w = 0
    for (q, vs, vw, rel), (_, rs, rw, _) in zip(cols, rows):
        n_s += rs.verdict == UNIQUE
        n_w += rw.verdict == UNIQUE
        note = {WEAK_ADDS: f"weak adds {rw.p}", INCONSISTENT: "INCONSISTENT (bug)"}.get(rel.kind, "")
        out.append(f"  {q:<{w0}} | {vs:<{w1}} | {vw:<{w2}} | {note}".rstrip())
    n = len(cols)
    bad = [c[0] for c in cols if c[3].kind == INCONSISTENT]
    out.append(f"  states with a unique counterpart: strong {n_s}/{n}, weak {n_w}/{n}"
               + ("   (every strong pair is also a weak pair)" if not bad else f"   INCONSISTENT at {bad}"))
    if mode in ("explain", "explained"):
        for q, rs, rw, rel in rows:
            if rel.kind == WEAK_ADDS:
                out.append(f"  {q}: weak adds {rw.p}; strong also sees (histories that repeat a state of A):")
                out += [f"      {_ending(w.b_state)} via {fmt_word(w.word)}" for w in rel.only_strong]
    return "\n".join(out)
