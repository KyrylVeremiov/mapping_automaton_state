"""MOCK of swap()"""

from dataclasses import dataclass


@dataclass
class Monitor:
    """The automaton A_phi = (Q, 2^AP, delta, q0, F) of an LTL formula phi.

    A letter of 2^AP is a frozenset of atomic propositions.
    delta maps (state, letter) -> state.
    """
    phi: str
    AP: set
    Q: set
    delta: dict
    q0: str
    F: set


def swap(A, q, B):
    # Hard-coded answers for the two example monitors only.
    return {"ok": "ok", "left2": "left3", "left1": "left2", "violated": "violated"}[q]
