#!/bin/bash
#
# A `PreToolUse` hook on Write and Edit: a line being added that carries
# `pragma: no cover` is put to the person at the keyboard before it is written.
# Wired in `.claude/settings.json`, beside the guards that refuse.
#
# **It asks rather than refuses, and that is the whole point.** The pragma has
# legitimate uses in this tree — `printing.py` excludes `if not
# shutil.which('Xvfb')` because every image has it — so a guard that blocked it
# would be wrong and would be turned off. What it must not be is an agent's
# private decision: the pragma removes a line from the figure this project
# gates on, so it moves the 100% union gate rather than satisfying it, and the
# gate stays green while the line goes untested. Nothing else in the suite can
# report that, because there is nothing left to report.
#
# It exists because that is exactly what happened. Two branches of the macOS
# library loading were marked `no cover` on the reasoning that no container can
# reach them, an AI reviewer called it "skipping the problem", and both turned
# out to be testable — `infrastructure/guile.py` went from a pragma to 100%
# coverage with seven tests, which the pragma had declared impossible.
#
# So the question this hook puts is not "is the pragma allowed" but "has the
# alternative been tried": a test that supplies the list, the bytes or the path
# the code reads, rather than the platform it runs on. `permissionDecision:
# "ask"` is how a hook asks for that: Claude Code prompts, and the person
# answers.
#
# Exit 0 with no output where there is no pragma, so it is silent on every
# other edit.

RAW=$(cat)

printf '%s' "$RAW" | python3 -c '
import json, sys

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool = payload.get("tool_input") or {}
path = str(tool.get("file_path") or "")

# Two files are exempt, because they quote the pragma in order to say what the
# rule is and could not otherwise be edited at all: this script, and CLAUDE.md,
# where the rule is written down. The same exemption the guards beside this one
# carry, for the same reason.
exempt = ("ask-about-a-no-cover-pragma.sh", "CLAUDE.md")
if any(path.endswith(name) for name in exempt):
    sys.exit(0)

# Only the fields that write text into a file, and every edit of a payload that
# carries several.
parts = [tool.get(key) or "" for key in ("content", "new_string")]
for edit in tool.get("edits") or []:
    if isinstance(edit, dict):
        parts.append(edit.get("new_string") or "")
written = "\n".join(str(part) for part in parts)

# Only what this edit puts into the file that is not in it already: a pragma
# already there is being kept, and moving the paragraph it sits in is an
# ordinary edit. A line that is not there is being written now, which is what
# somebody is answerable for.
try:
    with open(path, encoding="utf-8") as handle:
        already = set(handle.read().splitlines())
except Exception:
    already = set()

# `no cover` is the exclusion; `no branch` and `no partial branch` are the two
# narrower ones coverage.py reads, and they take a line out of the same figure.
marks = ("pragma: no cover", "pragma: no branch", "pragma: no partial branch")
adding = [line for line in written.splitlines()
          if line not in already and any(mark in line for mark in marks)]

if not adding:
    sys.exit(0)

lines = "\n".join("    " + line.strip() for line in adding[:5])
reason = (
    "This edit adds a coverage exclusion to {path}:\n\n{lines}\n\n"
    "A pragma moves the 100% union gate rather than satisfying it: the line "
    "stops being counted, the gate stays green, and nothing else in the suite "
    "can report that it is untested. It is sometimes right — every image has "
    "Xvfb, so `printing.py` excludes that branch — but it is not a decision to "
    "take quietly.\n\n"
    "Before allowing it, ask whether the line can be reached by supplying what "
    "the code reads rather than the platform it runs on: a list of paths, the "
    "bytes of a file, a patched module attribute. The last two pragmas in this "
    "tree were both replaced that way, and `infrastructure/guile.py` reached "
    "100% with seven tests the pragma had said were impossible."
).format(path=path or "this file", lines=lines)

json.dump({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "permissionDecisionReason": reason,
}}, sys.stdout)
'
