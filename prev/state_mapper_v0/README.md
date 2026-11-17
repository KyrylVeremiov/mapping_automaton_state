# State correspondence between two automata

Given two deterministic automata, an old one **A** and a new one **B**, and the current state **q** of A,
the program finds the state **p** of B that corresponds to q. The strong and the weak definition of
equivalence are taken from the formal text supplied with the task.

Requirements: Python 3.8+ (the syntax is checked against 3.8; developed and tested on 3.12) and, for
pictures, Graphviz (the `dot` command on the PATH, or a standard Windows installation). There are no
third-party Python packages.
Without Graphviz everything still works, but a `.dot` file is saved instead of a PNG.

## Files

| File | Purpose |
|---|---|
| `map_state.py` | the main program: `OLD NEW STATE`, modes, visualization |
| `run_examples.py` | runs the examples from `examples/`; contains `run_one_example(...)` |
| `formats.py`, `automaton.py` | readers for automata (JSON, DOT, JFLAP, AT&T, native `.aut`), `*` and `!` transitions |
| `mapping.py` | the algorithm (strong/weak, strict/lenient), verdicts, witness words |
| `report.py` | `short` and `explain` output |
| `visualize.py` | pictures (one per mode and one combined picture for all modes) |
| `examples/` | 14 examples: `old.<ext>`, `new.<ext>`, `case.json` |
| `tests/run_tests.py` | self-checks: formats, algorithm against brute force, relation strong => weak |
| `images/` | pictures are saved here |

## Usage

```bash
python map_state.py old.json new.json S2 --definition strong --policy strict --mode explain --visualize
python map_state.py old.jff new.dot a1b1 --definition all --policy all --visualize   # all 4 modes

python run_examples.py                      # all examples; defaults: visualize, weak, strict, short
python run_examples.py 02 07 --definition all --policy all --mode explain
python run_examples.py --definition all --policy all --picture combined   # one combined picture per example
python run_examples.py --no-visualize
python map_state.py old.json new.json --all-states --policy all      # table: strong | weak for every state of A
python run_examples.py 02 03 --all-states

python tests/run_tests.py                   # self-checks
```

Options (the same in both programs):

* `--definition strong | weak | strong_and_weak | all` (`all` = `strong_and_weak`)
* `--policy strict | lenient | strict_and_lenient | all`: what to do with a letter that has no transition. `strict`: the automaton gets stuck (STUCK). `lenient`: the letter is skipped and the state does not change.
* `--mode short | explain` (`explained` is accepted as well)
* `--visualize` (on by default in `run_examples.py`; turn it off with `--no-visualize`)
* `--picture separate | combined | both` (default `both`): with several modes, save one picture per mode, one combined picture, or both
* `--format auto | aut | json | dot | jff | att`: file format; detected automatically by default
* `--all-states`: instead of one state, a table for all states of A with strong and weak side by side (STATE is not needed, no pictures are produced)

If both definitions are requested, a `relation strong -> weak` block is printed after the results: whether
they are consistent and, if weak gives a counterpart where strong sees several endings, which histories
only strong sees.

From Python: `run_one_example("02_tricky_ambiguous", definition="strong_and_weak", policy="strict_and_lenient", mode="explain", visualize=True)`.

### Pictures

* For every combination of modes: `images/<example>__<definition>_<policy>.png`. The old automaton with the current state is on top, the new automaton with the result is below; thick coloured paths are the witness words.
* For several modes, additionally `images/<example>__all.png`: one picture with a table of the results (definition x policy) on top; the captions on the arrows show which modes produce them.

## File formats

The format is detected automatically (by extension, otherwise by content).

| Format | Extensions | What is read |
|---|---|---|
| JSON | `.json` | `{"start": "S0", "transitions": [["S0","a","S1"], ...]}`; also dialects: `initial_state`/`final_states`/`input_symbols`, `transitions` as a dictionary `{"q0": {"a": "q1"}}` or as a list of objects `{"from","symbol","to"}` |
| Graphviz | `.dot`, `.gv` | edges with `label`; `doublecircle` means accepting; the start state is the target of an arrow from an invisible node (`shape=point/none`) |
| JFLAP | `.jff`, `.xml` | finite automata (`<initial/>`, `<final/>`) |
| AT&T / OpenFst | `.att`, `.fsm`, `.fst` | one `src dst label` per line, final states on separate lines, the start state is the source of the first arc |
| native | `.aut` | see `automaton.py` |

In every format a transition label can be a letter, a list `a,b`, `*` (any letter) or `!a` (any letter except a).

* One alphabet for both automata: the union of the declared and the encountered letters.
* Determinism with overlapping transitions: explicit letter > `!` > `*`. Conflicting transitions and epsilon transitions are errors.
* If a file marks no accepting state at all, every state is accepting. A complete automaton is a special case of a partial one. Traps and "error" states are ordinary states.

## Verdicts and witnesses

