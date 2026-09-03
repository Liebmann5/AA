"""Architecture pins: port wiring and module reachability.

These tests are pure-AST/static analyses over ``src/`` — they import nothing
from ``auto_apply`` and execute none of it, so they are deterministic and
safe to run on any machine, including the worst-case USB target.

See each test module's docstring for its contract and exemption policy.
"""