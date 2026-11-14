"""
Tests for state_mapper.  Run with:  python -m unittest -v

1. Every example from examples.py must match its expectation.
2. Random cross-check against brute force: enumerate all words up to a length
   bound, replay them, and compare with the product-based algorithm.
3. Small API / parsing checks.
"""
import itertools
import os
import random
import shutil
import tempfile
import unittest

from prev.complete_automata.build_gallery import build_markdown, compute_results
from prev.complete_automata.examples import CASES, PAIRS, evaluate
from prev.complete_automata.state_mapper import (DFA, Status, distinguishing_word, map_all,
                          map_state)
from prev.complete_automata.visualize import _a_above_b, render_png, to_dot


class ExampleTests(unittest.TestCase):
    def test_all_examples_match_expectations(self):
        for case in CASES:
            with self.subTest(case=case.id):
                _, problems = evaluate(case)
                self.assertEqual(problems, [])


def random_dfa(rng, n, alphabet, density):
    names = [f"q{i}" for i in range(n)]
    edges = [(a, s, rng.choice(names))
             for a in names for s in alphabet if rng.random() < density]
    return DFA("q0", edges, states=names)


def brute_force(old, new, q, max_len):
    """N(q) restricted to histories of length <= max_len (None = B stuck)."""
    found = set()
    alphabet = sorted(old.alphabet)
    for length in range(max_len + 1):
        for word in itertools.product(alphabet, repeat=length):
            if old.run(word) == q:
                found.add(new.run(word))
    return found


class RandomCrossCheck(unittest.TestCase):
    MAX_LEN = 8

    def check_pair(self, old, new):
        results = map_all(old, new)
        for q in old.states:
            res = map_state(old, q, new)
            brute = brute_force(old, new, q, self.MAX_LEN)

            # What the algorithm claims N(q) is (None = B stuck).
            claimed = set(res.candidates) | ({None} if res.stuck else set())

            # 1) Everything found by brute force must be found by the algorithm.
            self.assertTrue(brute <= claimed, (q, brute, claimed))
            # 2) Anything extra must only be reachable by a longer history.
            for item in claimed - brute:
                word = (res.stuck.history if item is None else res.candidates[item])
                self.assertGreater(len(word), self.MAX_LEN)
            # 3) Every witness really replays as claimed.
            for item, word in res.candidates.items():
                self.assertEqual(old.run(word), q)
                self.assertEqual(new.run(word), item)
            if res.stuck:
                self.assertEqual(old.run(res.stuck.history), q)
                self.assertIsNone(new.run(res.stuck.history))
                self.assertIsNone(new.run(res.stuck.history[:len(res.stuck.replayed) + 1]))
                self.assertIsNotNone(new.run(res.stuck.replayed))
            # 4) Status follows the criterion.
            if not claimed:
                self.assertIs(res.status, Status.UNREACHABLE)
                self.assertFalse(brute)
            elif len(res.candidates) >= 2:
                self.assertIs(res.status, Status.AMBIGUOUS)
            elif res.stuck:
                self.assertIs(res.status, Status.STUCK)
            else:
                self.assertIs(res.status, Status.UNIQUE)
                self.assertEqual(res.answer, next(iter(res.candidates)))
            # 5) The single-state and all-states variants agree.
            other = results[q]
            self.assertIs(other.status, res.status)
            self.assertEqual(set(other.candidates), set(res.candidates))
            for key in res.candidates:
                self.assertEqual(len(other.candidates[key]), len(res.candidates[key]))
            self.assertEqual(other.stuck is None, res.stuck is None)

    def test_random_automata(self):
        rng = random.Random(12345)
        for _ in range(400):
            alphabet = ["a", "b", "c"][: rng.choice([1, 2, 3])]
            old = random_dfa(rng, rng.randint(1, 5), alphabet, rng.choice([0.5, 0.7, 0.9]))
            new = random_dfa(rng, rng.randint(1, 5), alphabet, rng.choice([0.5, 0.7, 0.9]))
            self.check_pair(old, new)

    def test_identical_automata_are_always_unique(self):
        rng = random.Random(7)
        for _ in range(100):
            old = random_dfa(rng, rng.randint(1, 6), ["a", "b"], 0.8)
            for q, res in map_all(old, old).items():
                if res.status is not Status.UNREACHABLE:
                    self.assertIs(res.status, Status.UNIQUE)
                    self.assertEqual(res.answer, q)


