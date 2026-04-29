---
id: S-001
title: run command executes arbitrary scripts without documented risk
category: security
severity: low
status: open
---

## Problem

`cli/main.py` registers a `run` subcommand that accepts a path to any Python
script and executes it via `subprocess.run([sys.executable, script] + args)`.
This is not documented in the README or the command's help text as a privileged
operation.

```python
# cli/main.py:49-53
subprocess.run([sys.executable, script] + list(args), check=True)
```

Anyone with CLI access can use this to execute arbitrary code. For a local
desktop tool this is expected behaviour, but it should be explicitly documented
so users understand the trust boundary.

## Risk

Low — this is a local tool and the user running it already has filesystem
access. There is no remote attack surface. The risk is limited to:

- A malicious `.gnucash` file that also drops a `.py` script and tricks the
  user into running `gnucash-plaintext run <script>` (social engineering)
- Confusion about whether this command is intended for end users or developers

## Suggested fix

Either:

1. Add a `# Developer utility — executes arbitrary Python` docstring and a
   visible warning in `--help` output, **or**
2. Remove the command entirely if it is only a development convenience (it
   is not tested and not mentioned in the README).
