# State correspondence between two automata

Given two deterministic automata, an old one **A** and a new one **B**, and the current state **q** of A,
the program finds the state **p** of B that corresponds to q. There are three definitions (modes):

| mode | meaning |
|---|---|
| `strong` | all histories of q must lead B to the same state |
| `simple` | the same, but only simple histories count (no repeated state of A). Called "weak" in the formal text |
| `existence` | the same search with "exists" instead of "for all": lists **every state of B that some history of q can lead to** |

(Earlier versions called `simple` "weak" and `existence` "reverse"; the old names are not accepted any more.)

## Quick start

```bash
python map_state.py old.json new.json current_state_in_old
```

This is the default launch (`python run_examples.py` behaves the same way for the examples). It is the same as
`--definition all --policy all --mode explain --visualize`:
all 6 modes (strong / simple / existence x strict / lenient) are explained step by step, the relations between the
definitions are printed, and the pictures are saved to `images/`: one per mode, one picture with all paths
(`__all.png`) and one table of pictures (`__grid.png`).

## Requirements and environment

* Python 3.8+ (the syntax is checked against 3.8; developed and tested on 3.12).
* `requirements.txt` lists the Python packages: **Pillow** (it puts the table picture together). Nothing else.
* **Python packages are checked and installed automatically** before every run that makes pictures
  (`environment.py`): a missing or too old package is installed with pip. If a normal installation is impossible
  (no permission, or a system Python that refuses changes, "externally managed", PEP 668), the package is
  installed into the folder `.vendor` inside the project and used from there; the system is not touched.
  Switch it off with `--no-install` or the environment variable `STATE_MAPPER_SKIP_INSTALL=1`; install by hand with
  `python -m pip install -r requirements.txt`. If the installation fails, the program still works and only the
  table picture is skipped, with a message that says what to do.
* **Graphviz** (the `dot` program) draws the pictures. It is a program, not a Python package, so it is
  **detected, not installed silently**. It is looked for in this order: the variable `GRAPHVIZ_DOT` (full path of
  dot), the PATH, and then the standard install folders:
  * Windows: `C:\Program Files\Graphviz\bin` (what the current installers and winget use), older versioned folders
    (`Graphviz 2.38`, `Graphviz2.38`), `C:\Program Files (x86)`, `%LOCALAPPDATA%\Programs`, Chocolatey, Scoop.
    So a standard Windows installation is found even if its `bin` folder was not added to the PATH.
  * macOS and Linux: `/opt/homebrew/bin`, `/usr/local/bin`, `/opt/local/bin`, `/usr/bin`.

  If Graphviz is not found, the message says how to install it (Windows: the installer from
  https://graphviz.org/download/ with "Add Graphviz to the system PATH", or `winget install Graphviz.Graphviz`;
  macOS: `brew install graphviz`; Debian/Ubuntu: `sudo apt install graphviz`) and a `.dot` file is saved instead of
  each picture.
* `python map_state.py --check-env` prints what is installed (Python, packages, Graphviz with its version).

The Windows search was tested with a simulated folder layout on Linux (the code does not depend on the system),
not on a real Windows machine.

## Files

| File | Purpose |
|---|---|
| `map_state.py` | the main program: `OLD NEW STATE`, modes, visualization |
| `run_examples.py` | runs the examples from `examples/`; contains `run_one_example(...)` |
| `environment.py` | checks/installs the requirements, finds Graphviz |
| `formats.py`, `automaton.py` | readers for automata (JSON, DOT, JFLAP, AT&T, native `.aut`), `*` and `!` transitions |
| `mapping.py` | the algorithm (strong/simple/existence, strict/lenient), verdicts, witness words, relations |
| `report.py` | `short` and `explain` output |
| `visualize.py` | pictures (per mode, one with all paths, one table of pictures) |
| `requirements.txt` | Python packages |
| `examples/` | 15 examples: `old.<ext>`, `new.<ext>`, `case.json` |
| `tests/run_tests.py` | self-checks (see the end of this file) |
| `images/` | pictures are saved here |
| `all_states_report.txt` | ready-made output of `--all-states` for all examples |

