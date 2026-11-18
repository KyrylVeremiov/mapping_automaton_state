"""Test cases for swap(), in the form  Input | Output | Result | Reason.

    Input  : old monitor A in state q
    Output : new monitor B in state p, or "AMBIGUOUS", or "IMPOSSIBLE"
    Result : TRUE if Output is the correct answer for Input, FALSE otherwise
    Reason : why a FALSE result is false

A test passes when (swap(A, q, B) == Output) equals Result.

Run:  python test_swap.py
"""

from swap import Monitor, swap

# The letters of 2^AP for AP = {a, b}
none, a, b, ab = frozenset(), frozenset({"a"}), frozenset({"b"}), frozenset({"a", "b"})

# States: ok = no pending a; leftN = an a is pending and b is needed within the next N steps;
# violated = an a was not followed by b in time.
A = Monitor(
    phi="a -> <>[0,2] b",                  # phi   = the LTL formula the monitor checks
    AP={"a", "b"},                         # AP    = atomic propositions; the alphabet is 2^AP
    Q={"ok", "left2", "left1", "violated"},           # Q     = finite, nonempty set of states
    delta={                                # delta = transition function Q x 2^AP -> Q, as (state, letter): next state
        ("ok", none): "ok",             ("ok", a): "left2",             ("ok", b): "ok",             ("ok", ab): "ok",
        ("left2", none): "left1",       ("left2", a): "left1",          ("left2", b): "ok",          ("left2", ab): "ok",
        ("left1", none): "violated",    ("left1", a): "violated",       ("left1", b): "ok",          ("left1", ab): "ok",
        ("violated", none): "violated", ("violated", a): "violated",    ("violated", b): "violated", ("violated", ab): "violated",
    },
    q0="ok",                               # q0    = initial state
    F={"ok"},                              # F     = accepting states, a subset of Q
)

B = Monitor(
    phi="a -> <>[0,3] b",                  # phi   = the LTL formula the monitor checks
    AP={"a", "b"},                         # AP    = atomic propositions; the alphabet is 2^AP
    Q={"ok", "left3", "left2", "left1", "violated"},  # Q     = finite, nonempty set of states
    delta={                                # delta = transition function Q x 2^AP -> Q, as (state, letter): next state
        ("ok", none): "ok",             ("ok", a): "left3",             ("ok", b): "ok",             ("ok", ab): "ok",
        ("left3", none): "left2",       ("left3", a): "left2",          ("left3", b): "ok",          ("left3", ab): "ok",
        ("left2", none): "left1",       ("left2", a): "left1",          ("left2", b): "ok",          ("left2", ab): "ok",
        ("left1", none): "violated",    ("left1", a): "violated",       ("left1", b): "ok",          ("left1", ab): "ok",
        ("violated", none): "violated", ("violated", a): "violated",    ("violated", b): "violated", ("violated", ab): "violated",
    },
    q0="ok",                               # q0    = initial state
    F={"ok"},                              # F     = accepting states, a subset of Q
)

# (A, q, B, Output, Result, Reason)
CASES = [
    (A, "ok", B, "ok", True, "-"),
    (A, "left2", B, "left2", False,
     "A reached left2 by reading {a}; B reading {a} reaches left3. From left2, B rejects the "
     "continuation {},{},{b}, although {a},{},{},{b} satisfies B's formula"),
]


def run():
    failed = 0
    for i, (old, q, new, output, result, reason) in enumerate(CASES, 1):
        actual = swap(old, q, new)
        ok = (actual == output) == result
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} #{i}: {old.phi} in {q} -> {new.phi} in {output} "
              f"| {'TRUE' if result else 'FALSE'} | {reason} | swap returned {actual}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return failed


if __name__ == "__main__":
    raise SystemExit(run())
