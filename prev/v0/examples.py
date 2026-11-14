#!/usr/bin/env python3
"""
Example cases for state_mapper: 7 "very simple", 7 "simple", 7 "hard".

Every case has: old automaton A, current state q of A, new automaton B, the
expected outcome, and a short "why" that explains the program output.

Usage:
    python examples.py                  run all cases, print output + explanation
    python examples.py --level simple   only one level: "very simple" | "simple" | "hard"
    python examples.py --id L2-02       only one case
    python examples.py --list           one line per case
Exit code is 0 if every case matches its expectation.

Automata are written as text: 'start=s; s -a-> x; x -b-> q'
(each item is either start=NAME or  SOURCE -EVENT-> TARGET).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

from v1.state_mapper import DFA, MappingResult, Status, format_table, map_all, map_state

VERY_SIMPLE, SIMPLE, HARD = "very simple", "simple", "hard"


@dataclass
class Case:
    id: str
    level: str
    title: str
    old: str                     # automaton A (text)
    current: str                 # current state of A
    new: str                     # automaton B (text)
    expect: Status               # expected status
    why: str                     # explanation of the expected output
    answer: Optional[str] = None            # expected B state when UNIQUE
    candidates: Tuple[str, ...] = ()        # expected real B states in N(q)
    lenient: bool = False
    table: bool = False          # also print the mapping for all states of A

    def __post_init__(self) -> None:
        if self.expect is Status.UNIQUE and not self.candidates:
            assert self.answer is not None
            self.candidates = (self.answer,)


# ==========================================================================
# Reusable automata
# ==========================================================================
DIAMOND_A = "start=s; s -a-> x; s -b-> y; x -c-> q; y -c-> q"

LOOP_A = "start=s; s -a-> q; q -b-> q"

ORDER_V1 = ("start=new; new -pay-> paid; paid -ship-> shipped; "
            "shipped -deliver-> delivered; new -cancel-> cancelled; "
            "paid -refund-> cancelled")
ORDER_V2 = ("start=new; new -pay-> paid; paid -pack-> packed; packed -ship-> shipped; "
            "shipped -deliver-> delivered; new -cancel-> cancelled; "
            "paid -refund-> cancelled")

SPLIT_MERGE_A = ("start=s; s -a-> x; s -b-> y; x -c-> m; y -c-> m; m -d-> q")
SPLIT_MERGE_B = ("start=S; S -a-> X; S -b-> Y; X -c-> M1; Y -c-> M2; "
                 "M1 -d-> P; M2 -d-> P")

APPROVAL_A = ("start=draft; draft -submit_small-> submitted; "
              "draft -submit_large-> submitted; submitted -approve-> approved; "
              "submitted -reject-> draft; approved -archive-> archived")
APPROVAL_B = ("start=draft; draft -submit_small-> sub_small; "
              "draft -submit_large-> sub_large; sub_small -approve-> approved; "
              "sub_small -reject-> draft; sub_large -manager_ok-> sub_large_ok; "
              "sub_large -reject-> draft; sub_large_ok -approve-> approved; "
              "sub_large_ok -reject-> draft; approved -archive-> archived")

CASES: List[Case] = [
    # ======================================================================
    # VERY SIMPLE: chains, no merging of paths
    # ======================================================================
    Case("L1-01", VERY_SIMPLE, "Identical copy",
         old="start=s; s -a-> x; x -b-> q", current="q",
         new="start=s; s -a-> x; x -b-> q",
         expect=Status.UNIQUE, answer="q",
         why="B is a copy of A. The only history of 'q' is 'a b' and B replays "
             "it into 'q'."),

    Case("L1-02", VERY_SIMPLE, "Same structure, different names",
         old="start=s; s -a-> x; x -b-> q", current="q",
         new="start=S0; S0 -a-> S1; S1 -b-> S2",
         expect=Status.UNIQUE, answer="S2",
         why="State names are irrelevant, only event histories matter: 'a b' "
             "leads A to 'q' and B to 'S2'."),

    Case("L1-03", VERY_SIMPLE, "B is broader than A (new events added)",
         old="start=s; s -a-> q", current="q",
         new="start=s; s -a-> p; s -z-> extra; p -y-> extra",
         expect=Status.UNIQUE, answer="p",
         why="B can do more than A (events z and y), but the only history of "
             "'q' ('a') is replayed into a single state. Extra behaviour of B "
             "does not matter."),

    Case("L1-04", VERY_SIMPLE, "B is narrower, but lost only an unrelated branch",
         old="start=s; s -a-> q; s -x-> z", current="q",
         new="start=s; s -a-> p",
         expect=Status.UNIQUE, answer="p",
         why="B dropped the event 'x', so B is narrower than A. But 'x' is not "
             "on any path to 'q'; only histories of 'q' matter."),

    Case("L1-05", VERY_SIMPLE, "B lost an event that q depends on",
         old="start=s; s -a-> x; x -b-> q", current="q",
         new="start=s; s -a-> x",
         expect=Status.STUCK, candidates=(),
         why="History 'a b' exists in A. In B, after 'a' we are in 'x', where "
             "'b' is not allowed. The history cannot be replayed, so there is "
             "no corresponding state."),

    Case("L1-06", VERY_SIMPLE, "Current state has no history (unreachable)",
         old="start=s; s -a-> x; orphan -b-> q", current="q",
         new="start=s; s -a-> x",
         expect=Status.UNREACHABLE,
         why="'q' can only be entered from 'orphan', and 'orphan' itself cannot "
             "be reached from the start. No history -> the question makes no "
             "sense (the input is probably inconsistent)."),

    Case("L1-07", VERY_SIMPLE, "Current state is the start state",
         old="start=s; s -a-> x", current="s",
         new="start=t; t -a-> u",
         expect=Status.UNIQUE, answer="t",
         why="The only history of the start state is the empty word, so the "
             "answer is the start state of B."),

    # ======================================================================
    # SIMPLE: merging paths and loops
    # ======================================================================
    Case("L2-01", SIMPLE, "Diamond: B merges the paths too",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; s2 -b-> y2; x2 -c-> p; y2 -c-> p",
         expect=Status.UNIQUE, answer="p",
         why="Two histories reach 'q' in A: 'a c' and 'b c'. In B both end in "
             "'p', so whichever one really happened, the answer is 'p'."),

    Case("L2-02", SIMPLE, "Diamond: B keeps the paths apart",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; s2 -b-> y2; x2 -c-> p1; y2 -c-> p2; "
             "p1 -d-> t",
         expect=Status.AMBIGUOUS, candidates=("p1", "p2"),
         why="A forgot whether it came by 'a c' or 'b c' (both are 'q'). B "
             "remembers it: 'p1' vs 'p2'. Without a log we cannot know which "
             "one is right. The program also shows that the two B states "
             "really differ: 'd' is allowed only in 'p1'."),

    Case("L2-03", SIMPLE, "Loop: infinitely many histories, one target",
         old=LOOP_A, current="q",
         new="start=s; s -a-> p; p -b-> p",
         expect=Status.UNIQUE, answer="p",
         why="Histories of 'q' are 'a', 'a b', 'a b b', ... (infinitely many). "
             "B maps all of them to 'p'. The algorithm does not enumerate "
             "words: the product has only 2 reachable pairs."),

    Case("L2-04", SIMPLE, "Loop: B unrolls the first iteration",
         old=LOOP_A, current="q",
         new="start=s; s -a-> p1; p1 -b-> p2; p2 -b-> p2",
         expect=Status.AMBIGUOUS, candidates=("p1", "p2"),
         why="History 'a' ends in 'p1', but 'a b', 'a b b', ... end in 'p2'. B "
             "distinguishes 'no b yet' from 'at least one b'; A does not. "
             "Checking only the shortest history ('a') would wrongly give 'p1'."),

    Case("L2-05", SIMPLE, "Diamond: B lost one branch (strict mode)",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; x2 -c-> p",
         expect=Status.STUCK, candidates=("p",),
         why="History 'a c' works and ends in 'p', but 'b c' is impossible in "
             "B (no event 'b'). If the instance came by 'b c', it is invalid "
             "in B, so strict mode refuses to answer."),

    Case("L2-06", SIMPLE, "Same as L2-05, lenient mode",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; x2 -c-> p",
         expect=Status.UNIQUE, answer="p", lenient=True,
         why="Lenient mode: all histories that B CAN replay agree on 'p', so "
             "'p' is returned, together with a warning about the history "
             "'b c' that B rejects."),

    Case("L2-07", SIMPLE, "Ambiguous in the past, identical in the future",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; s2 -b-> y2; x2 -c-> p1; y2 -c-> p2; "
             "p1 -d-> t; p2 -d-> t",
         expect=Status.AMBIGUOUS, candidates=("p1", "p2"),
         why="B has two copies of the state: 'p1' (after 'a c') and 'p2' (after "
             "'b c'). By history the answer is still ambiguous. But the program "
             "notices that 'p1' and 'p2' allow exactly the same events, so a "
             "wrong pick is harmless for the future behaviour."),

    # ======================================================================
    # HARD: realistic workflows, cycles, refinement / coarsening, tables
    # ======================================================================
    Case("L3-01", HARD, "Order workflow v1 -> v2: state before the change",
         old=ORDER_V1, current="paid", new=ORDER_V2,
         expect=Status.UNIQUE, answer="paid",
         why="Version 2 inserts a mandatory 'pack' step after 'paid'. The only "
             "history of 'paid' is 'pay', and B replays it into 'paid'. An "
             "order that is still 'paid' can be migrated safely."),

    Case("L3-02", HARD, "Order workflow v1 -> v2: state after the change",
         old=ORDER_V1, current="shipped", new=ORDER_V2,
         expect=Status.STUCK, candidates=(), table=True,
         why="History of 'shipped' is 'pay ship'. In v2 'ship' is only allowed "
             "after 'pack', so this history is invalid in B. An order that has "
             "already been shipped cannot be mapped automatically (a manual "
             "patch like 'pretend pack happened' is needed). The table shows "
             "which states of A are migratable: new, paid, cancelled; not "
             "shipped, delivered."),

    Case("L3-03", HARD, "Ticket with a hidden 'reopened' flag (cycle)",
         old="start=new; new -assign-> work; work -finish-> done; "
             "done -reopen-> work",
         current="work",
         new="start=new; new -assign-> work1; work1 -finish-> done1; "
             "done1 -reopen-> work2; work2 -finish-> done2; "
             "done2 -reopen-> work2; work2 -escalate-> esc",
         expect=Status.AMBIGUOUS, candidates=("work1", "work2"),
         why="B splits 'work' into first pass ('work1') and after a reopen "
             "('work2'). The shortest history 'assign' says 'work1', which is "
             "wrong for a reopened ticket. The difference shows up only via "
             "the cycle 'finish reopen'. B allows 'escalate' only in 'work2', "
             "so a wrong choice has visible consequences."),

    Case("L3-04", HARD, "Coarser B: counter mod 4 -> counter mod 2",
         old="start=c0; c0 -tick-> c1; c1 -tick-> c2; c2 -tick-> c3; c3 -tick-> c0",
         current="c2",
         new="start=even; even -tick-> odd; odd -tick-> even",
         expect=Status.UNIQUE, answer="even", table=True,
         why="B forgets more than A (it counts mod 2, A mod 4), so B never "
             "separates what A merged: 'c2' has histories tick^2, tick^6, ... "
             "(always an even number) -> 'even'. When B is a quotient of A, "
             "every state of A has a unique image (see the table)."),

    Case("L3-05", HARD, "Finer B: counter mod 2 -> counter mod 4",
         old="start=even; even -tick-> odd; odd -tick-> even",
         current="even",
         new="start=c0; c0 -tick-> c1; c1 -tick-> c2; c2 -tick-> c3; "
             "c3 -tick-> c0; c3 -overflow-> halted",
         expect=Status.AMBIGUOUS, candidates=("c0", "c2"),
         why="The opposite direction: B remembers more than A. Even counts 0, "
             "2, 4, ... end in 'c0' or 'c2' alternately; A cannot tell which. "
             "B states differ in the future: the sequence 'tick overflow' is "
             "possible from 'c2' but not from 'c0'."),

    Case("L3-06", HARD, "B splits paths but merges them again before q",
         old=SPLIT_MERGE_A, current="q", new=SPLIT_MERGE_B,
         expect=Status.UNIQUE, answer="P", table=True,
         why="A merges the paths at 'm', but B keeps them apart in 'M1' and "
             "'M2'. Then both continue by 'd' into the same 'P'. So 'm' is "
             "ambiguous (see the table), but 'q' is unique. Splitting inside "
             "B is harmless unless it still separates histories at the "
             "requested state."),

    Case("L3-07", HARD, "Approval workflow: new mandatory manager step",
         old=APPROVAL_A, current="approved", new=APPROVAL_B,
         expect=Status.STUCK, candidates=("approved",), table=True,
         why="B requires 'manager_ok' after 'submit_large'. History "
             "'submit_small approve' works (-> 'approved'), but 'submit_large "
             "approve' is invalid in B, and A cannot tell which one happened. "
             "The table shows three different outcomes in one workflow: "
             "'draft' is unique (B merges back), 'submitted' is ambiguous "
             "(small vs large), 'approved' and 'archived' are stuck."),
]


# ==========================================================================
# Runner
# ==========================================================================
def evaluate(case: Case) -> Tuple[MappingResult, List[str]]:
    """Run a case; return the result and a list of mismatches (empty = OK)."""
    old, new = DFA.from_text(case.old), DFA.from_text(case.new)
    result = map_state(old, case.current, new, lenient=case.lenient)
    problems: List[str] = []
    if result.status is not case.expect:
        problems.append(f"status {result.status.value}, expected {case.expect.value}")
    if case.expect is Status.UNIQUE and result.answer != case.answer:
        problems.append(f"answer {result.answer!r}, expected {case.answer!r}")
    if set(result.candidates) != set(case.candidates):
        problems.append(f"candidates {sorted(result.candidates)}, "
                        f"expected {sorted(case.candidates)}")
    return result, problems


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def run_case(case: Case) -> bool:
    old, new = DFA.from_text(case.old), DFA.from_text(case.new)
    result, problems = evaluate(case)
    mode = " (lenient mode)" if case.lenient else ""
    print("=" * 74)
    print(f"[{case.id}] {case.level.upper()}: {case.title}{mode}")
    print("=" * 74)
    print(f"Old automaton A (start = {old.start}):")
    print(old.describe())
    print(f"Current state of A: '{case.current}'")
    print(f"New automaton B (start = {new.start}):")
    print(new.describe())
    print()
    print(f"PROGRAM OUTPUT: {result.short()}")
    print(_indent(result.explain()))
    if case.table:
        print("\n  Mapping of ALL states of A (map_all):")
        print(_indent(format_table(map_all(old, new, lenient=case.lenient)), "    "))
    print(f"\nWHY: {case.why}")
    print(f"CHECK: {'OK' if not problems else 'MISMATCH - ' + '; '.join(problems)}\n")
    return not problems


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--level", choices=[VERY_SIMPLE, SIMPLE, HARD])
    parser.add_argument("--id", help="run a single case, e.g. L2-02")
    parser.add_argument("--list", action="store_true", help="list cases and exit")
    args = parser.parse_args(argv)

    selected = [c for c in CASES
                if (args.level is None or c.level == args.level)
                and (args.id is None or c.id == args.id)]
    if not selected:
        parser.error("no case matches the given filters")

    if args.list:
        for c in selected:
            outcome = c.expect.value + (f" -> {c.answer}" if c.answer else "")
            print(f"{c.id}  {c.level:<11}  {outcome:<18}  {c.title}")
        return 0

    ok = sum(run_case(c) for c in selected)
    print(f"{ok}/{len(selected)} cases match their expectations.")
    return 0 if ok == len(selected) else 1


if __name__ == "__main__":
    sys.exit(main())
