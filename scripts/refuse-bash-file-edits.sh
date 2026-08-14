#!/bin/bash
#
# A `PreToolUse` hook on Bash, for anyone working in this repo with an agent: refuse a shell command that edits or writes a file. Wired in `.claude/settings.json`, which is committed for exactly this reason.
#
# Files are changed with the Read and Edit tools and created with Write, so that every change arrives as a deliberate diff the author reviews. A `sed -i` sweep, or a `python3 - <<EOF … path.write_text(t)` heredoc, applies unreviewed substitutions across a file — usually several files in one call — and a mistake in one of them is invisible until it has already landed everywhere. Asking for this in CLAUDE.md was not enough on its own; the rule was written down, agreed to, and broken dozens of times in a single session, which is why it is a hook.
#
# Exit 2 blocks the call and returns stderr to the agent, so it re-does the change with Read/Edit rather than being told afterwards.
#
# Deliberately NOT refused: reading (`sed -n`, `grep`, `awk` printing to stdout), running a script that a Write call created, `python3 -m …`, and redirecting to /dev/null.
#
# Three things the matching has to get right, each of which was wrong at some point and let a real command through or blocked a harmless one:
#
# 1. **The command arrives JSON-escaped and is examined decoded.** A multi-line command is one JSON string whose newlines are the two characters `\` and `n`, so matched as it arrives it is a single line and only its *first* command is ever at the start of one — `cd services\nsed -i …` sailed through. The escapes are turned back into the characters they stand for before anything is matched, and `grep` then sees each line of the command as a line.
#
# 2. **Quoted text is not the command.** `grep -rn "sed -i" docs/` searches for a string and writes nothing; `printf 'cat > x'` prints one. Both were refused. Quoted runs are removed before matching, so what is left is the shell's own words. The cost is that a violation *inside* quotes — `bash -c 'sed -i …'` — is not seen, which is the right way round: a guard that blocks reading is one that gets turned off.
#
# 3. **Every pattern is anchored to a command position** — the start of a line, or just after `|`, `;`, `&&`, `||` or `(` — so a tool named in an argument is not mistaken for a tool being run.

RAW=$(cat)

# The `command` field alone, not the JSON tail after it: `"command":"…"` followed by `"description":"…sed -i…"` would otherwise be matched on the description. Backslash escapes are consumed as a unit so an escaped quote inside the command does not end it early.
COMMAND=$(printf '%s' "$RAW" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(\([^"\\]\|\\.\)*\)".*/\1/p')

# `\"` back to `"`, so the quoted runs below can be found at all.
COMMAND=${COMMAND//\\\"/\"}

# Quoted runs removed while the command is still one line — a `\n` inside a quoted string belongs to that string, and decoding first would turn it into a line of its own that looks like a command.
UNQUOTED=$(printf '%s' "$COMMAND" | sed "s/'[^']*'//g; s/\"[^\"]*\"//g")

# Now the escapes: `\n` becomes a newline, and `grep` reads each command in a sequence as its own line.
UNQUOTED=$(printf '%b' "$UNQUOTED")

# A command position: the start of a line, or after a separator.
AT_START='(^|[|;&(]|&&|\|\|)[[:space:]]*'

matches() {
    printf '%s\n' "$UNQUOTED" | grep -qE "$AT_START$1"
}

reject() {
    echo "REFUSED: $1" >&2
    echo "" >&2
    echo "Files are edited with Read + Edit, and created with Write — never through a shell command. Re-do this as Edit calls, one occurrence at a time." >&2
    exit 2
}

# In-place editors, whatever the language. `sed -n` and a bare `sed` filtering a pipe are untouched.
if matches 'sed[[:space:]]+[^|;&]*(-i|--in-place)'; then
    reject "\`sed -i\` edits a file in place."
fi
if matches 'perl[[:space:]]+-[^|;&]*i'; then
    reject "\`perl -i\` edits a file in place."
fi

# A Python program read from stdin or `-c`, in any of its spellings: `python3 -c …`, `python3 - <<EOF`, `python3 <<EOF`, and a bare `python3` at the end of a pipeline — all four read the program from somewhere other than a file, which is how a batch of unreviewed edits arrives. `python3 -m …` and `python3 script.py` name something and are left alone.
if matches '(python|python3)([[:space:]]*$|[[:space:]]+(<<|-([[:space:]]|c|$)))'; then
    reject "a Python program passed on the command line or through a heredoc is how a batch of unreviewed edits gets applied."
fi

# Writing a file through the shell rather than through Write/Edit.
if matches '(cat|tee|printf|echo)[^|]*>>?[[:space:]]*[^ &]' \
   && ! printf '%s\n' "$UNQUOTED" | grep -qE '>>?[[:space:]]*/dev/null'; then
    reject "this writes a file through the shell. Use the Write tool to create one and Edit to change one."
fi

exit 0