## Usage

```bash
python map_state.py old.json new.json S2                                  # the default launch (see above)
python map_state.py old.json new.json S2 --definition existence --policy strict --mode short
python map_state.py old.jff new.dot a1b1 --definition strong_and_simple --policy strict --no-visualize
python map_state.py old.json new.json --all-states --policy all           # table for every state of A

python run_examples.py                      # all examples, the same defaults as map_state.py (see Quick start)
python run_examples.py 02 07                # only these examples
python run_examples.py --definition simple --policy strict --mode short   # a quick, compact run
python run_examples.py --picture grid       # only the table picture
python run_examples.py 02 03 --all-states

python tests/run_tests.py                   # self-checks (or: python tests/run_tests.py environment pictures)
```

Options (the same in `map_state.py` and `run_examples.py`, with the same defaults, shown in bold):

* `--definition strong | simple | existence | strong_and_simple | `**`all`**
* `--policy strict | lenient | strict_and_lenient | `**`all`**: what to do with a letter that has no transition. `strict`: the automaton gets stuck (STUCK). `lenient`: the letter is skipped and the state does not change.
* `--mode short | `**`explain`** (`explained` is accepted as well)
* `--visualize` (**on** in `map_state.py`; `--no-visualize` turns it off)
* `--picture `**`all`**` | separate,combined,grid`: which pictures to make when several modes run, see below
* `--format auto | aut | json | dot | jff | att`: file format; detected automatically by default
* `--all-states`: instead of one state, a table for all states of A with the three definitions side by side (STATE is not needed, no pictures)
* `--no-install`, `--check-env`: see "Requirements and environment"

`run_examples.py` has the same options and the same defaults, so `python run_examples.py` runs every example in all
6 modes, explained, with all pictures (120 files for the 15 examples); use `--definition simple --policy strict
--mode short` for a short run.

