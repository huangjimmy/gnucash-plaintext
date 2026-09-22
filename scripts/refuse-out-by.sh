#!/bin/bash
#
# A `PreToolUse` hook on Write and Edit: refuse "out" used as though it were a
# verb meaning wrong. Wired in `.claude/settings.json`, which is committed for
# exactly this reason.
#
# The rule is the plain-English one in CLAUDE.md. "the page is out by 19.86"
# asks a reader to know that "out" means wrong and that the amount is the size
# of the error, and it withholds the two figures, which are the whole of what
# they want. Write what is true: "the page does not balance: it states 3,771.28
# of assets against 3,791.14 of liabilities and equity", or where only the size
# matters, "the totals differ by 0.01".
#
# **What separates the idiom from ordinary English is the word in front of
# "out", and that is the whole design.** In "laid out by WebKit" the word "out"
# is part of the verb "lay out" — it is a particle, and the sentence is
# correct. The same is true of "worked out by hand", "written back out by the
# exporter", "filtered out by the export", "spelled out by the export". In the
# idiom nothing owns "out" at all: a copula is put in front of it — "is out",
# "was out", "are out", "were out" — as though "out" were itself the verb. That
# is the shape refused here.
#
# "totals out by" is refused beside it, and is the worst of them: a noun is set
# against "out" with no verb anywhere, so the sentence reads as though
# totalling were the act of being wrong.
#
# Measured before this guard was written: 34 lines in this tree hold "out by",
# and 32 are the correct form. A guard on the bare words would refuse thirty
# correct sentences and be turned off within the hour; this one refuses the two
# that are the idiom, and both are ordinary corrections to make.
#
# Exit 2 blocks the call and returns stderr to the agent, so the sentence is
# rewritten before it reaches the file rather than found later in review.
#
# **It is a seatbelt, not a sandbox**, like the guards beside it. It catches
# what gets typed. Someone set on the idiom can spell it another way, and that
# is fine: the point is to catch a habit, not to win an argument. A shape it
# wrongly refuses is a defect; a shape nobody would type getting past it is not.

RAW=$(cat)

# Only the fields that write text into a file. `file_path` is not one of them: a
# path may hold the words, and judging it would block editing this very script.
#
# Two files are exempt, because they quote the shape they refuse and could not
# otherwise say what they are about: this script, and CLAUDE.md, which is where
# the rule is written down. Without that, correcting a word in either one is
# blocked by the rule the file exists to state, which is a shape wrongly
# refused, and those are defects.
TEXT=$(printf '%s' "$RAW" | python3 -c '
import json, sys
try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
tool = payload.get("tool_input") or {}
path = str(tool.get("file_path") or "")
exempt = ("refuse-out-by.sh",
          "CLAUDE.md")
if any(path.endswith(name) for name in exempt):
    sys.exit(0)
parts = [tool.get(key) or "" for key in ("content", "new_string")]
# And every edit of a payload that carries several. A tool shaped as a list of
# edits would otherwise put the whole batch past this, neither key being at the
# top.
for edit in tool.get("edits") or []:
    if isinstance(edit, dict):
        parts.append(edit.get("new_string") or "")
written = "\n".join(str(part) for part in parts)

# Only what this edit puts into the file that is not in it already, for the
# reason the name guard does the same: this repo writes one paragraph per line,
# so moving a paragraph is an ordinary edit, and judging the whole payload would
# make any file holding such a line unmovable. A line already there is being
# kept; a line that is not is being written now, and that is what a person is
# answerable for.
try:
    with open(path, encoding="utf-8") as handle:
        already = set(handle.read().splitlines())
except Exception:
    already = set()
fresh = [line for line in written.splitlines() if line not in already]
sys.stdout.write("\n".join(fresh))
')

[ -z "$TEXT" ] && exit 0

# A copula in front of "out" is the idiom — nothing else owns the word, so it is
# standing in as the verb. `is worked out by` is untouched because the copula is
# followed by "worked": the verb is there and "out" is its particle.
#
# A noun in front of it is the same fault with no copula at all: "puts the totals
# out by that amount".
#
# **Both forms need a quantity after them, and that is what makes this a rule
# about meaning rather than a word list.** "out by" followed by an amount is the
# size of an error, which is the idiom. Followed by anything else it is ordinary
# English, and two different sentences prove it:
#
#   - "the release is out by Friday" — "out" means published, "by Friday" is a
#     deadline. The copula form refused this until the quantity was required, and
#     it is a sentence anybody might write in a probe or a note.
#   - "working the bank figure out by hand" — verb, object, particle, and "by
#     hand" is a manner. Three lines of this tree are that sentence. Syntax cannot
#     separate it from "puts the totals out", which has the same shape; what comes
#     after is the only thing that can.
#
# A shape wrongly refused is a defect, and both of those were found by sweeping
# the tree rather than by argument — the phrasal-verb one before this was wired,
# the deadline one by the review that read it afterwards.
#
# "stdout by default" needs no exception: there is no word boundary inside
# "stdout", so the pattern never reaches it.
QUANTITY='([0-9]|whatever|(a|an|one|two|three|that|this|its|the|the same)[[:space:]]+(cent|cents|penny|pennies|amount|amounts|figure|figures|much|margin|difference))'
COPULA='\b(is|are|was|were|be|been|being|am)[[:space:]]+out[[:space:]]+by[[:space:]]+'"$QUANTITY"
NOUN='\b(totals?|balances?|figures?|sheets?|pages?|sides?|books?|accounts?|sums?|columns?|amounts?)[[:space:]]+out[[:space:]]+by[[:space:]]+'"$QUANTITY"
IDIOM="$COPULA|$NOUN"

OFFENDING=$(printf '%s\n' "$TEXT" | grep -inE "$IDIOM" | head -5)

[ -z "$OFFENDING" ] && exit 0

{
    echo "REFUSED: \"out\" is written here as though it were a verb meaning wrong."
    echo
    echo "$OFFENDING"
    echo
    echo "A reader has to know that \"out\" means wrong and that the amount is the"
    echo "size of the error. State the two figures, or state the difference:"
    echo
    echo "  the page is out by 19.86    -> the page does not balance: it states"
    echo "                                 3,771.28 of assets against 3,791.14 of"
    echo "                                 liabilities and equity"
    echo "  the totals are out by 0.01  -> the totals differ by 0.01"
    echo "  puts the totals out by that amount"
    echo "                              -> leaves the totals disagreeing by that amount"
    echo
    echo "Where a verb owns the word, it is a particle and is untouched: a page is"
    echo "laid out by WebKit, a figure is worked out by hand, a key is written back"
    echo "out by the exporter, output goes to stdout by default."
} >&2

exit 2
