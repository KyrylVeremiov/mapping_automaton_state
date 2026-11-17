#!/usr/bin/env python3
"""Self-checks:  python tests/run_tests.py

1. file formats: every reader gives exactly the automaton it should (incl. accepting states,
   '*' / '!' labels, dialects, error cases);
2. algorithm: random automata, compared with brute-force enumeration of words, and the hybrid
   'simple' search compared with the full enumeration of simple histories;
3. relations of the definitions: strong UNIQUE p => simple UNIQUE p => p is a candidate of existence
   (never the other way round), O_simple <= O_strong, and simple allows more counterparts than strong
   (the tricky automata, both directions); existence = strong with "exists" instead of "for all";
4. environment: requirements are checked / installed (with mocks), Graphviz is found (also in the
   standard Windows folders);
5. pictures and command line: the table picture (3x2, 3x1, 1x2), file names, the default launch.
"""
from __future__ import annotations

import contextlib
import io
import itertools
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import environment as ENV                                      # noqa: E402
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
        r = M.analyze(A, B, q, M.SIMPLE, M.STRICT)
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
            if definition == M.SIMPLE:
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
            for d, p in itertools.product(M.DEFINITION_NAMES, (M.STRICT, M.LENIENT)):
                r = M.analyze(A, B, q, d, p)
                if r.verdict == M.UNREACHABLE:
                    check("unreachable", q not in M.reachable_words(A))
                    continue
                n += 1
                exp = brute(A, B, q, d, p, 4 if d == M.SIMPLE else 12)
                if d == M.EXISTENCE:       # candidates: the states some history leads to; "stuck" is no state
                    got, exp = M.candidate_set(r), exp - {None}
                else:
                    got = {w.b_state for w in r.witnesses}
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
                enum = M._simple_enumerate(A, B, q, p, 5_000_000)
                r = M.analyze(A, B, q, M.SIMPLE, p)
                got = {w.b_state: w.word for w in r.witnesses}
                n += 1
                check("hybrid vs enumeration", set(got) == set(enum[0]) and all(len(got[k]) == len(enum[0][k]) for k in got))
                for k, w in got.items():
                    ta, tb = M.run_word(A, w, p), M.run_word(B, w, p)
                    seq = [ta.start] + [s[2] for s in ta.steps]
                    check("witness is a simple history of q ending in k",
                          not ta.stuck and ta.end == q and len(set(seq)) == len(seq) and tb.end == k)
    print(f"  {n} hybrid-vs-enumeration comparisons")


# -------------------------------------------------- strong => simple (simple allows more counterparts)
def rand_aut_acc(prefix, n, sigma, rnd, p, acc_p):
    lines = [f"start: {prefix}0", "states: " + " ".join(f"{prefix}{i}" for i in range(n))]
    lines += [f"{prefix}{i} -{c}-> {prefix}{rnd.randrange(n)}" for i in range(n) for c in sigma if rnd.random() < p]
    acc = [f"{prefix}{i}" for i in range(n) if rnd.random() < acc_p]
    if acc:
        lines.append("accept: " + " ".join(acc))
    return parse_automaton("\n".join(lines), prefix)


def state_rows(old, new, pol):
    A, B = load_pair(old, new)
    return [(q, M.analyze(A, B, q, M.STRONG, pol), M.analyze(A, B, q, M.SIMPLE, pol),
             M.analyze(A, B, q, M.EXISTENCE, pol)) for q in A.states]


def corresponding(r):
    """C(q): the corresponding state of a result (a set with 0 or 1 element)."""
    return {r.p} if r.verdict == M.UNIQUE else set()


