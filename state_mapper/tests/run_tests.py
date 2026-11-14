#!/usr/bin/env python3
"""Self-checks:  python tests/run_tests.py

1. file formats: every reader gives exactly the automaton it should (incl. accepting states,
   '*' / '!' labels, dialects, error cases);
2. algorithm: random automata, compared with brute-force enumeration of words, and the hybrid
   'weak' search compared with the full enumeration of simple histories;
3. relation of the definitions: strong UNIQUE p => weak UNIQUE p, O_weak <= O_strong, and weak allows
   more counterparts (the tricky automata, both directions).
"""
from __future__ import annotations

import itertools
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mapping as M                                            # noqa: E402
from automaton import AutomatonError, load_automaton, load_pair, parse_automaton   # noqa: E402

EX = ROOT / "examples"
failures = []


def check(name, cond, detail=""):
    if not cond:
        failures.append(name)
        print(f"  FAIL  {name} {detail}")


def table(path, sigma=None, fmt="auto"):
    a = load_automaton(path, fmt)
    a.compile(sigma or sorted(a.letters()))
    return a.start, dict(a.delta), (a.accepting if a.explicit_accepting else None)


def tmp(text, suffix):
    f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return f.name


# ------------------------------------------------------------------ formats
def test_formats():
    print("formats")
    # same automata, different notations
    s_nat, d_nat, _ = table(EX / "01_c03_parity/old.json")
    s_jff, d_jff, acc = table(EX / "13_jflap_and_dot/old.jff")
    check("jff == json (start, transitions)", (s_nat, d_nat) == (s_jff, d_jff))
    check("jff: accepting states are read", acc == {"a1b1"}, str(acc))
    s_nat, d_nat, _ = table(EX / "01_c03_parity/new.json")
    s_dot, d_dot, acc = table(EX / "13_jflap_and_dot/new.dot")
    check("dot == json (start, transitions)", (s_nat, d_nat) == (s_dot, d_dot))
    check("dot: doublecircle = accepting", acc == {"odd"}, str(acc))
    st, d, _ = table(EX / "02_tricky_ambiguous/old.json")        # the uploaded tricky2.json
    check("json (list of triples): tricky2", st == "S0" and len(d) == 9 and d[("S3", "a")] == "E"
          and d[("S2", "b")] == "S0" and d[("E", "b")] == "E", str(len(d)))
    st, d, _ = table(EX / "03_tricky_unique/old.json")           # the uploaded tricky1.json
    check("json (list of triples): tricky1", st == "s0" and len(d) == 7 and d[("s2", "a")] == "e", str(len(d)))
    st, d, _ = table(EX / "06_wildcard_equivalent/old.aut", ["a", "b", "c"])
    check("native '!' and '*'", d[("wait", "b")] == "wait" and d[("wait", "a")] == "seen" and d[("seen", "c")] == "seen")
    st, d, _ = table(EX / "07_wildcard_ambiguous/old.json", ["a", "b", "c"])
    check("json '!' and '*'", d[("s0", "c")] == "s0" and d[("s0", "a")] == "s1" and d[("s1", "b")] == "s1")
    st, d, _ = table(EX / "04_stuck_vs_skip/old.dot")
    check("dot example 04", st == "s0" and d[("s1", "b")] == "s2")
    st, d, _ = table(EX / "05_unreachable/old.jff")
    check("jff example 05", st == "s0" and ("x", "a") in d)
    st, d, _ = table(EX / "08_lenient_ambiguous/old.fsm")
    check("fsm (att) example 08", st == "0" and d[("0", "a")] == "1", str((st, d)))
    s_att, d_att, acc = table(EX / "14_att_and_json_dict/old.att")
    check("att: start, final state", s_att == "0" and acc == {"3"} and d_att[("0", "a")] == "1", str(acc))
    s_js, d_js, acc = table(EX / "14_att_and_json_dict/new.json")
    check("json dict dialect", s_js == "t0" and acc == {"t3", "t4"} and d_js[("t2", "c")] == "t4", str(acc))

    # dialects and wildcard labels
    p = tmp('{"initial":"p","accepting":["q"],"transitions":[{"from":"p","symbol":"a","to":"q"},'
            '{"from":"p","symbol":"!a","to":"p"},{"from":"q","symbol":"*","to":"q"}],"alphabet":["a","b","c"]}', ".json")
    st, d, acc = table(p)
    check("json objects + '!' + '*'", d[("p", "b")] == "p" and d[("p", "a")] == "q" and d[("q", "c")] == "q" and acc == {"q"})
    p = tmp('digraph { rankdir=LR; node [shape=doublecircle]; "q 2"; node [shape=circle]; '
            'init [label="" shape=none]; init -> "q 0"; "q 0" -> "q 1" [label="a, b"]; '
            '"q 1" -> "q 2" [label="*"]; "q 2" -> "q 0" [label="!a"] }', ".gv")
    st, d, acc = table(p, ["a", "b", "c"])
    check("dot: quoted ids, shape defaults, labels", st == "q 0" and acc == {"q 2"} and d[("q 0", "b")] == "q 1"
          and d[("q 1", "c")] == "q 2" and d[("q 2", "b")] == "q 0" and ("q 2", "a") not in d, str((st, acc)))
    p = tmp('<structure><type>fa</type><automaton><state id="0"><initial/></state><state id="1"><final/></state>'
            '<transition><from>0</from><to>1</to><read>x</read></transition></automaton></structure>', ".jff")
    st, d, acc = table(p)
    check("jff without state names", st == "q0" and acc == {"q1"} and d[("q0", "x")] == "q1", str((st, acc)))
    # no accepting state marked => all accepting (explicit_accepting is False)
    p = tmp('{"start":"s","transitions":[["s","a","t"]]}', ".json")
    check("no accepting marked => undeclared", table(p)[2] is None)
    # sniffing without extension
    for text, expect in (('{"start":"s","transitions":[["s","a","t"]]}', "json"),
                         ("digraph{ i [shape=point]; i->s; s->t [label=a] }", "dot"),
                         ("start: s\ns -a-> t\n", "aut"), ("0 1 a\n1 2 b\n2\n", "att")):
        a = load_automaton(tmp(text, ".dat"))
        check(f"auto-detect {expect}", a.start in ("s", "0") and len(a.raw) >= 1)

    # errors
    for name, text, suffix in (("json epsilon", '{"start":"s","transitions":[["s","","t"]]}', ".json"),
                               ("json no start", '{"transitions":[["s","a","t"]]}', ".json"),
                               ("json broken", '{"start": ', ".json"),
                               ("att epsilon", "0 1 <eps>\n", ".att"),
                               ("dot no start", "digraph{ a -> b [label=x] }", ".dot"),
                               ("jff epsilon", '<structure><automaton><state id="0"><initial/></state>'
                                '<transition><from>0</from><to>0</to><read/></transition></automaton></structure>', ".jff"),
                               ("nondeterministic", "start: s\ns -a-> t\ns -a-> u\n", ".aut")):
        try:
            a = load_automaton(tmp(text, suffix))
            a.compile(sorted(a.letters()) or ["a"])
            check(f"error: {name}", False, "no error raised")
        except AutomatonError:
            pass
    try:
        load_automaton(EX / "01_c03_parity/old.json", "xml")
        check("error: unknown --format", False)
    except AutomatonError:
        pass

    # accepting states of non-native formats really influence the answer (mutated copies)
    for src, dst, old, new, q in (("13_jflap_and_dot/new.dot", "odd [shape=doublecircle]", "old.jff", "new.dot", "a1b1"),):
        d = Path(tempfile.mkdtemp())
        (d / "old.jff").write_text((EX / "13_jflap_and_dot/old.jff").read_text())
        (d / "new.dot").write_text((EX / src).read_text().replace(dst, "odd [shape=circle]; even [shape=doublecircle]"))
        A, B = load_pair(d / "old.jff", d / "new.dot")
        r = M.analyze(A, B, q, M.WEAK, M.STRICT)
        check("dot: non-accepting p => NO_MATCH", r.verdict == M.NO_MATCH, r.verdict)
    A, B = load_pair(EX / "13_jflap_and_dot/old.jff", EX / "13_jflap_and_dot/new.dot")
    check("jff: non-accepting q => NO_MATCH", M.analyze(A, B, "a0b1", M.STRONG, M.STRICT).verdict == M.NO_MATCH)