class ApiTests(unittest.TestCase):
    def test_nondeterminism_is_rejected(self):
        with self.assertRaises(ValueError):
            DFA("s", [("s", "a", "x"), ("s", "a", "y")])

    def test_parse_text(self):
        dfa = DFA.from_text("start=s; s -a-> x\n x -b-c-> y")
        self.assertEqual(dfa.start, "s")
        self.assertEqual(dfa.run(["a", "b-c"]), "y")
        self.assertIsNone(dfa.run(["b-c"]))

    def test_unknown_state(self):
        old = DFA.from_text("s -a-> x")
        with self.assertRaises(ValueError):
            map_state(old, "nope", old)

    def test_lenient_only_helps_with_one_candidate(self):
        old = DFA.from_text("start=s; s -a-> x; s -b-> y; x -c-> q; y -c-> q")
        new = DFA.from_text("start=s; s -a-> x; x -c-> p")
        self.assertIs(map_state(old, "q", new).status, Status.STUCK)
        self.assertEqual(map_state(old, "q", new, lenient=True).answer, "p")
        # If B cannot replay anything, lenient mode does not invent an answer.
        empty = DFA.from_text("start=s; s -z-> t")
        self.assertIs(map_state(old, "q", empty, lenient=True).status, Status.STUCK)

    def test_distinguishing_word(self):
        dfa = DFA.from_text("start=a; a -x-> b; b -y-> c; d -x-> e; e -y-> f; f -z-> g")
        self.assertEqual(distinguishing_word(dfa, "a", "d"), ("x", "y", "z"))
        self.assertIsNone(distinguishing_word(dfa, "a", "a"))


class CatalogTests(unittest.TestCase):
    """The example catalogue itself must be consistent."""

    def test_ids_are_unique_and_every_case_has_a_reason(self):
        ids = [c.id for c in CASES]
        self.assertEqual(len(ids), len(set(ids)))
        for case in CASES:
            self.assertTrue(case.reason, case.id)

    def test_minimal_pairs_are_consistent_and_really_flip_the_answer(self):
        in_pairs = {cid for _, members in PAIRS.values() for cid in members}
        self.assertEqual(in_pairs, {c.id for c in CASES if c.pair})
        by_id = {c.id: c for c in CASES}
        for pid, (_, members) in PAIRS.items():
            self.assertGreaterEqual(len(members), 2, pid)
            for cid in members:
                self.assertEqual(by_id[cid].pair, pid)
            statuses = [by_id[cid].expect for cid in members]
            self.assertEqual(len(set(statuses)), len(statuses),
                             f"pair {pid}: members do not all give different statuses")

    def test_all_levels_and_all_statuses_are_covered(self):
        self.assertEqual({c.level for c in CASES},
                         {"very simple", "simple", "hard", "complete"})
        self.assertEqual({c.expect for c in CASES}, set(Status))

    def test_gallery_markdown_mentions_every_case(self):
        markdown = build_markdown(compute_results())   # needs no Graphviz
        for case in CASES:
            self.assertIn(f"#### {case.id}", markdown)
            self.assertIn(f"images/{case.id}.png", markdown)