def test_relation():
    print("strong => simple => existence")
    from dataclasses import replace
    rnd, sigma = random.Random(23), ["a", "b", "c"]
    n = adds = r_adds = 0
    for _ in range(250):
        A = rand_aut_acc("s", rnd.randint(2, 7), sigma, rnd, .7, .6)
        B = rand_aut_acc("t", rnd.randint(2, 5), sigma, rnd, .7, .6)
        A.compile(sigma)
        B.compile(sigma)
        for q in A.states:
            for pol in (M.STRICT, M.LENIENT):
                rs, ri, rx = (M.analyze(A, B, q, d, pol) for d in M.DEFINITION_NAMES)
                rels = M.compare_all({(r.definition, pol): r for r in (rs, ri, rx)}, pol)
                n += 1
                check("all relations are consistent", all(r.kind != M.INCONSISTENT for r in rels),
                      "; ".join(r.problem for r in rels))
                check("O_simple is a subset of O_strong", M.outcome_set(ri) <= M.outcome_set(rs))
                if len(M.outcome_set(rs)) <= 1:
                    check("one ending in strong => simple says the same", rs.signature() == ri.signature())
                # the chain of the corresponding states: C_strong <= C_simple <= candidates of existence
                check("C_strong <= C_simple", corresponding(rs) <= corresponding(ri))
                check("C_simple <= candidates of existence", corresponding(ri) <= M.candidate_set(rx))
                check("simple's endings are candidates of existence", M.candidate_set(ri) <= M.candidate_set(rx))
                # existence is strong with "exists": the same states, the same answer unless strong says STUCK
                check("existence lists the states strong reaches", M.candidate_set(rx) == M.candidate_set(rs))
                if rs.verdict != M.STUCK:
                    check("strong (not STUCK) == existence", rs.signature() == rx.signature())
                if rs.verdict == M.UNIQUE:
                    check("strong UNIQUE p => simple UNIQUE p and existence UNIQUE p",
                          ri.verdict == M.UNIQUE == rx.verdict and ri.p == rx.p == rs.p)
                adds += any(r.kind == M.SIMPLE_ADDS for r in rels)
                r_adds += any(r.kind == M.EXISTENCE_ADDS for r in rels)
    print(f"  {n} state/policy triples; simple adds a counterpart in {adds}, existence lists more than simple in {r_adds}")
    check("random cases do contain 'simple adds' (the test is not vacuous)", adds > 0)
    check("random cases do contain 'existence adds' (the test is not vacuous)", r_adds > 0)

    # the tricky pair of the task, both directions, both policies
    ex = EX
    for pol in (M.STRICT, M.LENIENT):
        rows = state_rows(ex / "02_tricky_ambiguous/old.json", ex / "02_tricky_ambiguous/new.json", pol)
        check("tricky S->s: strong 2/5", sum(r[1].verdict == M.UNIQUE for r in rows) == 2)
        check("tricky S->s: simple 5/5", sum(r[2].verdict == M.UNIQUE for r in rows) == 5)
        added = {q: ri.p for q, rs, ri, rx in rows if rs.verdict != M.UNIQUE and ri.verdict == M.UNIQUE}
        check("tricky S->s: simple adds S0~s0, S1~s1, S2~s2", added == {"S0": "s0", "S1": "s1", "S2": "s2"}, str(added))
        cands = {q: sorted(M.candidate_set(rx)) for q, rs, ri, rx in rows}
        check("tricky S->s: existence lists the endings", cands == {"S0": ["e", "s0"], "S1": ["e", "s1"],
              "S2": ["e", "s2"], "S3": ["e"], "E": ["e"]}, str(cands))
        for q, rs, ri, rx in rows:      # the inclusions are proper: simple not in strong, existence not in simple
            if q in ("S0", "S1", "S2"):
                check("C_strong is empty, C_simple is not, existence has more", corresponding(rs) == set()
                      and len(corresponding(ri)) == 1 and M.candidate_set(rx) > corresponding(ri))
        rows = state_rows(ex / "03_tricky_unique/old.json", ex / "03_tricky_unique/new.json", pol)
        check("tricky s->S: strong 3/4, simple 4/4", sum(r[1].verdict == M.UNIQUE for r in rows) == 3
              and sum(r[2].verdict == M.UNIQUE for r in rows) == 4)
        added = {q: ri.p for q, rs, ri, rx in rows if rs.verdict != M.UNIQUE and ri.verdict == M.UNIQUE}
        check("tricky s->S: simple adds e~S3", added == {"e": "S3"}, str(added))
        for q, rs, ri, rx in rows:
            check("tricky: every strong pair is a simple pair", corresponding(rs) <= corresponding(ri))
            check("tricky: every simple pair is a existence candidate", corresponding(ri) <= M.candidate_set(rx))

    # existence is not "strong": a single candidate does not prove ~strong when B gets stuck on other histories
    A, B = load_pair(ex / "15_existence_ignores_stuck/old.json", ex / "15_existence_ignores_stuck/new.json")
    rs, ri, rx = (M.analyze(A, B, "s1", d, M.STRICT) for d in M.DEFINITION_NAMES)
    check("example 15: strong and simple STUCK, existence UNIQUE t1",
          (rs.verdict, ri.verdict, rx.verdict, rx.p) == (M.STUCK, M.STUCK, M.UNIQUE, "t1"))
    check("example 15: the ignored stuck history is reported", [w.word for w in rx.ignored_stuck] == [("b",)])

    # the checkers themselves must be able to fail: fake results that contradict the theory
    A, B = load_pair(ex / "01_c03_parity/old.json", ex / "01_c03_parity/new.json")
    rs, ri, rx = (M.analyze(A, B, "a1b1", d, M.STRICT) for d in M.DEFINITION_NAMES)
    fake = replace(ri, p="even", witnesses=[replace(w, b_state="even") for w in ri.witnesses])
    check("negative test: strong->simple contradiction is detected",
          M.compare_strong_simple(rs, fake).kind == M.INCONSISTENT)
    check("negative test: simple->existence contradiction is detected",
          M.compare_simple_existence(fake, rx).kind == M.INCONSISTENT)
    fake_r = replace(rx, witnesses=[])
    check("negative test: strong==existence violation is detected",
          M.compare_strong_existence(rs, fake_r).kind == M.INCONSISTENT)
    check("genuine pairs are accepted", M.compare_strong_simple(rs, ri).kind == M.AGREE
          and M.compare_simple_existence(ri, rx).kind == M.SAME_CANDIDATES)

    # the same with SEVERAL endings in strong (example 02: strong sees s2 and e), so that the
    # "subset" guards - and not the "one ending" guards - are the ones that must fire
    A, B = load_pair(ex / "02_tricky_ambiguous/old.json", ex / "02_tricky_ambiguous/new.json")
    rs, ri, rx = (M.analyze(A, B, "S2", d, M.STRICT) for d in M.DEFINITION_NAMES)
    check("example 02: genuine pairs", M.compare_strong_simple(rs, ri).kind == M.SIMPLE_ADDS
          and M.compare_simple_existence(ri, rx).kind == M.EXISTENCE_ADDS)
    alien = replace(ri, p="zzz", witnesses=[replace(w, b_state="zzz") for w in ri.witnesses])
    rel = M.compare_strong_simple(rs, alien)
    check("negative test: a simple ending that strong does not see is detected",
          rel.kind == M.INCONSISTENT and "zzz" in rel.problem, rel.problem)
    no_s2 = replace(rx, witnesses=[w for w in rx.witnesses if w.b_state != "s2"])
    rel = M.compare_simple_existence(ri, no_s2)
    check("negative test: a simple ending missing among the existence candidates is detected",
          rel.kind == M.INCONSISTENT and "s2" in rel.problem, rel.problem)