# --------------------------------------------------------------- algorithm
def rand_aut(prefix, n, sigma, rnd, p):
    lines = [f"start: {prefix}0", "states: " + " ".join(f"{prefix}{i}" for i in range(n))]
    lines += [f"{prefix}{i} -{c}-> {prefix}{rnd.randrange(n)}" for i in range(n) for c in sigma if rnd.random() < p]
    return parse_automaton("\n".join(lines), prefix)


def brute(A, B, q, definition, policy, maxlen):
    outs = set()
    for L in range(maxlen + 1):
        for w in itertools.product(A.sigma, repeat=L):
            ta = M.run_word(A, w, policy)
            if ta.stuck or ta.end != q:
                continue
            if definition == M.WEAK:
                seq = [ta.start] + [s[2] for s in ta.steps]
                if len(set(seq)) != len(seq):
                    continue
            outs.add(M.run_word(B, w, policy).end)
    return outs


def test_algorithm():
    print("algorithm")
    rnd, sigma = random.Random(7), ["a", "b"]
    n = bad = 0
    for _ in range(150):
        A, B = rand_aut("s", rnd.randint(1, 3), sigma, rnd, .75), rand_aut("t", rnd.randint(1, 3), sigma, rnd, .75)
        A.compile(sigma)
        B.compile(sigma)
        for q in A.states:
            for d, p in itertools.product((M.STRONG, M.WEAK), (M.STRICT, M.LENIENT)):
                r = M.analyze(A, B, q, d, p)
                if r.verdict == M.UNREACHABLE:
                    check("unreachable", q not in M.reachable_words(A))
                    continue
                n += 1
                got = {w.b_state for w in r.witnesses}
                exp = brute(A, B, q, d, p, 12 if d == M.STRONG else 4)
                if got != exp:
                    bad += 1
                    check("brute force", False, f"{q} {d} {p} {got} {exp}")
    print(f"  {n} brute-force comparisons")

    rnd, sigma, n = random.Random(11), ["a", "b", "c"], 0
    for _ in range(150):
        A, B = rand_aut("s", rnd.randint(4, 8), sigma, rnd, .7), rand_aut("t", rnd.randint(2, 6), sigma, rnd, .7)
        A.compile(sigma)
        B.compile(sigma)
        for q in A.states:
            for p in (M.STRICT, M.LENIENT):
                if q not in M.reachable_words(A):
                    continue
                enum = M._weak_enumerate(A, B, q, p, 5_000_000)
                r = M.analyze(A, B, q, M.WEAK, p)
                got = {w.b_state: w.word for w in r.witnesses}
                n += 1
                check("hybrid vs enumeration", set(got) == set(enum[0]) and all(len(got[k]) == len(enum[0][k]) for k in got))
                for k, w in got.items():
                    ta, tb = M.run_word(A, w, p), M.run_word(B, w, p)
                    seq = [ta.start] + [s[2] for s in ta.steps]
                    check("witness is a simple history of q ending in k",
                          not ta.stuck and ta.end == q and len(set(seq)) == len(seq) and tb.end == k)
    print(f"  {n} hybrid-vs-enumeration comparisons")


