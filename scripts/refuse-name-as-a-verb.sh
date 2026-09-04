#!/bin/bash
#
# A `PreToolUse` hook on Write and Edit: refuse text that uses "name" as a verb for something that has no name. Wired in `.claude/settings.json`, which is committed for exactly this reason.
#
# The rule is in CLAUDE.md and it is about being understood. A guid is not a name. A split is not a name. "the message names the split" tells a reader that a split has a name and that the message prints it, and neither is true — what the message prints is a guid, and the reader who goes looking for a name finds nothing. Write what is actually there: a refusal **lists** the disposals, a report **prints** the split's guid, a block **gives** a guid, a payment **applies** a split, a guid **matches**.
#
# "name" as a noun is untouched — an account name, a file name, a customer's name, `get_account_full_name`, `--by-name`. Those are names. So is naming a thing that has one: "the error gives the account's name" is fine, and so is `name: "US Customer"`.
#
# Asking for this in CLAUDE.md was not enough. It was written down, agreed to, and broken again in the same session — in prose that had just been corrected for it — which is why it is a hook.
#
# Exit 2 blocks the call and returns stderr to the agent, so the sentence is rewritten before it is written to the file rather than found later in review.
#
# **It is a seatbelt, not a sandbox.** It matches the shapes that get typed — "names the", "naming a", "names it" — and a determined author can slip past it with a spelling nobody uses. That is fine: the point is to catch the habit, not to win an argument with someone who has decided. A shape it wrongly refuses is a defect; a shape nobody would type getting past it is not.

RAW=$(cat)

# Only the fields that write text into a file. `file_path` is not one of them: a path may legitimately hold the word, and refusing on it would block editing this very script.
#
# Two files are exempt, because they quote the shape they refuse and would
# otherwise be unable to say what they are about: this script and its test.
# Without that, correcting a word in either one is blocked by the rule the
# file exists to state — which is a shape wrongly refused, and those are
# defects.
TEXT=$(printf '%s' "$RAW" | python3 -c '
import json, sys
try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
tool = payload.get("tool_input") or {}
path = str(tool.get("file_path") or "")
exempt = ("refuse-name-as-a-verb.sh",
          "test_the_name_guard_leaves_real_names_alone.py")
if any(path.endswith(name) for name in exempt):
    sys.exit(0)
parts = [tool.get(key) or "" for key in ("content", "new_string")]
# And every edit of a payload that carries several. A tool shaped as a list of
# edits put the whole batch past this, because neither key is at the top.
for edit in tool.get("edits") or []:
    if isinstance(edit, dict):
        parts.append(edit.get("new_string") or "")
written = "\n".join(str(part) for part in parts)

# Only what this edit is putting into the file that is not in it already.
#
# The rule arrived after the prose did: 268 tracked files hold a sentence it
# refuses, CLAUDE.md and README among them. Judging the whole payload made
# every one of those files unwritable and every move of such a paragraph
# impossible — and this repo writes one paragraph per line, so moving one is
# an ordinary edit. A refusal exits 2 with no override, so that is not a
# strict guard, it is a file nobody can touch.
#
# Line by line, because a paragraph is a line here: a line already in the file
# is being kept or moved, and one that is not is being written now. It is what
# a person is answerable for, and it leaves the corpus to be corrected a
# sentence at a time rather than all at once or never.
try:
    with open(path, encoding="utf-8") as handle:
        already = set(handle.read().splitlines())
except Exception:
    already = set()
fresh = [line for line in written.splitlines() if line not in already]

# Plural `names` used as a noun, blanked before the match so the shapes below
# are not read as the verb. They are the same trap the singular was, and the
# singular is why bare `name` was dropped from the pattern:
#
#   the account names the file declares   the column names this report prints
#   the tax table names a file states     sorted by the names each account has
#
# Two shapes, both decided by the word in front. A determiner before `names`
# makes it the thing being counted — "the names each", "its names that". And a
# noun this repo pluralises — account, column, field, file, key, table, tag,
# option, command, flag — makes "<noun> names" the subject rather than the act.
#
# It is the seatbelt reasoning again: these are what get typed here, and a
# shape wrongly refused is a defect, while one nobody writes getting past is
# not. `the report names the split` is untouched, `report` being none of these.
import re
BEFORE = (r"(?:the|a|an|its|their|those|these|his|her|our|your|this|that)"
          r"|(?:account|column|field|file|key|table|tag|option|command|flag)s?")
fresh = [re.sub(rf"\b({BEFORE})\s+names\b", r"\1 NOUNS", line, flags=re.I)
         for line in fresh]

# And the other side of the verb: what is being named. The rule is about a
# thing that has no name, so a thing that has one, named, is the correct form
# and has to stay writable — CLAUDE.md keeps the name of an account, of a
# customer, and `name:` in a block, and a guard that refused "naming the
# account" would leave the right sentence the one nobody can type. The nouns
# are the ones this repo gives names to; a basis, a split, a guid, a
# transaction and a lot are not among them, so those are refused as before.
#
# No apostrophes anywhere in this program: it is a single-quoted argument to
# python3 -c, and one would end the string and take the rest of the guard
# with it — measured, every shape was let through, because an empty read is
# an empty payload and an empty payload passes.
HAS_A_NAME = (r"account|customer|vendor|employee|job|file|report|column"
              r"|field|key|table|tag|option|command|flag|book|currency"
              r"|commodity")
DETERMINER = (r"(?:the|a|an|its|their|this|that|these|those|each|every|one"
              r"|both|any|no)")
fresh = [re.sub(rf"\b(?:names|naming)\s+(?:{DETERMINER}\s+)?"
                rf"(?:{HAS_A_NAME})s?\b", "NAMED A NAMED THING", line,
                flags=re.I)
         for line in fresh]
sys.stdout.write("\n".join(fresh))
')

[ -z "$TEXT" ] && exit 0

# The verb, followed by whatever it acts on. A determiner or a pronoun after
# "names"/"naming" is what separates the verb from the noun: "the account
# name" and "by name" have no determiner after them, while "names the split"
# and "naming them" do.
# `names` and `naming` only. Bare `name` was here for the imperative — "name
# the transaction" — and caught far more nouns than verbs: "the account name
# the error prints", "the file name a block states", "the name that GnuCash
# keeps" are all noun-plus-determiner and all correct English. A shape this
# wrongly refuses is a defect, and exit 2 leaves no way past it but editing
# this file, so the rare imperative is the one to give up.
VERB='\b(names|naming)[[:space:]]+(the|a|an|it|its|them|their|that|this|these|those|each|every|which|whichever|one|both|any|no)\b'

OFFENDING=$(printf '%s\n' "$TEXT" | grep -inE "$VERB" | head -5)

[ -z "$OFFENDING" ] && exit 0

{
    echo "REFUSED: \"name\" is used as a verb here, for something that has no name."
    echo
    echo "$OFFENDING"
    echo
    echo "A guid is not a name and neither is a split. Say what is actually"
    echo "printed or done:"
    echo
    echo "  names the split          -> prints the split's guid"
    echo "  naming them              -> lists them, with their dates and amounts"
    echo "  names the transaction    -> gives the transaction's guid"
    echo "  the block names a guid   -> the block gives a guid"
    echo "  a payment names a split  -> a payment applies a split"
    echo "  the guid names the basis -> the guid matches the basis"
    echo
    echo "Keep it where the thing genuinely has a name and the text prints it:"
    echo "an account's name, a customer's name, \`name:\` in a block."
} >&2

exit 2
