#!/usr/bin/env python3
"""
Example cases for state_mapper: 10 "very simple", 11 "simple", 14 "hard", plus 11
"complete" cases for completely defined automata (every state has a transition on
every event; forbidden events lead to a trap state instead of "no transition").

Every case has: old automaton A, current state q of A, new automaton B, the
expected outcome, a short "reason" (the pattern it illustrates) and a "why"
that explains the program output.  Cases that share a `pair` id are "minimal
pairs": a tiny change turns a possible mapping into an impossible one.
`python build_gallery.py` turns all cases into pictures and EXAMPLES.md.

Usage:
    python examples.py                  run all cases, print output + explanation
    python examples.py --level simple   only one level: "very simple" | "simple" | "hard" | "complete"
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

from prev.complete_automata.state_mapper import DFA, MappingResult, Status, format_table, map_all, map_state

VERY_SIMPLE, SIMPLE, HARD = "very simple", "simple", "hard"
COMPLETE = "complete"


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
    reason: str = ""             # short name of the pattern the case illustrates
    pair: str = ""               # id of the minimal pair (see PAIRS), if any
    error_states: Tuple[str, ...] = ()   # states of B declared as "error / trap"
    expect_note: bool = False    # does the program print a NOTE (suspicious trap)?

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

FORMS_A = ("start=empty; empty -id-> got_id; empty -addr-> got_addr; "
           "got_id -addr-> both; got_addr -id-> both")

RETRY_A = ("start=idle; idle -connect-> connecting; connecting -fail-> connecting; "
           "connecting -ok-> connected; connected -close-> idle")
RETRY_B = ("start=idle; idle -connect-> try0; try0 -fail-> try1; try1 -fail-> try2; "
           "try0 -ok-> connected; try1 -ok-> connected; try2 -ok-> connected; "
           "try2 -giveup-> failed; connected -close-> idle")

REVIEW_A = ("start=draft; draft -submit-> review; review -reject-> draft; "
            "review -legal_ok-> legal_done; review -fin_ok-> fin_done; "
            "legal_done -fin_ok-> approved; fin_done -legal_ok-> approved; "
            "approved -publish-> published")
REVIEW_B = ("start=draft; draft -submit-> review; review -reject-> draft; "
            "review -legal_ok-> legal_done; review -fin_ok-> fin_done; "
            "legal_done -fin_ok-> approved_legal_first; fin_done -legal_ok-> approved_fin_first; "
            "approved_legal_first -publish-> published; approved_fin_first -publish-> published")

SHIP_A = ("start=received; received -express-> accepted; received -normal-> accepted; "
          "accepted -check-> checked; checked -pack-> packed; packed -ship-> shipped")
SHIP_B = ("start=received; received -express-> e_acc; received -normal-> n_acc; "
          "e_acc -check-> e_chk; n_acc -check-> n_chk; e_chk -pack-> e_pack; n_chk -pack-> n_pack; "
          "e_pack -ship-> e_shipped; n_pack -ship-> n_shipped; e_shipped -insure-> insured")

# --- completely defined automata (every state has a transition on every event) ---
TURNSTILE_A = ("start=locked; locked -coin-> unlocked; locked -push-> locked; "
               "unlocked -coin-> unlocked; unlocked -push-> locked")
TURNSTILE_B = ("start=closed; closed -coin-> open; closed -push-> closed; "
               "open -coin-> open; open -push-> closed")

PARITY_A = "start=even; even -a-> odd; even -b-> even; odd -a-> even; odd -b-> odd"
PARITY_AB = ("start=a0b0; a0b0 -a-> a1b0; a0b0 -b-> a0b1; a0b1 -a-> a1b1; a0b1 -b-> a0b0; "
             "a1b0 -a-> a0b0; a1b0 -b-> a1b1; a1b1 -a-> a0b1; a1b1 -b-> a1b0")

ARM_A = ("start=idle; idle -arm-> armed; idle -fire-> idle; armed -arm-> armed; "
         "armed -fire-> triggered; triggered -arm-> triggered; triggered -fire-> idle")
ARM_B = ("start=idle; idle -arm-> armed; idle -fire-> idle; armed -arm-> armed; "
         "armed -fire-> fault; fault -arm,fire-> fault")

DIAMOND_C_A = ("start=s; s -a-> x; s -b-> y; s -c-> s; x -a,b-> x; x -c-> q; "
               "y -a,b-> y; y -c-> q; q -a,b-> q; q -c-> s")
DIAMOND_C_B = ("start=s; s -a-> x; s -b-> y; s -c-> s; x -a,b-> x; x -c-> p; "
               "y -a,b-> y; y -c-> trap; p -a,b-> p; p -c-> s; trap -a,b,c-> trap")

CASES: List[Case] = [
    # ======================================================================
    # VERY SIMPLE: chains, no merging of paths
    # ======================================================================
    Case("L1-01", VERY_SIMPLE, "Identical copy",
         reason="B is an exact copy",
         old="start=s; s -a-> x; x -b-> q", current="q",
         new="start=s; s -a-> x; x -b-> q",
         expect=Status.UNIQUE, answer="q",
         why="B is a copy of A. The only history of 'q' is 'a b' and B replays "
             "it into 'q'."),

    Case("L1-02", VERY_SIMPLE, "Same structure, different names",
         reason="same structure, different names",
         old="start=s; s -a-> x; x -b-> q", current="q",
         new="start=S0; S0 -a-> S1; S1 -b-> S2",
         expect=Status.UNIQUE, answer="S2",
         why="State names are irrelevant, only event histories matter: 'a b' "
             "leads A to 'q' and B to 'S2'."),

    Case("L1-03", VERY_SIMPLE, "B is broader than A (new events added)",
         reason="B only adds behaviour",
         old="start=s; s -a-> q", current="q",
         new="start=s; s -a-> p; s -z-> extra; p -y-> extra",
         expect=Status.UNIQUE, answer="p",
         why="B can do more than A (events z and y), but the only history of "
             "'q' ('a') is replayed into a single state. Extra behaviour of B "
             "does not matter."),

    Case("L1-04", VERY_SIMPLE, "B is narrower, but lost only an unrelated branch",
         reason="B lost a branch that does not lead to q", pair="P1",
         old="start=s; s -a-> q; s -x-> z", current="q",
         new="start=s; s -a-> p",
         expect=Status.UNIQUE, answer="p",
         why="B dropped the event 'x', so B is narrower than A. But 'x' is not "
             "on any path to 'q'; only histories of 'q' matter."),

    Case("L1-05", VERY_SIMPLE, "B lost an event that q depends on",
         reason="B lost an event on the path to q", pair="P1",
         old="start=s; s -a-> x; x -b-> q", current="q",
         new="start=s; s -a-> x",
         expect=Status.STUCK, candidates=(),
         why="History 'a b' exists in A. In B, after 'a' we are in 'x', where "
             "'b' is not allowed. The history cannot be replayed, so there is "
             "no corresponding state."),

    Case("L1-06", VERY_SIMPLE, "Current state has no history (unreachable)",
         reason="q has no history",
         old="start=s; s -a-> x; orphan -b-> q", current="q",
         new="start=s; s -a-> x",
         expect=Status.UNREACHABLE,
         why="'q' can only be entered from 'orphan', and 'orphan' itself cannot "
             "be reached from the start. No history -> the question makes no "
             "sense (the input is probably inconsistent)."),

    Case("L1-07", VERY_SIMPLE, "Current state is the start state",
         reason="start state = empty history",
         old="start=s; s -a-> x", current="s",
         new="start=t; t -a-> u",
         expect=Status.UNIQUE, answer="t",
         why="The only history of the start state is the empty word, so the "
             "answer is the start state of B."),

    Case("L1-08", VERY_SIMPLE, "B changes only what happens AFTER q",
         reason="B changed only what happens after q",
         old="start=s; s -a-> q; q -b-> r", current="q",
         new="start=s; s -a-> p; p -x-> u; p -y-> v; u -z-> p",
         expect=Status.UNIQUE, answer="p",
         why="Only the PAST of a state matters. After 'p' B behaves completely "
             "differently (x, y, z instead of b), but the only history of 'q' "
             "('a') is replayed and ends in 'p'. What the state can do next is "
             "irrelevant."),

    Case("L1-09", VERY_SIMPLE, "Event renamed in B",
         reason="event renamed in B",
         old="start=s; s -pay-> q", current="q",
         new="start=s; s -payment-> p",
         expect=Status.STUCK, candidates=(),
         why="B calls the event 'payment' instead of 'pay'. Events are compared "
             "by name, so B rejects the first event of every history. Fix: "
             "translate the event names first ('pay' -> 'payment') and run "
             "again."),

    Case("L1-10", VERY_SIMPLE, "B demands a new first step",
         reason="new mandatory first step in B",
         old="start=s; s -a-> x; x -b-> q", current="q",
         new="start=init; init -login-> s; s -a-> x; x -b-> q",
         expect=Status.STUCK, candidates=(),
         why="B requires a 'login' event before anything else. Every history of "
             "'q' is rejected at its very first event: 'a' is not allowed in B's "
             "start state 'init'. Old instances never did 'login', so they "
             "cannot be placed in B."),

    # ======================================================================
    # SIMPLE: merging paths and loops
    # ======================================================================
    Case("L2-01", SIMPLE, "Diamond: B merges the paths too",
         reason="B merges the paths too", pair="P2",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; s2 -b-> y2; x2 -c-> p; y2 -c-> p",
         expect=Status.UNIQUE, answer="p",
         why="Two histories reach 'q' in A: 'a c' and 'b c'. In B both end in "
             "'p', so whichever one really happened, the answer is 'p'."),

    Case("L2-02", SIMPLE, "Diamond: B keeps the paths apart",
         reason="B keeps the paths apart", pair="P2",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; s2 -b-> y2; x2 -c-> p1; y2 -c-> p2; "
             "p1 -d-> t",
         expect=Status.AMBIGUOUS, candidates=("p1", "p2"),
         why="A forgot whether it came by 'a c' or 'b c' (both are 'q'). B "
             "remembers it: 'p1' vs 'p2'. Without a log we cannot know which "
             "one is right. The program also shows that the two B states "
             "really differ: 'd' is allowed only in 'p1'."),

    Case("L2-03", SIMPLE, "Loop: infinitely many histories, one target",
         reason="all histories of a loop end in one state", pair="P3",
         old=LOOP_A, current="q",
         new="start=s; s -a-> p; p -b-> p",
         expect=Status.UNIQUE, answer="p",
         why="Histories of 'q' are 'a', 'a b', 'a b b', ... (infinitely many). "
             "B maps all of them to 'p'. The algorithm does not enumerate "
             "words: the product has only 2 reachable pairs."),

    Case("L2-04", SIMPLE, "Loop: B unrolls the first iteration",
         reason="B unrolls the first loop iteration", pair="P3",
         old=LOOP_A, current="q",
         new="start=s; s -a-> p1; p1 -b-> p2; p2 -b-> p2",
         expect=Status.AMBIGUOUS, candidates=("p1", "p2"),
         why="History 'a' ends in 'p1', but 'a b', 'a b b', ... end in 'p2'. B "
             "distinguishes 'no b yet' from 'at least one b'; A does not. "
             "Checking only the shortest history ('a') would wrongly give 'p1'."),

    Case("L2-05", SIMPLE, "Diamond: B lost one branch (strict mode)",
         reason="B lost one of the paths (strict mode)", pair="P4",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; x2 -c-> p",
         expect=Status.STUCK, candidates=("p",),
         why="History 'a c' works and ends in 'p', but 'b c' is impossible in "
             "B (no event 'b'). If the instance came by 'b c', it is invalid "
             "in B, so strict mode refuses to answer."),

    Case("L2-06", SIMPLE, "Same as L2-05, lenient mode",
         reason="same, lenient mode", pair="P4",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; x2 -c-> p",
         expect=Status.UNIQUE, answer="p", lenient=True,
         why="Lenient mode: all histories that B CAN replay agree on 'p', so "
             "'p' is returned, together with a warning about the history "
             "'b c' that B rejects."),

    Case("L2-07", SIMPLE, "Ambiguous in the past, identical in the future",
         reason="B duplicates the state, same future",
         old=DIAMOND_A, current="q",
         new="start=s2; s2 -a-> x2; s2 -b-> y2; x2 -c-> p1; y2 -c-> p2; "
             "p1 -d-> t; p2 -d-> t",
         expect=Status.AMBIGUOUS, candidates=("p1", "p2"),
         why="B has two copies of the state: 'p1' (after 'a c') and 'p2' (after "
             "'b c'). By history the answer is still ambiguous. But the program "
             "notices that 'p1' and 'p2' allow exactly the same events, so a "
             "wrong pick is harmless for the future behaviour."),

    Case("L2-08", SIMPLE, "B dropped the loop on q",
         reason="B dropped the loop on q",
         old="start=s; s -a-> q; q -b-> q", current="q",
         new="start=s; s -a-> p",
         expect=Status.STUCK, candidates=("p",),
         why="History 'a' is fine and ends in 'p'. But 'a b', 'a b b', ... use "
             "the loop q -b-> q, which B no longer has. An instance that went "
             "around the loop even once cannot be replayed. Lenient mode would "
             "return 'p' with a warning."),

    Case("L2-09", SIMPLE, "Two forms in any order: B remembers the order",
         reason="B remembers the order of two events", pair="P5",
         old=FORMS_A, current="both",
         new="start=empty; empty -id-> got_id; empty -addr-> got_addr; "
             "got_id -addr-> both_id_first; got_addr -id-> both_addr_first; "
             "both_addr_first -audit-> audited",
         expect=Status.AMBIGUOUS, candidates=("both_id_first", "both_addr_first"),
         why="In A the two forms ('id', 'addr') can be filled in either order and "
             "both orders give 'both'. B now records which form came first, and "
             "treats the orders differently ('audit' only after 'addr' first). "
             "A forgot the order, so the choice cannot be made."),

    Case("L2-10", SIMPLE, "Two forms in any order: B merges them too",
         reason="B merges both orders of the same events", pair="P5",
         old=FORMS_A, current="both",
         new="start=empty; empty -id-> got_id; empty -addr-> got_addr; "
             "got_id -addr-> both; got_addr -id-> both; both -submit-> done",
         expect=Status.UNIQUE, answer="both",
         why="Same A as in L2-09, but B also merges the two orders into one state "
             "('both'). Both histories 'id addr' and 'addr id' end there, so the "
             "answer is unique (the extra 'submit' step is after 'both' and does "
             "not matter)."),

    Case("L2-11", SIMPLE, "Three histories, B separates only one",
         reason="B separates only one of three histories",
         old="start=s; s -a-> x; s -b-> y; s -c-> z; x -e-> q; y -e-> q; z -e-> q",
         current="q",
         new="start=S; S -a-> X; S -b-> Y; S -c-> Z; X -e-> Q1; Y -e-> Q1; Z -e-> Q2",
         expect=Status.AMBIGUOUS, candidates=("Q1", "Q2"),
         why="Three histories reach 'q': 'a e', 'b e', 'c e'. B merges the first two "
             "into 'Q1' but sends 'c e' to 'Q2'. The number of candidates (2) is "
             "not the number of histories (3): it is the number of different B "
             "states they end in."),

    # ======================================================================
    # HARD: realistic workflows, cycles, refinement / coarsening, tables
    # ======================================================================
    Case("L3-01", HARD, "Order workflow v1 -> v2: state before the change",
         reason="q lies before the change in B", pair="P6",
         old=ORDER_V1, current="paid", new=ORDER_V2,
         expect=Status.UNIQUE, answer="paid",
         why="Version 2 inserts a mandatory 'pack' step after 'paid'. The only "
             "history of 'paid' is 'pay', and B replays it into 'paid'. An "
             "order that is still 'paid' can be migrated safely."),

    Case("L3-02", HARD, "Order workflow v1 -> v2: state after the change",
         reason="q lies after the new mandatory step", pair="P6",
         old=ORDER_V1, current="shipped", new=ORDER_V2,
         expect=Status.STUCK, candidates=(), table=True,
         why="History of 'shipped' is 'pay ship'. In v2 'ship' is only allowed "
             "after 'pack', so this history is invalid in B. An order that has "
             "already been shipped cannot be mapped automatically (a manual "
             "patch like 'pretend pack happened' is needed). The table shows "
             "which states of A are migratable: new, paid, cancelled; not "
             "shipped, delivered."),

    Case("L3-03", HARD, "Ticket with a hidden 'reopened' flag (cycle)",
         reason="hidden flag visible only through a cycle",
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
         reason="B forgets more than A (coarser)", pair="P7",
         old="start=c0; c0 -tick-> c1; c1 -tick-> c2; c2 -tick-> c3; c3 -tick-> c0",
         current="c2",
         new="start=even; even -tick-> odd; odd -tick-> even",
         expect=Status.UNIQUE, answer="even", table=True,
         why="B forgets more than A (it counts mod 2, A mod 4), so B never "
             "separates what A merged: 'c2' has histories tick^2, tick^6, ... "
             "(always an even number) -> 'even'. When B is a quotient of A, "
             "every state of A has a unique image (see the table)."),

    Case("L3-05", HARD, "Finer B: counter mod 2 -> counter mod 4",
         reason="B remembers more than A (finer)", pair="P7",
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
         reason="B splits the paths but merges them before q", pair="P8",
         old=SPLIT_MERGE_A, current="q", new=SPLIT_MERGE_B,
         expect=Status.UNIQUE, answer="P", table=True,
         why="A merges the paths at 'm', but B keeps them apart in 'M1' and "
             "'M2'. Then both continue by 'd' into the same 'P'. So 'm' is "
             "ambiguous (see the table), but 'q' is unique. Splitting inside "
             "B is harmless unless it still separates histories at the "
             "requested state."),

    Case("L3-07", HARD, "Approval workflow: new mandatory manager step",
         reason="one workflow, three different outcomes",
         old=APPROVAL_A, current="approved", new=APPROVAL_B,
         expect=Status.STUCK, candidates=("approved",), table=True,
         why="B requires 'manager_ok' after 'submit_large'. History "
             "'submit_small approve' works (-> 'approved'), but 'submit_large "
             "approve' is invalid in B, and A cannot tell which one happened. "
             "The table shows three different outcomes in one workflow: "
             "'draft' is unique (B merges back), 'submitted' is ambiguous "
             "(small vs large), 'approved' and 'archived' are stuck."),

    Case("L3-08", HARD, "Retry limit in B: ambiguous AND stuck at once",
         reason="retry limit in B: ambiguous and stuck at once",
         old=RETRY_A, current="connecting", new=RETRY_B,
         expect=Status.AMBIGUOUS, candidates=("try0", "try1", "try2"), table=True,
         why="A retries a failed connection forever, B allows only 2 retries. "
             "Histories 'connect', 'connect fail', 'connect fail fail' end in "
             "'try0', 'try1', 'try2' (ambiguous), and 'connect fail fail fail' "
             "cannot be replayed at all (stuck). The table shows that even "
             "'idle' is tainted: some of its histories contain 3+ failures."),

    Case("L3-09", HARD, "Retry limit in B: connected, strict mode",
         reason="retry limit in B: strict mode", pair="P9",
         old=RETRY_A, current="connected", new=RETRY_B,
         expect=Status.STUCK, candidates=("connected",),
         why="Whatever B can replay ends in 'connected' (success after 0, 1 or "
             "2 failures). But 'connect fail fail fail ok' is a valid history in "
             "A and invalid in B. Strict mode refuses, because one real "
             "instance may have followed that history."),

    Case("L3-10", HARD, "Retry limit in B: connected, lenient mode",
         reason="retry limit in B: lenient mode", pair="P9",
         old=RETRY_A, current="connected", new=RETRY_B,
         expect=Status.UNIQUE, answer="connected", lenient=True,
         why="Same automata as L3-09. Lenient mode accepts 'connected' because "
             "all replayable histories agree on it, and warns that histories "
             "with 3+ failures are not valid in B. Use it when such instances "
             "are known not to exist (or will be handled separately)."),

    Case("L3-11", HARD, "Counter mod 2 -> mod 6: three candidates",
         reason="B counts modulo more than A (3 candidates)",
         old="start=even; even -tick-> odd; odd -tick-> even", current="even",
         new="start=c0; c0 -tick-> c1; c1 -tick-> c2; c2 -tick-> c3; c3 -tick-> c4; "
             "c4 -tick-> c5; c5 -tick-> c0; c5 -overflow-> halted",
         expect=Status.AMBIGUOUS, candidates=("c0", "c2", "c4"),
         why="'even' has histories tick^0, tick^2, tick^4, tick^6, ... B counts "
             "mod 6, so they end in c0, c2, c4, c0, ... (three different states). "
             "Each candidate behaves differently: 'overflow' is 5, 3 or 1 ticks "
             "away."),

    Case("L3-12", HARD, "Parallel approvals: ambiguous, but harmless",
         reason="ambiguous in the past, harmless for the future",
         old=REVIEW_A, current="approved", new=REVIEW_B,
         expect=Status.AMBIGUOUS,
         candidates=("approved_legal_first", "approved_fin_first"), table=True,
         why="A lets legal and finance approve in any order and does not "
             "remember who was first. B records it in two different states. By "
             "history the answer is ambiguous, but the program notices that "
             "both B states allow exactly the same events ('publish'), so "
             "choosing either is safe for the future. Also note that "
             "'published' is unique again: B merges the two states there."),

    Case("L3-13", HARD, "An early split persists along the whole chain",
         reason="an early split persists along the whole chain",
         old=SHIP_A, current="shipped", new=SHIP_B,
         expect=Status.AMBIGUOUS, candidates=("e_shipped", "n_shipped"), table=True,
         why="A never distinguished 'express' from 'normal' delivery (both lead "
             "to 'accepted'). B keeps two separate chains. As long as the chains "
             "do not merge again, EVERY later state is ambiguous (see the "
             "table). Only 'received' (before the split) is unique. Compare "
             "with L3-06, where the merge cancels the ambiguity."),

    Case("L3-14", HARD, "Split and merge again: q inside the split part",
         reason="q lies inside the split part of B", pair="P8",
         old=SPLIT_MERGE_A, current="m", new=SPLIT_MERGE_B,
         expect=Status.AMBIGUOUS, candidates=("M1", "M2"),
         why="Same automata as L3-06, but now we ask about 'm', which lies "
             "between the split and the merge. Histories 'a c' and 'b c' end in "
             "'M1' and 'M2'. (Here both allow the same events, so for the "
             "future either would do, but by history it is a guess.)"),

    # ======================================================================
    # COMPLETE: completely defined automata
    # ======================================================================
    Case("C-01", COMPLETE, "Turnstile: complete automata without a trap",
         reason="complete automata, no trap states",
         old=TURNSTILE_A, current="unlocked", new=TURNSTILE_B,
         expect=Status.UNIQUE, answer="open",
         why="Both automata are completely defined: every state reacts to every "
             "event ('ignored' events are self-loops), so nothing is ever "
             "'undefined' and there is no trap. The histories of 'unlocked' are "
             "all words ending in 'coin'; in B they all end in 'open'. For "
             "complete automata without traps the rule is unchanged: all "
             "histories must end in one state."),

    Case("C-02", COMPLETE, "Parity of a's -> parity of a's AND b's (finer B)",
         reason="complete B counts more than A (finer)",
         old=PARITY_A, current="odd", new=PARITY_AB,
         expect=Status.AMBIGUOUS, candidates=("a1b0", "a1b1"),
         why="'odd' means an odd number of a's, and A ignores b's. B also counts "
             "b's mod 2, so the same A-state is spread over two B-states: "
             "'a' ends in 'a1b0', 'a b' ends in 'a1b1'. The number of b's was "
             "never recorded in A, so it cannot be restored."),

    Case("C-03", COMPLETE, "Parity of a's AND b's -> parity of a's (coarser B)",
         reason="complete B counts less than A (coarser)",
         old=PARITY_AB, current="a1b1", new=PARITY_A,
         expect=Status.UNIQUE, answer="odd", table=True,
         why="The opposite direction: B forgets the b-parity, so it never "
             "separates what A merged. Every state of A has exactly one image "
             "(see the table): a0b*, a1b* -> even, odd. Coarsening is always safe."),

    Case("C-04", COMPLETE, "A forbidden event leads to an UNDECLARED trap",
         reason="forbidden event leads to an undeclared trap", pair="P10",
         old=ARM_A, current="triggered", new=ARM_B,
         expect=Status.UNIQUE, answer="fault", expect_note=True,
         why="B is complete: it forbids 'fire' in state 'armed' by sending it to "
             "the absorbing trap 'fault'. The program does not know that 'fault' "
             "means 'error', so it treats it as an ordinary state: every history "
             "of 'triggered' ends there, and the answer looks UNIQUE. That "
             "answer is misleading (no real instance can sit in 'fault' and "
             "continue). The NOTE appears because 'fault' is absorbing while "
             "'triggered' is not. Compare with C-05."),

    Case("C-05", COMPLETE, "The same, with the trap declared as an error state",
         reason="the trap is declared as an error state", pair="P10",
         old=ARM_A, current="triggered", new=ARM_B,
         expect=Status.STUCK, candidates=(), error_states=("fault",),
         why="Same automata as C-04, but 'fault' is declared as an error state "
             "(error_states={'fault'}). Entering it now counts as 'B rejects "
             "this event', exactly like a missing transition in a partial "
             "automaton, and the honest answer appears: history 'arm fire' is "
             "possible in A but forbidden in B."),

    Case("C-06", COMPLETE, "An absorbing state is not necessarily an error",
         reason="an absorbing state that is not an error",
         old="start=new; new -pay-> paid; new -cancel-> cancelled; paid -pay-> paid; "
             "paid -cancel-> cancelled; cancelled -pay,cancel-> cancelled",
         current="cancelled",
         new="start=open; open -pay-> settled; open -cancel-> void; settled -pay-> settled; "
             "settled -cancel-> void; void -pay,cancel-> void",
         expect=Status.UNIQUE, answer="void",
         why="'void' looks like a trap (everything loops back), but it is the "
             "legitimate counterpart of 'cancelled', which is absorbing in A "
             "too. Structure alone cannot tell an error trap from a normal final "
             "state, which is why error states must be declared by you, and the "
             "NOTE is printed only when A's state can still move on."),

    Case("C-07", COMPLETE, "Order workflow: ignored events and a declared trap",
         reason="ignored events (self-loops) plus a declared trap",
         old="start=new; new -pay-> paid; new -ship-> new; new -cancel-> cancelled; "
             "paid -pay-> paid; paid -ship-> shipped; paid -cancel-> cancelled; "
             "shipped -pay,ship,cancel-> shipped; cancelled -pay,ship,cancel-> cancelled",
         current="shipped",
         new="start=new; new -pay-> paid; new -ship-> new; new -cancel-> cancelled; "
             "paid -pay-> paid; paid -ship-> rejected; paid -cancel-> cancelled; "
             "cancelled -pay,ship,cancel-> cancelled; rejected -pay,ship,cancel-> rejected",
         expect=Status.STUCK, candidates=(), error_states=("rejected",), table=True,
         why="In A, shipping is allowed after payment; in B it leads to the trap "
             "'rejected' (declared as an error state). Orders in 'shipped' came "
             "through 'pay ship', which B forbids, so they cannot be mapped. The "
             "table shows the rest of the workflow is fine: 'new', 'paid' and "
             "'cancelled' are unique. Note that 'ship' in state 'new' is an "
             "ignored event (a self-loop) in both automata and is harmless."),

    Case("C-08", COMPLETE, "q is the trap state of A itself",
         reason="q is the trap state of A",
         old="start=s; s -a-> x; s -b-> err; x -a,b-> x; err -a,b-> err",
         current="err",
         new="start=s; s -a-> x; s -b-> y; y -a-> y; y -b-> z; x -a,b-> x; z -a,b-> z",
         expect=Status.AMBIGUOUS, candidates=("y", "z"),
         why="'err' collects every invalid sequence of A (all words starting with "
             "'b'). B accepts such sequences and treats them differently ('b' -> "
             "'y', 'b b' -> 'z'). Do not map an error state by history: an "
             "instance in A's error state is not a live instance. Handle it "
             "separately (for example 'error -> error')."),

    Case("C-09", COMPLETE, "One path leads into a trap: trap NOT declared",
         reason="undeclared trap on one path", pair="P11",
         old=DIAMOND_C_A, current="q", new=DIAMOND_C_B,
         expect=Status.AMBIGUOUS, candidates=("p", "trap"), expect_note=True,
         why="'q' has histories 'a c' and 'b c'. In B the first ends in 'p', the "
             "second enters the absorbing 'trap'. Because the trap is treated as "
             "an ordinary state, the result reads as an ordinary ambiguity "
             "('p' or 'trap'), although one of the 'candidates' is really a "
             "rejection. The NOTE points at the suspicious state."),

    Case("C-10", COMPLETE, "The same, trap declared (strict)",
         reason="declared trap, strict mode", pair="P11",
         old=DIAMOND_C_A, current="q", new=DIAMOND_C_B,
         expect=Status.STUCK, candidates=("p",), error_states=("trap",),
         why="With 'trap' declared as an error state the picture is precise: "
             "'a c' is replayed (-> 'p'), 'b c' is rejected by B. Strict mode "
             "refuses, because an instance may have come by 'b c'."),

    Case("C-11", COMPLETE, "The same, trap declared, answer accepted anyway",
         reason="declared trap, lenient mode", pair="P11",
         old=DIAMOND_C_A, current="q", new=DIAMOND_C_B,
         expect=Status.UNIQUE, answer="p", error_states=("trap",), lenient=True,
         why="Lenient mode returns 'p' because every history that B accepts ends "
             "there, and warns that 'b c' is rejected (it enters the error "
             "state 'trap'). Use it only if instances with such a history are "
             "known not to exist."),


    # Case("M-01", VERY_SIMPLE, "...",
    #      reason="B is an exact copy",
    #      old="start=s; s -a-> s1; s1 -a-> s2; s2 -a-> s1; s1 -d-> s3", current="s3",
    #      new="start=S; S -a-> S1; S1 -a-> S2; S2 -a-> S3; S3 -d-> S4",
    #      expect=Status.UNIQUE, answer="S4",
    #      why="..."),


    # Case("M-02", VERY_SIMPLE, "...",
    #      reason="B is an exact copy",
    #      old="start=s; s -a-> s1; s1 -a-> s2; s2 -a-> s3; s3 -d-> s4; s3 -a-> s2", current="s3",
    #      new="start=S; S -a-> S1; S1 -a-> S2; S2 -a-> S3; S3 -d-> S4",
    #      expect=Status.UNIQUE, answer="S4",
    #      why="..."),
]


# Minimal pairs: (title, [case ids]).  A tiny change flips the answer.
PAIRS = {
    "P1": ("Lost branch: unrelated to q vs. needed by q", ["L1-04", "L1-05"]),
    "P2": ("Diamond: B merges the paths vs. B keeps them apart", ["L2-01", "L2-02"]),
    "P3": ("Loop: same loop in B vs. first iteration unrolled", ["L2-03", "L2-04"]),
    "P4": ("Same automata: strict vs. lenient mode", ["L2-05", "L2-06"]),
    "P5": ("Two forms in any order: B merges vs. B remembers the order", ["L2-10", "L2-09"]),
    "P6": ("Same automata: q before vs. after the new mandatory step", ["L3-01", "L3-02"]),
    "P7": ("Counter: coarser B (mod 4 -> 2) vs. finer B (mod 2 -> 4)", ["L3-04", "L3-05"]),
    "P8": ("Same automata: q after the merge vs. q inside the split", ["L3-06", "L3-14"]),
    "P9": ("Same automata: strict (refuse) vs. lenient (answer + warning)", ["L3-09", "L3-10"]),
    "P10": ("Complete B: trap state not declared vs. declared as an error state", ["C-04", "C-05"]),
    "P11": ("Complete B with a trap on one path: not declared / declared strict / declared lenient",
            ["C-09", "C-10", "C-11"]),
}


# ==========================================================================
# Runner
# ==========================================================================
def evaluate(case: Case) -> Tuple[MappingResult, List[str]]:
    """Run a case; return the result and a list of mismatches (empty = OK)."""
    old, new = DFA.from_text(case.old), DFA.from_text(case.new)
    result = map_state(old, case.current, new, lenient=case.lenient,
                       error_states=case.error_states)
    problems: List[str] = []
    if case.level == COMPLETE:      # these cases are about completely defined automata
        alphabet = old.alphabet | new.alphabet
        for name, dfa in (("A", old), ("B", new)):
            if not dfa.is_complete(alphabet):
                problems.append(f"automaton {name} is not completely defined")
    if bool(result.notes) != case.expect_note:
        problems.append(f"NOTE printed: {bool(result.notes)}, expected {case.expect_note}")
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
    print(f"Pattern: {case.reason}" + (f"   (minimal pair {case.pair})" if case.pair else ""))
    print("=" * 74)
    print(f"Old automaton A (start = {old.start}):")
    print(old.describe())
    print(f"Current state of A: '{case.current}'")
    print(f"New automaton B (start = {new.start}):")
    print(new.describe())
    if case.error_states:
        names = ", ".join(f"'{e}'" for e in case.error_states)
        print(f"Declared error/trap states of B: {names}")
    print()
    print(f"PROGRAM OUTPUT: {result.short()}")
    print(_indent(result.explain()))
    if case.table:
        print("\n  Mapping of ALL states of A (map_all):")
        print(_indent(format_table(map_all(old, new, lenient=case.lenient,
                                              error_states=case.error_states)), "    "))
    print(f"\nWHY: {case.why}")
    print(f"CHECK: {'OK' if not problems else 'MISMATCH - ' + '; '.join(problems)}\n")
    return not problems


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--level", choices=[VERY_SIMPLE, SIMPLE, HARD, COMPLETE])
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