class CompleteAutomataTests(unittest.TestCase):
    """Completely defined automata, trap states and error_states."""

    def test_complete_group_really_consists_of_complete_automata(self):
        group = [c for c in CASES if c.level == "complete"]
        self.assertGreaterEqual(len(group), 8)
        for case in group:
            old, new = DFA.from_text(case.old), DFA.from_text(case.new)
            sigma = old.alphabet | new.alphabet
            self.assertTrue(old.is_complete(sigma), case.id)
            self.assertTrue(new.is_complete(sigma), case.id)

    def test_completion_with_declared_sink_equals_the_partial_mapping(self):
        """Completing both automata and declaring B's sink as an error state must
        not change anything; without the declaration the sink shows up as a
        'candidate' exactly when the partial B would be stuck."""
        rng = random.Random(2024)
        for _ in range(300):
            alphabet = ["a", "b", "c"][: rng.choice([1, 2, 3])]
            old = random_dfa(rng, rng.randint(1, 5), alphabet, rng.choice([0.5, 0.7, 0.9]))
            new = random_dfa(rng, rng.randint(1, 5), alphabet, rng.choice([0.5, 0.7, 0.9]))
            sigma = sorted(old.alphabet | new.alphabet)
            old_c = old.completed(sigma, sink="#sinkA")
            new_c = new.completed(sigma, sink="#sinkB")
            errors = {"#sinkB"} & new_c.states
            for q in old.states:
                partial = map_state(old, q, new)
                declared = map_state(old_c, q, new_c, error_states=errors)
                self.assertIs(partial.status, declared.status)
                self.assertEqual(set(partial.candidates), set(declared.candidates))
                self.assertEqual(partial.stuck is None, declared.stuck is None)
                if partial.stuck is not None:
                    self.assertEqual(len(partial.stuck.history), len(declared.stuck.history))
                    self.assertEqual(declared.stuck.into_error, "#sinkB")
                undeclared = map_state(old_c, q, new_c)
                self.assertEqual("#sinkB" in undeclared.candidates, partial.stuck is not None)

    def test_completed_adds_an_absorbing_sink_only_when_needed(self):
        partial = DFA.from_text("start=s; s -a,b-> x; x -a-> x")
        self.assertFalse(partial.is_complete())
        full = partial.completed(sink="T")
        self.assertTrue(full.is_complete())
        self.assertTrue(full.is_absorbing("T"))
        self.assertEqual(full.completed(sink="T2").states, full.states)   # nothing missing
        with self.assertRaises(ValueError):
            partial.completed(sink="x")                                   # name clash

    def test_error_state_validation(self):
        old = DFA.from_text("start=s; s -a-> q")
        new = DFA.from_text("start=s; s -a-> t; t -a-> t")
        with self.assertRaises(ValueError):
            map_state(old, "q", new, error_states={"nope"})
        with self.assertRaises(ValueError):
            map_state(old, "q", new, error_states={"s"})                  # B's start state
        self.assertIs(map_state(old, "q", new, error_states={"t"}).status, Status.STUCK)
        self.assertIs(map_state(old, "q", new).status, Status.UNIQUE)

    def test_undeclared_trap_triggers_a_note_and_declared_trap_does_not(self):
        c4 = next(c for c in CASES if c.id == "C-04")
        c5 = next(c for c in CASES if c.id == "C-05")
        c6 = next(c for c in CASES if c.id == "C-06")
        def run(case):
            return map_state(DFA.from_text(case.old), case.current, DFA.from_text(case.new),
                             error_states=case.error_states)
        self.assertTrue(run(c4).notes)
        self.assertIn("error_states", "\n".join(run(c4).notes))
        self.assertFalse(run(c5).notes)
        self.assertFalse(run(c6).notes)          # absorbing in A too: a legitimate final state
        self.assertIn("error state", run(c5).explain())

    def test_distinguishing_word_respects_error_states(self):
        dfa = DFA.from_text("start=a; a -x-> b; b -x-> b; c -x-> trap; trap -x-> trap")
        self.assertIsNone(distinguishing_word(dfa, "a", "c"))
        self.assertEqual(distinguishing_word(dfa, "a", "c", frozenset({"trap"})), ("x",))

    def test_describe_roundtrip_and_comma_shorthand(self):
        dfa = DFA.from_text("start=s; s -a,b-> x; x -c-> s; x -a-> x")
        self.assertEqual(dfa.step("s", "a"), "x")
        self.assertEqual(dfa.step("s", "b"), "x")
        again = DFA.from_text("start=s; " + dfa.describe(indent="").replace("\n", "; "))
        for state in dfa.states:
            for symbol in dfa.alphabet:
                self.assertEqual(dfa.step(state, symbol), again.step(state, symbol))


class VisualizeTests(unittest.TestCase):
    @staticmethod
    def result_of(case):
        return map_state(DFA.from_text(case.old), case.current,
                         DFA.from_text(case.new), lenient=case.lenient)

    def test_dot_describes_both_automata_and_the_match(self):
        case = next(c for c in CASES if c.id == "L3-06")
        dot = to_dot(self.result_of(case), "demo title")
        for needle in ("cluster_old", "cluster_new", "(current)", "(match)",
                       "corresponds to", "demo title"):
            self.assertIn(needle, dot)

    def test_dot_marks_stuck_history(self):
        case = next(c for c in CASES if c.id == "L1-05")
        self.assertIn("B has no transition", to_dot(self.result_of(case)))

    @unittest.skipUnless(shutil.which("dot"), "Graphviz 'dot' is not installed")
    def test_png_for_every_example_with_old_automaton_on_top(self):
        with tempfile.TemporaryDirectory() as tmp:
            for case in CASES:
                with self.subTest(case=case.id):
                    result = self.result_of(case)
                    path = os.path.join(tmp, case.id + ".png")
                    render_png(result, path, case.title)
                    with open(path, "rb") as fh:
                        self.assertEqual(fh.read(8), b"\x89PNG\r\n\x1a\n")
                    self.assertTrue(_a_above_b(to_dot(result)))


if __name__ == "__main__":
    unittest.main()