# -------------------------------------------------- strong => weak (weak allows more counterparts)
def rand_aut_acc(prefix, n, sigma, rnd, p, acc_p):
    lines = [f"start: {prefix}0", "states: " + " ".join(f"{prefix}{i}" for i in range(n))]
    lines += [f"{prefix}{i} -{c}-> {prefix}{rnd.randrange(n)}" for i in range(n) for c in sigma if rnd.random() < p]
    acc = [f"{prefix}{i}" for i in range(n) if rnd.random() < acc_p]
    if acc:
        lines.append("accept: " + " ".join(acc))
    return parse_automaton("\n".join(lines), prefix)


def state_rows(old, new, pol):
    A, B = load_pair(old, new)
    return [(q, M.analyze(A, B, q, M.STRONG, pol), M.analyze(A, B, q, M.WEAK, pol)) for q in A.states]


def test_relation():
    print("strong => weak")
    from dataclasses import replace
    rnd, sigma = random.Random(23), ["a", "b", "c"]
    n = adds = 0
    for _ in range(250):
        A = rand_aut_acc("s", rnd.randint(2, 7), sigma, rnd, .7, .6)
        B = rand_aut_acc("t", rnd.randint(2, 5), sigma, rnd, .7, .6)
        A.compile(sigma)
        B.compile(sigma)
        for q in A.states:
            for pol in (M.STRICT, M.LENIENT):
                rs, rw = M.analyze(A, B, q, M.STRONG, pol), M.analyze(A, B, q, M.WEAK, pol)
                rel = M.compare_definitions(rs, rw)
                n += 1
                check("relation is consistent", rel.kind != M.INCONSISTENT, rel.problem)
                check("O_weak is a subset of O_strong", M.outcome_set(rw) <= M.outcome_set(rs))
                if rs.verdict == M.UNIQUE:
                    check("strong UNIQUE p => weak UNIQUE p", rw.verdict == M.UNIQUE and rw.p == rs.p)
                if len(M.outcome_set(rs)) <= 1:
                    check("one ending in strong => weak says the same", rs.signature() == rw.signature())
                adds += rel.kind == M.WEAK_ADDS
    print(f"  {n} state/policy pairs; weak adds a counterpart in {adds} of them")
    check("random cases do contain 'weak adds' (the test is not vacuous)", adds > 0)

    # the tricky pair of the task, both directions, both policies
    ex = EX
    for pol in (M.STRICT, M.LENIENT):
        rows = state_rows(ex / "02_tricky_ambiguous/old.json", ex / "02_tricky_ambiguous/new.json", pol)
        check("tricky S->s: strong 2/5", sum(r[1].verdict == M.UNIQUE for r in rows) == 2)
        check("tricky S->s: weak 5/5", sum(r[2].verdict == M.UNIQUE for r in rows) == 5)
        added = {q: rw.p for q, rs, rw in rows if rs.verdict != M.UNIQUE and rw.verdict == M.UNIQUE}
        check("tricky S->s: weak adds S0~s0, S1~s1, S2~s2", added == {"S0": "s0", "S1": "s1", "S2": "s2"}, str(added))
        rows = state_rows(ex / "03_tricky_unique/old.json", ex / "03_tricky_unique/new.json", pol)
        check("tricky s->S: strong 3/4, weak 4/4", sum(r[1].verdict == M.UNIQUE for r in rows) == 3
              and sum(r[2].verdict == M.UNIQUE for r in rows) == 4)
        added = {q: rw.p for q, rs, rw in rows if rs.verdict != M.UNIQUE and rw.verdict == M.UNIQUE}
        check("tricky s->S: weak adds e~S3", added == {"e": "S3"}, str(added))
        for q, rs, rw in rows:
            if rs.verdict == M.UNIQUE:
                check("tricky: every strong pair is a weak pair", rw.verdict == M.UNIQUE and rw.p == rs.p)

    # the checker itself must be able to fail: fake a weak result that contradicts the strong one
    A, B = load_pair(ex / "01_c03_parity/old.json", ex / "01_c03_parity/new.json")
    rs, rw = M.analyze(A, B, "a1b1", M.STRONG, M.STRICT), M.analyze(A, B, "a1b1", M.WEAK, M.STRICT)
    fake = replace(rw, p="even", witnesses=[replace(w, b_state="even") for w in rw.witnesses])
    check("negative test: contradiction is detected", M.compare_definitions(rs, fake).kind == M.INCONSISTENT)
    check("negative test: genuine pair is accepted", M.compare_definitions(rs, rw).kind == M.AGREE)


if __name__ == "__main__":
    test_formats()
    test_algorithm()
    test_relation()
    print("ALL TESTS PASSED" if not failures else f"{len(failures)} FAILURE(S): {failures[:5]}")
    sys.exit(1 if failures else 0)
