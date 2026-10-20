# Quota display collaboration demo

This isolated example is intentionally seeded with a bug for a public AImanager
collaboration demonstration. It contains no production data or credentials.

`remaining_percent(usage_level)` converts a usage ratio into remaining percentage,
rounded to one decimal. Valid numeric inputs range from 0 to 1 (inclusive).
Missing, nonnumeric, boolean, nonfinite and out-of-range values must return `None`
to mean unknown, rather than implying an available balance. Numeric strings are
not accepted. A zero usage ratio is valid and means 100% remaining.

Run tests with `python3 -m unittest -v`. Collaborators may inspect this workspace;
only explicitly authorized execution tasks may edit files or run commands.