# ---------------------------------------------------------------- environment
def quiet():
    msgs = []
    return msgs, msgs.append


def test_environment():
    print("environment")
    reqs = ENV.parse_requirements("# c\nPillow>=9.0.0   # why\n\n-r other.txt\nsix == 1.16\nnumpy\n")
    check("parse_requirements", [(r.name, r.op, r.version) for r in reqs]
          == [("Pillow", ">=", "9.0.0"), ("six", "==", "1.16"), ("numpy", "", "")], str(reqs))

    real = ENV.installed_version
    try:
        for have, spec, expect in (("13.0.0", "Pillow>=9.0.0", True), ("8.4.0", "Pillow>=9.0.0", False),
                                   ("9.0", "Pillow>=9.0.0", True), ("1.16.0", "six==1.16", True),
                                   ("1.17.0", "six==1.16", False), ("2.0", "x<3", True), ("3.0", "x<3", False),
                                   ("10.0", "x>=9.2", True)):
            ENV.installed_version = lambda name, have=have: have
            check(f"satisfied({have} vs {spec})", ENV.satisfied(ENV.parse_requirements(spec)[0]) is expect)
        ENV.installed_version = lambda name: None
        check("not installed -> not satisfied", not ENV.satisfied(ENV.parse_requirements("Pillow>=9")[0]))
    finally:
        ENV.installed_version = real

    work = Path(tempfile.mkdtemp())
    req = work / "requirements.txt"
    req.write_text("Pillow>=9.0.0\n", encoding="utf-8")
    vendor = work / ".vendor"

    # everything installed: nothing is run
    calls = []
    msgs, out = quiet()
    ok = ENV.ensure_requirements(req, runner=lambda cmd: calls.append(cmd) or True, check=lambda r: True,
                                 out=out, vendor=vendor)
    check("all satisfied: True, no pip, no output", ok is True and not calls and not msgs, str((ok, calls, msgs)))

    # missing, normal installation works
    state = {"installed": False}
    calls = []

    def runner_ok(cmd):
        calls.append(cmd)
        state["installed"] = True
        return True
    msgs, out = quiet()
    ok = ENV.ensure_requirements(req, runner=runner_ok, check=lambda r: state["installed"], out=out, vendor=vendor)
    check("missing -> pip install", ok is True and len(calls) == 1 and "install" in calls[0]
          and "Pillow>=9.0.0" in calls[0] and "--target" not in calls[0], str(calls))

    # normal installation fails (e.g. externally managed Python) -> fallback into .vendor
    state, calls = {"installed": False}, []

    def runner_fallback(cmd):
        calls.append(cmd)
        if "--target" in cmd:
            state["installed"] = True
            return True
        return False
    msgs, out = quiet()
    ok = ENV.ensure_requirements(req, runner=runner_fallback, check=lambda r: state["installed"], out=out, vendor=vendor)
    check("normal install fails -> --target .vendor", ok is True and len(calls) == 2 and "--target" in calls[1]
          and str(vendor) in calls[1], str(calls))
    state, calls = {"installed": False}, []
    ok = ENV.ensure_requirements(req, runner=runner_fallback, check=lambda r: state["installed"], out=quiet()[1],
                                 vendor=vendor, force_target=True)
    check("force_target goes straight to --target", ok and len(calls) == 1 and "--target" in calls[0])

    # nothing works: no exception, a clear message, False
    msgs, out = quiet()
    ok = ENV.ensure_requirements(req, runner=lambda cmd: False, check=lambda r: False, out=out, vendor=vendor)
    check("installation impossible -> False and a hint", ok is False and any("pip install -r" in m for m in msgs)
          and any("Pillow" in m for m in msgs), str(msgs))

    # switched off (argument and environment variable)
    calls = []
    msgs, out = quiet()
    ok = ENV.ensure_requirements(req, skip=True, runner=lambda cmd: calls.append(cmd) or True, check=lambda r: False,
                                 out=out, vendor=vendor)
    check("skip=True: nothing installed", ok is False and not calls and any("off" in m for m in msgs), str(msgs))
    old_env = os.environ.get(ENV.SKIP_ENV)
    os.environ[ENV.SKIP_ENV] = "1"
    try:
        ok = ENV.ensure_requirements(req, runner=lambda cmd: calls.append(cmd) or True, check=lambda r: False,
                                     out=quiet()[1], vendor=vendor)
        check(f"{ENV.SKIP_ENV}=1: nothing installed", ok is False and not calls)
    finally:
        if old_env is None:
            del os.environ[ENV.SKIP_ENV]
        else:
            os.environ[ENV.SKIP_ENV] = old_env
    msgs, out = quiet()
    check("missing requirements file is not fatal", ENV.ensure_requirements(work / "none.txt", out=out) is True
          and any("not found" in m for m in msgs))
    check("the project's requirements.txt lists Pillow",
          any(r.name.lower() == "pillow" for r in ENV.parse_requirements(ENV.REQUIREMENTS.read_text())))

    # Graphviz: a fake "standard Windows installation" in a temporary folder
    pf = work / "Program Files"
    pf86 = work / "Program Files (x86)"
    for folder in (pf / "Graphviz 2.38" / "bin", pf / "Graphviz" / "bin", pf86 / "Graphviz2.38" / "bin"):
        folder.mkdir(parents=True)
        (folder / "dot.exe").write_text("")
    env = {"ProgramFiles": str(pf), "ProgramFiles(x86)": str(pf86)}
    nowhere = lambda name: None                                              # "dot" is not on the PATH
    found = ENV.find_dot(env, "win32", nowhere)
    check("Windows: found in Program Files\\Graphviz\\bin (the unversioned folder wins)",
          found == str(pf / "Graphviz" / "bin" / "dot.exe"), str(found))
    (pf / "Graphviz" / "bin" / "dot.exe").unlink()
    found = ENV.find_dot(env, "win32", nowhere)
    check("Windows: otherwise a versioned folder", found == str(pf / "Graphviz 2.38" / "bin" / "dot.exe"), str(found))
    (pf / "Graphviz 2.38" / "bin" / "dot.exe").unlink()
    found = ENV.find_dot(env, "win32", nowhere)
    check("Windows: Program Files (x86) as well", found == str(pf86 / "Graphviz2.38" / "bin" / "dot.exe"), str(found))
    nothing = ENV.find_dot({"ProgramFiles": str(work / "empty")}, "win32", nowhere)
    # on a real Windows machine the literal default folders (C:\\Program Files ...) may really exist
    check("Windows: nothing installed -> None", nothing is None or sys.platform.startswith("win"), str(nothing))
    local = work / "Local"
    (local / "Programs" / "Graphviz" / "bin").mkdir(parents=True)
    (local / "Programs" / "Graphviz" / "bin" / "dot.exe").write_text("")
    found = ENV.find_dot({"LOCALAPPDATA": str(local)}, "win32", nowhere)
    check("Windows: per-user installation (LOCALAPPDATA\\Programs)",
          found == str(local / "Programs" / "Graphviz" / "bin" / "dot.exe"), str(found))
    check("PATH wins over the standard folders", ENV.find_dot(env, "win32", lambda name: "C:/tools/dot.exe")
          == "C:/tools/dot.exe")
    explicit = work / "my_dot.exe"
    explicit.write_text("")
    check("GRAPHVIZ_DOT wins over everything", ENV.find_dot(dict(env, GRAPHVIZ_DOT=str(explicit)), "win32",
                                                            lambda name: "C:/tools/dot.exe") == str(explicit))
    check("GRAPHVIZ_DOT pointing nowhere is ignored", ENV.find_dot(dict(env, GRAPHVIZ_DOT=str(work / "no")),
                                                                   "win32", lambda name: "x/dot") == "x/dot")
    hints = {pf_: ENV.install_hint(pf_) for pf_ in ("win32", "darwin", "linux")}
    check("install hints", "winget" in hints["win32"] and "graphviz.org" in hints["win32"]
          and "brew install graphviz" in hints["darwin"] and "apt install graphviz" in hints["linux"]
          and ENV.DOT_ENV in hints["linux"])
    check("dot_environment puts the folder of dot first on the PATH",
          ENV.dot_environment(str(explicit))["PATH"].split(os.pathsep)[0] == str(work))