| Verdict | When | Witness |
|---|---|---|
| `UNIQUE p` | all histories of q lead B to the same state p | the shortest history |
| `AMBIGUOUS {...}` | the histories lead B to different states | the shortest history for every candidate |
| `STUCK` | (strict) B cannot read a letter of a history | the history and the place where B gets stuck |
| `UNREACHABLE` | q cannot be reached from the start state of A | the set of reachable states, closed under the transitions and not containing q |
| `NO_MATCH` | only when accepting states are declared, see below | a word |

If B gets stuck on some history, the verdict STUCK takes precedence over AMBIGUOUS. The other endings are
visible in `explain`.

## Relation between the definitions: strong => weak, not the other way round

Simple histories are a part of all histories: `H_simple(q) ⊆ H(q)`. Hence (the Proposition of the formal text):

1. The **endings** of the histories (the states of B they lead to) form a subset for weak: `O_weak(q) ⊆ O_strong(q)`. Weak sees fewer of them.
2. A **correspondence** `p ~ q` means that the set of endings equals `{p}` (and p is accepting). With fewer endings a one-element set occurs more often, so **weak allows more corresponding states than strong**.
3. Therefore `p ~strong q => p ~weak q`, and the converse does not hold. If strong has at most one ending, weak gives the same answer.

Example: the old automaton S0..S3,E (tricky2), the new automaton s0..s2,e (tricky1), policy strict.

| state of A | strong | weak |
|---|---|---|
| S0 | AMBIGUOUS {s0, e} | UNIQUE s0 |
| S1 | AMBIGUOUS {s1, e} | UNIQUE s1 |
| S2 | AMBIGUOUS {s2, e} | UNIQUE s2 |
| S3 | UNIQUE e | UNIQUE e |
| E | UNIQUE e | UNIQUE e |

A unique counterpart exists for 2 of 5 states under strong and for 5 of 5 under weak. The extra endings of
strong come from histories with repeats, for example `a a a b a a` leads B to `e`. In the opposite direction
(old s, new S) strong gives 3 of 4: the verdict for `e` is STUCK, and weak adds `e ~ S3`.

The ready-made output of `python run_examples.py --all-states --policy all --mode explain` for all examples
is in `all_states_report.txt`.

The program shows this with the `relation strong -> weak` block when both definitions are run and with the
`--all-states` table. The tests check the implication on hundreds of random pairs of automata (including ones
with accepting states) and are able to catch a violation.

### How the definitions are computed

* **strong**: search in the product A x B. Histories may contain cycles and may be infinitely many, but only the reachable pairs (state of A, state of B) matter. The running time is polynomial.
* **weak**: NP-hard in general (it is a simple-path problem constrained by a word). Hence a hybrid:
  1. all endings of strong are taken from the product A x B: this is an upper bound for the candidates of weak, because `O_weak ⊆ O_strong` (weak never has more candidates than strong, while it has more equivalent pairs, see above);
  2. a candidate is confirmed if its shortest history is already simple (this is the most common case);
  3. otherwise an exact search for a simple history is started (iterative deepening with a bound from the distance in the product). It finds the shortest simple history or proves that there is none.
  On hard inputs the search can become exponential. There is a safety cap (3 million nodes) with a clear message.
  For `explain` and for the grey colouring in the pictures, all simple histories are listed as long as there are at most the budget (20 000 nodes); otherwise the colouring from strong is used and this is marked.
* **lenient** means replacing delta by its completion with self-loops. For weak this affects only B, because a simple path contains no skips.

### Accepting states
In the formal text a history is a word of L(A) and the correspondence requires w ∈ L(B). Therefore, if the files
mark accepting states, q must be accepting in A and p must be accepting in B. Otherwise a fifth verdict,
`NO_MATCH`, is given (examples 09, 10, 13). Without such marks there are exactly four verdicts.

## Examples (in different formats)

| Example | Format | What it shows |
|---|---|---|
| `01_c03_parity` | JSON | picture C-03: UNIQUE in all modes |
| `02_tricky_ambiguous` | JSON | picture tricky2_1: strong gives AMBIGUOUS {s2, e}, weak gives UNIQUE s2 |
| `03_tricky_unique` | JSON | picture tricky1_2: UNIQUE S2 |
| `04_stuck_vs_skip` | DOT | strict gives STUCK, lenient gives UNIQUE |
| `05_unreachable` | JFLAP | UNREACHABLE |
| `06_wildcard_equivalent` | .aut | `*` and `!` transitions against explicit letters |
| `07_wildcard_ambiguous` | JSON | `*` and `!` in JSON; weak and strong differ |
| `08_lenient_ambiguous` | AT&T (.fsm) | skipping a letter in automaton A changes the result |
| `09_b_rejects` | JSON | NO_MATCH: B does not accept the histories |
| `10_no_accepted_history` | .aut | NO_MATCH: q is not accepting |
| `11_merge_split` | .aut | AMBIGUOUS already for simple histories |
| `12_weak_exact_search` | .aut | the shortest history is not simple, an exact search is needed |
| `13_jflap_and_dot` | JFLAP + DOT | different formats in one pair, accepting states |
| `14_att_and_json_dict` | AT&T + JSON | a JSON dialect with a dictionary of transitions |

In `case.json` the field `expect` gives the expected result for each combination; `run_examples.py` compares
with it and prints a summary (exit code 1 on a mismatch).
