"""Orchestrator failure harness (stop point S1).

The same small vertical slice (slice.py) runs under different orchestrators through one
interface (adapters.py). The harness (harness.py) subjects each of them to the same
failure scenarios and writes the numbers the decision record compares. The reference
adapter (reference.py) is the naive baseline: one subprocess per job, no retries, no
leases; it is expected to fail the must-pass gates and proves the harness detects that.
"""