# ------------------------------------------------- pictures and the command line
def pictures_available():
    if ENV.find_dot() is None:
        return "Graphviz (dot) is not installed"
    try:
        import PIL                                                  # noqa: F401
    except ImportError:
        return "Pillow is not installed"
    return ""


def test_pictures():
    print("pictures and command line")
    import argparse
    import map_state as MS
    import visualize as V
    check("parse_pictures", MS.parse_pictures("all") == ("separate", "combined", "grid")
          and MS.parse_pictures("grid") == ("grid",) and MS.parse_pictures("grid,separate") == ("separate", "grid"))
    try:
        MS.parse_pictures("both")
        check("parse_pictures rejects unknown kinds", False)
    except argparse.ArgumentTypeError:
        pass
    for old_name in ("weak", "strong_and_weak", "reverse"):
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                MS.main(["a", "b", "c", "--definition", old_name])
                check(f"'{old_name}' is not accepted any more", False)
            except SystemExit as e:
                check(f"'{old_name}' is not accepted any more", e.code == 2)

    # geometry of the table picture, computed by hand:  x0 = 10 + 50 + 5 = 65, y0 = 10 + 40 + 5 + 30 + 5 = 90
    xs, ys, w, h = V.grid_layout([100, 200, 150], [80, 90], left=50, head_h=40, top=30, margin=10, gap=5)
    check("grid_layout", (xs, ys, w, h) == ([65, 170, 375], [90, 175], 535, 275), str((xs, ys, w, h)))
    xs, ys, w, h = V.grid_layout([100], [80], left=0, head_h=0, top=0, margin=10, gap=5)
    check("grid_layout without captions", (xs, ys, w, h) == ([10], [10], 120, 100), str((xs, ys, w, h)))

    # run_examples.py has the same defaults as map_state.py: all 6 modes, explained (here without pictures)
    proc = subprocess.run([sys.executable, str(ROOT / "run_examples.py"), "15", "--no-visualize"],
                          capture_output=True, text=True, cwd=str(ROOT))
    headers = [f"--- {df} / {po} " for df in M.DEFINITION_NAMES for po in ("strict", "lenient")]
    check("run_examples default: exit code 0", proc.returncode == 0, proc.stderr[-300:])
    check("run_examples default: all 6 modes, in explain mode", all(h in proc.stdout for h in headers)
          and "Step 4." in proc.stdout)
    check("run_examples default: all 6 combinations are checked against 'expect'",
          "1 example(s) run; 6/6 checks" in proc.stdout, proc.stdout[-200:])

    why = pictures_available()
    if why:
        print(f"  (picture tests skipped: {why})")
        return
    from PIL import Image
    ex = EX / "02_tricky_ambiguous"
    A, B = load_pair(ex / "old.json", ex / "new.json")
    work = Path(tempfile.mkdtemp())
    real = V._dot_bytes
    for defs, pols, cells, calls in (((M.STRONG, M.SIMPLE, M.EXISTENCE), (M.STRICT, M.LENIENT), 6, 12),   # 3x2
                                     ((M.STRONG, M.SIMPLE, M.EXISTENCE), (M.STRICT,), 3, 8),            # 3x1
                                     ((M.EXISTENCE,), (M.STRICT, M.LENIENT), 2, 6)):                   # 1x2
        results = [(d, p, M.analyze(A, B, "S2", d, p)) for d in defs for p in pols]
        counter = []
        V._dot_bytes = lambda *a, _c=counter, **k: _c.append(1) or real(*a, **k)
        try:
            out = V.render_grid(A, B, results, work / f"grid_{len(defs)}x{len(pols)}.png")
        finally:
            V._dot_bytes = real
        img = Image.open(out)
        check(f"grid {len(defs)}x{len(pols)}: {cells} cell pictures + captions",
              len(counter) == calls, f"{len(counter)} dot runs, expected {calls}")
        check(f"grid {len(defs)}x{len(pols)}: a real picture", img.width > 800 and img.height > 400, str(img.size))
    big = Image.open(work / "grid_3x2.png").size
    check("3x2 is wider than 1x2 and taller than 3x1", big[0] > Image.open(work / "grid_1x2.png").size[0]
          and big[1] > Image.open(work / "grid_3x1.png").size[1])

    # file names and the choice of pictures
    def made(**kw):
        d = Path(tempfile.mkdtemp())
        MS.solve(ex / "old.json", ex / "new.json", "S2", images_dir=d, label="x", out=lambda *a: None, **kw)
        return sorted(f.name for f in d.iterdir())
    allp = made(definition="all", policy="all")
    check("all/all: 6 separate + __all.png + __grid.png", allp == sorted(
        [f"x__{d}_{p}.png" for d in M.DEFINITION_NAMES for p in ("strict", "lenient")] + ["x__all.png", "x__grid.png"]),
          str(allp))
    check("all/strict: grid_all_strict and combined_all_strict", made(definition="all", policy="strict", picture="grid,combined")
          == ["x__combined_all_strict.png", "x__grid_all_strict.png"])
    check("picture=grid: only the table", made(definition="all", policy="all", picture="grid") == ["x__grid.png"])
    check("one mode: only its own picture", made(definition="existence", policy="strict") == ["x__existence_strict.png"])
    check("--no-visualize: no pictures", made(definition="all", policy="all", visualize_=False) == [])

    # the default launch of the task:  python map_state.py old.json new.json current_state_in_old
    d = Path(tempfile.mkdtemp())
    proc = subprocess.run([sys.executable, str(ROOT / "map_state.py"), str(ex / "old.json"), str(ex / "new.json"),
                           "S2", "--images-dir", str(d)], capture_output=True, text=True, cwd=str(ROOT))
    headers = [f"--- {df} / {po} " for df in M.DEFINITION_NAMES for po in ("strict", "lenient")]
    check("default launch: exit code 0", proc.returncode == 0, proc.stderr[-300:])
    check("default launch: all 6 modes, in explain mode", all(h in proc.stdout for h in headers)
          and "Step 4." in proc.stdout)
    check("default launch: relation blocks", "relation strong -> simple" in proc.stdout
          and "relation simple -> existence" in proc.stdout)
    check("default launch: 6 + 2 pictures", len(list(d.iterdir())) == 8, str(sorted(f.name for f in d.iterdir())))
    d = Path(tempfile.mkdtemp())
    proc = subprocess.run([sys.executable, str(ROOT / "run_examples.py"), "15", "--images-dir", str(d)],
                          capture_output=True, text=True, cwd=str(ROOT))
    check("run_examples default: 6 + 2 pictures", proc.returncode == 0 and len(list(d.iterdir())) == 8,
          str(sorted(f.name for f in d.iterdir())) + proc.stderr[-200:])


GROUPS = {"formats": test_formats, "algorithm": test_algorithm, "relation": test_relation,
          "environment": test_environment, "pictures": test_pictures}


if __name__ == "__main__":
    names = sys.argv[1:] or list(GROUPS)            # e.g.  python tests/run_tests.py environment pictures
    unknown = [n for n in names if n not in GROUPS]
    if unknown:
        sys.exit(f"unknown test group(s) {unknown}; choose from {', '.join(GROUPS)}")
    for name in names:
        GROUPS[name]()
    print("ALL TESTS PASSED" if not failures else f"{len(failures)} FAILURE(S): {failures[:5]}")
    sys.exit(1 if failures else 0)