When several definitions are requested, a `relation` block is printed after the results (see "How the definitions
are related"). From Python: `run_one_example("02_tricky_ambiguous", definition="all", policy="all", mode="explain")`.

### Pictures

For `--definition all --policy all` (6 modes) the following files are made for an example `NAME`:

* `images/NAME__<definition>_<policy>.png`: one picture per mode (6 files). The old automaton A with the current state is on top, the new automaton B with the result is below; thick coloured paths are the witness histories, grey parts lie on no history of the state.
* `images/NAME__all.png`: **one picture with all the paths**: A and B are drawn once, every correspondence arrow is labelled with the modes that produce it, and a table at the top lists the result of every mode.
* `images/NAME__grid.png`: **one table of pictures**: columns = definitions (strong, simple, existence), rows = policies (strict, lenient), every cell is the picture of one mode with its verdict. This is a **3x2** table. With one policy it is **3x1** (`--policy strict`), with one definition **1x2** (`--definition existence`), with `strong_and_simple` and both policies 2x2, and so on.

For other combinations the names are `NAME__combined_<definition>_<policy>.png` and `NAME__grid_<definition>_<policy>.png`.
`--picture` chooses the kinds (`all`, or a comma separated list of `separate`, `combined`, `grid`); with a single
mode only its own picture is made.

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
| `UNIQUE p` | strong/simple: all histories lead B to the same state p. existence: p is the only candidate | the shortest history |
| `AMBIGUOUS {...}` | strong/simple: the histories lead B to different states. existence: several candidates | the shortest history for every candidate |
| `STUCK` | (strict) B cannot read a letter of a history. existence: *every* history makes B stuck | the history and the place where B gets stuck |
| `UNREACHABLE` | q cannot be reached from the start state of A | the set of reachable states, closed under the transitions and not containing q |
| `NO_MATCH` | only when accepting states are declared, see below | a word |

In strong and simple a history that makes B stuck gives STUCK (it takes precedence over AMBIGUOUS). **In the existence mode
such a history simply gives no candidate** (it leads nowhere); the program only notes that it exists.

## How the definitions are related

Notation: `H(q)` histories of q (words of L(A) that lead A to q), `Hsimple(q)` the simple ones, `O(q)` the set of
states of B (or "stuck") that histories lead to.

| | criterion for p |
|---|---|
| strong | `H(q)` is not empty and **for all** `w` in `H(q)`: `w` in L(B) and B ends in p |
| simple | the same for **all** `w` in `Hsimple(q)` |
| existence | **exists** `w` in `H(q)` such that B ends in p. The result is the list of all such p |

In the existence mode the condition `w in L(B)` is not part of the test: every state that some history leads to is listed.
If accepting states are declared, a candidate that is not accepting is marked `(not accepting)`, and a single
candidate that is not accepting gives `NO_MATCH`, as in the other modes.

**Chain of the corresponding states.** Let `C(q)` be the set of states that correspond to q by a definition. For
strong and simple it has at most one element. Then

```
C_strong(q)  is a subset of  C_simple(q)  is a subset of  C_existence(q)      and none of the inclusions can be reversed
```

* strong => simple: the Proposition of the formal text (simple histories are histories).
* simple => existence: if p corresponds to q by simple, every simple history leads B to p, and a simple history is a history, so p is a candidate of existence.
* Not the other way round, for each step:
  * in the table below, for S0: `C_strong = {}`, `C_simple = {s0}`, `C_existence = {s0, e}`;
  * a single candidate of existence is no proof of strong: in example 15 existence says `UNIQUE t1`, but strong and simple say `STUCK`, because another history makes B stuck and existence ignores it.

**Endings.** `O_simple(q)` is a subset of `O_strong(q)`. The candidates of existence are exactly the defined endings of
`O_strong(q)`, so existence and strong list the same states, and they give the same answer unless strong says STUCK:
existence ignores stuck histories, so it then lists the candidates of the other histories (and says STUCK only if no
history leads B anywhere). Because simple sees fewer endings, it allows more corresponding states than strong.

Old automaton S0..S3,E (tricky2), new automaton s0..s2,e (tricky1), policy strict (`--all-states`):

| state of A | strong | simple | existence |
|---|---|---|---|
| S0 | AMBIGUOUS {s0, e} | UNIQUE s0 | AMBIGUOUS {s0, e} |
| S1 | AMBIGUOUS {s1, e} | UNIQUE s1 | AMBIGUOUS {s1, e} |
| S2 | AMBIGUOUS {s2, e} | UNIQUE s2 | AMBIGUOUS {s2, e} |
| S3 | UNIQUE e | UNIQUE e | UNIQUE e |
| E | UNIQUE e | UNIQUE e | UNIQUE e |

A unique counterpart exists for 2 of 5 states under strong and for 5 of 5 under simple. In the other direction
(old s, new S) strong gives 3 of 4 (the verdict for `e` is STUCK), simple adds `e ~ S3`, and existence lists
`{S3, S0, E, S1, S2}` for `e`. The extra endings come from histories with repeats, e.g. `a a a b a a` leads B to `e`.
The `relation` blocks and the `--all-states` table show this, the tests check it on hundreds of random pairs of automata.
The output of `python run_examples.py --all-states --policy all --mode explain` is in `all_states_report.txt`.

## Complexity

`n = |Q_A|`, `m = |Q_B|`, `k = |alphabet|`.

| mode | time | memory | remark |
|---|---|---|---|
| **existence** | `O(n*m*(k + m))` | `O(n*m)` | polynomial; the same product search as strong |
| strong | `O(n*m*(k + m))` | `O(n*m)` | polynomial |
| simple | `O(n*m*(k + m))` for the pre-check, plus at most `m+1` exact searches of `O(n * k^n)` each | `O(n*m)` | exponential only in the worst case |

**Existence in detail.** The product automaton A x B has at most `n(m+1)` states (the +1 is the state "B is stuck") and
at most `n(m+1)k` transitions. One breadth-first search from `(a0, b0)` costs `O(n*m*k)`; a state p is a candidate if
and only if the pair `(q, p)` is reached (the policy lenient only adds self-loops, so the size does not change).
The shortest witness word of every candidate is read from the parent pointers: it has at most `n(m+1)-1` letters,
and there are at most `m+1` of them, so `O(n*m^2)`. In total `O(n*m*(k + m))` time and `O(n*m)` memory, linear in
the size of the product up to the factor `m` for the words. The question "is p a candidate" is reachability in the
product graph, so it is in NL.

**Simple**: deciding whether a given state p is the ending of some simple history is NP-hard (a simple path
constrained by a word; a Hamiltonian path can be encoded with a B that counts the letters), so a polynomial
algorithm for the candidate list would mean P = NP. (For the verdict alone I do not know a polynomial method
either, but I have not proved it hard.) The program computes the candidates of strong (an upper bound), confirms a
candidate when its shortest history is already simple, and only otherwise searches for a simple history exactly
(iterative deepening with a bound from the distance in the product). There is a safety cap (3 million nodes) with a clear message. For the listing in `explain` and for the grey
colouring all simple histories are enumerated as long as there are at most 20 000 search nodes.

## Accepting states
In the formal text a history is a word of L(A) and the correspondence requires `w in L(B)`. Therefore, if the files
mark accepting states, q must be accepting in A and (for strong and simple) p must be accepting in B. Otherwise a fifth
verdict, `NO_MATCH`, is given (examples 09, 10, 13). Without such marks there are exactly four verdicts.

## Examples (in different formats)

| Example | Format | What it shows |
|---|---|---|
| `01_c03_parity` | JSON | picture C-03: UNIQUE in all modes |
| `02_tricky_ambiguous` | JSON | picture tricky2_1: strong and existence give {s2, e}, simple gives UNIQUE s2 |
| `03_tricky_unique` | JSON | picture tricky1_2: UNIQUE S2 |
| `04_stuck_vs_skip` | DOT | strict gives STUCK (existence too: no history leads B anywhere), lenient gives UNIQUE |
| `05_unreachable` | JFLAP | UNREACHABLE |
| `06_wildcard_equivalent` | .aut | `*` and `!` transitions against explicit letters |
| `07_wildcard_ambiguous` | JSON | `*` and `!` in JSON; simple and strong differ |
| `08_lenient_ambiguous` | AT&T (.fsm) | skipping a letter in automaton A changes the result |
| `09_b_rejects` | JSON | NO_MATCH: B does not accept the histories |
| `10_no_accepted_history` | .aut | NO_MATCH: q is not accepting |
| `11_merge_split` | .aut | AMBIGUOUS already for simple histories |
| `12_simple_exact_search` | .aut | the shortest history is not simple, an exact search is needed; strict: existence ignores the stuck histories |
| `13_jflap_and_dot` | JFLAP + DOT | different formats in one pair, accepting states |
| `14_att_and_json_dict` | AT&T + JSON | a JSON dialect with a dictionary of transitions |
| `15_existence_ignores_stuck` | JSON | strict: strong and simple STUCK, existence UNIQUE t1 |

In `case.json` the field `expect` gives the expected result for each of the 6 combinations (`strong/strict`, ...,
`existence/lenient`); `run_examples.py` compares with it and prints a summary (exit code 1 on a mismatch or on an
inconsistency between the definitions).

## Tests

`python tests/run_tests.py` (about half a minute) runs five groups; name some of them to run only those:
`formats`, `algorithm`, `relation`, `environment`, `pictures`.

* formats: every reader gives exactly the automaton it should (accepting states, `*` and `!`, dialects, errors).
* algorithm: all three definitions on random automata against brute-force enumeration of words; the hybrid `simple` search against the full enumeration of simple histories.
* relation: strong => simple => existence on random automata (also with accepting states), the tricky pair in both directions, and negative tests that prove the checkers can fail.
* environment: installation of the requirements (pip, the fallback into `.vendor`, switching off) with a stand-in for pip, and the search for Graphviz in a simulated Windows layout.
* pictures: the geometry and the content of the table picture (3x2, 3x1, 1x2), file names, and the default launch of `map_state.py`. Skipped, with a message, if Graphviz or Pillow is missing.
