#!/bin/bash
#
# A `PreToolUse` hook on Bash, beside `refuse-bash-file-edits.sh`: nothing may be killed except one id, named, one per command. Containers and processes alike. Wired in `.claude/settings.json`.
#
# The machine that runs this suite runs other things. On 2026-08-21 an agent stopped a commit hook mid-sweep and then ran `docker ps -q | xargs docker kill` to clean up after it — `docker ps -q` is every container on the machine, so the kill took down the author's web server, up since May, along with the ten test containers it meant. It had looked at the first ten names through `head` and never seen the server in the list.
#
# The rule that would have prevented it is not "no kills" but "one id, one time". `docker kill gnucash-dev-debian13` and `kill 1757608` are decisions about one thing, made by someone who knows which one. `docker ps -q | xargs docker kill`, `kill $(pgrep -f pytest)`, `pkill -f docker`, `kill -- -1757608`, two kills in one command and `docker container prune` all hand the choice of victims to the shell, and the author's server is in the list every time nobody looked.
#
# So: one literal id, once. Refused otherwise — no command substitution, no pipe into `xargs`, no `pkill`/`killall` (they select by pattern, never by id), no negative pid (that is a process *group*, however few ids are written down), no second id, no second kill in the same command, no `prune`, no `compose down`.
#
# A signal may be given: `kill -9 1757608`, `kill -TERM 1757608`, `kill -s TERM 1757608`. `kill -0 1757608` sends nothing and is how a script asks whether a pid is still alive, which the same shape allows.
#
# **This is a seatbelt, not a sandbox, and the goal is not to close every loophole.** A guard that reads text cannot: a quoted command word (`'pkill' -f x`) loses its verb to the same stripping that lets `grep -rn "docker kill"` be read, and no amount of alternation fixes that. What it is for is the command a careless hand actually types — the one above was typed by an agent tidying up after itself, not by anyone getting past anything.
#
# What *would* settle it is not a better regex: run the command in a throwaway container holding the same folder tree and look at what died. That is the only way to know what a command does rather than what it looks like, and it is worth building the day this guards something that matters more than one developer's afternoon. It is not worth it for this, which is why the answer here is text and the limits of text are written down instead of papered over.
#
# One consequence worth knowing rather than discovering: the shell-string check is two scans of the whole command joined by "and", so a *compound* command that both hands a shell a program and names a docker verb is refused even when neither half is a kill — `docker stop web && docker run … img bash -c "pytest"` is. Splitting it in two runs it. That is bluntness rather than a mistake, and it is the same bluntness as "one kill per command": a command doing several things at once is one this cannot read carefully.
#
# So the two kinds of gap are not worth the same. **A shape it refuses that someone legitimately needs is a defect**: widening this file has twice done that — `docker image rm gnucash-dev:debian13`, which is the only way to delete an image this repo builds, and `docker rm -f a b`, which is how a person removes two named containers — and each cost more than the hole it was closing. **A shape that gets past it and that nobody would type is not**: `su root -c`, `busybox ash -c` and their like are answered by saying so rather than by another alternation, because every alternation is a chance to refuse something real. Fix what is typed here; leave the rest written down.
#
# What this costs, and why it is worth it: a detached commit hook can no longer be stopped by killing its process group, so its children — the ten `docker run` clients of a sweep — outlive the parent by up to a few minutes. That is the whole cost, because `scripts/test.sh` runs every container with `--rm`, so they remove themselves as they exit. Killing the parent by id and waiting is the supported way to stop a sweep.
#
# Exit 2 blocks the call and returns stderr to the agent.
#
# The container side is matched anywhere in the command, because the form that did the damage puts its verb in an argument: `docker ps -q | xargs docker kill`. The process side needs a command position — with a path, a `sudo`, an `env`, a `time` or an `xargs` in front of it — because a bare word boundary refused `cat /tmp/kill`, a file that happens to be named that, while anchoring it without a path let `/bin/kill -- -1757608` through: the same process-group kill by its full path.
#
# Quoted runs are removed first, so a command that merely *names* one of these — `grep -rn "docker kill" scripts/` — is not refused. That is also the one way past this guard, since `bash -c "docker ps -q | xargs docker kill"` is entirely quoted, so a shell handed a program as a string is refused outright when the string holds a kill.
#
# **Every `"command"` field in the payload is judged, not one.** Picking a single field means picking which — first or last — and either can be the wrong one when a second `"command":"…"` appears inside another string, so a decoy would decide what the guard reads. Measured on this build, the extraction returned the real command in every decoy shape tried, including a decoy longer than it; that is `sed`'s tie-break rather than a guarantee, and a guard should not rest on one. Judging all of them, a decoy can only add a refusal, never hide one.

RAW=$(cat)

reject() {
    echo "REFUSED: $1" >&2
    echo "" >&2
    echo "One id, named, one per command -- \`docker kill gnucash-dev-debian13\`, \`kill 1757608\`. Anything that lets the shell pick the victims is refused: \$( ), xargs, pkill/killall, a negative pid, a second id, a second kill in the same command, prune, compose down." >&2
    echo "" >&2
    echo "This machine runs containers and processes that are not this project's; \`docker ps -q | xargs docker kill\` has already killed the author's web server once." >&2
    echo "" >&2
    echo "A sweep rarely needs stopping at all: scripts/test.sh runs every container with --rm, so an abandoned one clears itself within minutes. Kill the detached git commit by its own pid and let its children finish." >&2
    echo "" >&2
    echo "If you were reading rather than killing -- \`sudo cat /tmp/kill\`, \`… | xargs grep -n kill\` -- a word after \`sudo\`, \`xargs\` or their like is read as the command they run, so a file or pattern named \`kill\` lands here. Drop the runner word: \`grep -rn kill scripts/\` passes." >&2
    exit 2
}

# Everything that stops or destroys a container, through to the end of its own command in the sequence. `[^;&|]*` stops at a separator, so `… | xargs docker kill` yields an occurrence with no id after it, which is refused below for having none.
# `docker-compose` as well as `docker compose`: the v1 binary is hyphenated and is still installed on plenty of machines, and `docker-compose down` stops every container the file describes.
# Every object group with a destructive verb, not only `container` and
# `system`: the header says "no `prune`", and `docker image prune -a`,
# `docker volume prune`, `docker network prune` and `docker builder prune`
# each destroy things on a shared machine that nobody named, which is the
# class this exists for.
#
# And the flags that sit in front of either: `docker compose -f x.yml
# down`, `docker compose -p web down` and `docker --context prod kill web`
# put a flag — with an argument of its own — between the words this looked
# for, and matched nothing at all. That is not theoretical here: this
# repo's own `scripts/dev-stop.sh` runs `docker compose down`, so the bare
# spelling was refused and naming the file, which is the obvious retry,
# was not. Flag-shaped rather than any word, because `docker exec
# gnucash-dev rm /tmp/f` would otherwise read as an `rm` naming no
# container.
DOCKER_FLAGS='(-[^[:space:];&|]+[[:space:]]+([^-][^[:space:];&|]*[[:space:]]+)?)*'
DOCKER_VERBS='docker(-compose)?[[:space:]]+'"$DOCKER_FLAGS"'((container|compose|system|image|volume|network|builder|buildx)[[:space:]]+'"$DOCKER_FLAGS"')?(kill|stop|rmi|rm|restart|prune|down)'

# A redirection after the id, which says nothing about what is killed: `kill -0 1757608 2>/dev/null` is how a loop asks whether a pid is alive, and reading the `2>/dev/null` as a second target refused it.
REDIRECTS='([[:space:]]*[0-9]*>&?[[:space:]]*[^[:space:]>]*)*[[:space:]]*$'

# One literal id, and only one: a token of the characters a container or
# image name is made of. `$(…)`, a backquote and a second id all fail it.
#
# The flags read past *here* are named rather than shaped: a generic
# "flag and maybe an argument" skip has an optional slot, and where the
# flag is boolean that slot eats the first id — `docker rm -f alpha beta`
# then read as one named container and was allowed, which is two
# containers destroyed by a command the sibling rule refuses in every
# other spelling (`docker rm a b`, `docker kill a b`). The flags docker's
# destructive verbs take an argument for are these two, in both their
# spellings: `--timeout` is what `docker stop --help` prints today and
# `--time` is the deprecated form, and naming only the old one meant the
# value `5` read as the id and the container's name as a second — one
# flag, four spellings, two answers. Every other flag takes no argument,
# so it consumes nothing but itself.
#
# The `--flag=value` spelling gets its own arm rather than a looser one:
# it carries its value inline, so it cannot eat the id after it the way a
# generic skip did, and `docker stop --time=0 web` was otherwise refused
# for naming one container — while `docker --context=prod stop web`, the
# same spelling on the other side of the verb, was allowed.
PRE_ID_FLAGS='((-s|--signal|-t|--time(out)?)[[:space:]]+[^[:space:];&|]+[[:space:]]+|-[A-Za-z-]+=[^[:space:];&|]*[[:space:]]+|--?[A-Za-z][A-Za-z0-9-]*[[:space:]]+)*'

# Flags after the id. One that comes last is skipped by nothing requiring
# a trailing space, so `docker rm web -f` was refused for naming no
# container while `docker rm -f web` passed.
#
# The id itself stays *required*: making it optional so `docker stop
# --help` would pass allowed `docker ps -q | xargs docker rm -f` too,
# which is the incident — a verb fed its ids through a pipe looks exactly
# like a verb given none. Asking for the manual is handled where the
# occurrence is judged, by the one thing that tells them apart, which is
# the word `--help`.
#
# With the same named value-taking arm the pre-id flags have, since
# docker takes its arguments on either side of the id: `docker stop web
# -t 5` and `docker kill web -s TERM` left the value stranded and were
# refused, so one command had two answers depending on which side of the
# id its flag sat — the asymmetry `--flag=value` was given its own arm to
# end.
TRAILING_FLAGS='([[:space:]]*((-s|--signal|-t|--time(out)?)[[:space:]]+[^[:space:];&|-][^[:space:];&|]*|--?[A-Za-z][A-Za-z0-9-]*(=[^[:space:];&|]*)?))*'

# `:`, `/` and `@` are in it because an image is named with them, and
# widening the verbs above to cover `docker image rm` without widening
# this refused `docker image rm gnucash-dev:debian13` — the id stopping at
# the colon — which is how every image this repo builds is named, on the
# machine the guard exists to keep other people's things on. A flag before
# the id (`docker stop -t 0 web`, `docker kill -s TERM web`) is read past
# for the same reason the flags before the verb are.
DOCKER_ONE_ID="^$DOCKER_VERBS"'[[:space:]]+'"$PRE_ID_FLAGS"'[A-Za-z0-9][A-Za-z0-9_.:@/-]*'"$TRAILING_FLAGS$REDIRECTS"

# A signal, optionally, then exactly one positive pid. `-- -123` and `-123` are process groups and fail it; so does `$(…)`, a second pid, and a `%1` job spec.
#
# `[1-9][0-9]*` rather than `[0-9]+`, because `kill 0` signals every
# process in the caller's own group — the thing the negative-pid family is
# refused for, spelled without the minus.
PROC_ONE_ID='^(kill)([[:space:]]+-(s[[:space:]]+)?[A-Za-z0-9]+)?[[:space:]]+[1-9][0-9]*'"$REDIRECTS"

# A command position for the process side: the start, after a separator, or after one of the words that run another command. A path in front is part of the name, so `/bin/kill` is the same kill; a path in an *argument* is not, which is what `cat /tmp/kill` is.
# The words that run another command. `timeout` is the one people actually write in front of a kill, and `time` does not cover it — `time` matches only up to the space after it, so `timeout 60 kill -- -1757608` sat at no command position at all and went through. `nice`, `ionice`, `stdbuf` and `doas` are the same shape.
# A word that runs another command, and whatever it is given before the
# command it runs: `sudo -u jimmy kill …` and `env VAR=v pkill …` put a
# word between the two that is neither a flag nor a digit, and skipping
# only flags left those kills at no command position at all. `command` and
# `builtin` are the same class of word and were missing outright.
#
# What that costs is reading: `sudo cat /tmp/kill`, and `… | xargs grep -l
# kill` or `… | xargs grep -n killall`, are refused as kills. A file or a
# pattern named `kill` is a strange thing to have, `grep -rn kill scripts/`
# with no runner word in front of it still passes, and refusing to read is
# cheaper than missing a kill — but the cost is more than one contrived
# path and is written down here as such.
RUNS_ANOTHER='(sudo|doas|env|time|timeout|nice|ionice|stdbuf|nohup|setsid|xargs|exec|command|builtin)[[:space:]]+([^[:space:];&|]+[[:space:]]+)*'
# A shell keyword holds a command position too, and none of the above
# matches one — so `for p in $(pgrep -f pytest); do kill $p; done`, which is
# the incident written longhand, was never even looked at. So were `pkill`
# behind an `if` and a process-group kill behind a `while`.
KEYWORDS='(do|then|else|elif|while|until|if|!)[[:space:]]+'
# An environment assignment in front of a command is a command position
# too, and the shorter spelling of the one above: `env VAR=v pkill …` was
# caught by the runner word and `VAR=v pkill …` by nothing at all.
ASSIGNMENT='[A-Za-z_][A-Za-z0-9_]*=[^[:space:];&|]*[[:space:]]+'
# `)` closes a `case` arm and `{` opens a group, and a command follows each
# as surely as it follows a `;` — `case x in *) kill -- -PID;; esac` and
# `{ pkill -f pytest; }` sat at no position the guard knew. A backquote
# opens a command too: `$(…)` was a position through its `(` while
# `` `pkill -f x` `` was none, so the two spellings of one substitution
# were answered differently.
# `find … -exec kill {} \;` runs a command too, and `-exec` is preceded by
# a space rather than by any of the above — so it is a position of its own.
# `\\?` before the word: `\kill -- -PID` is the shell's way of bypassing an
# alias, it survives the quote-stripping above, and a backslash is neither
# a path nor a position — so it matched nothing. The *quoted* command word
# is the limit this cannot reach: `'pkill' -f pytest` loses its verb to the
# stripping, as `bash -c "…"` does, and is caught by neither. A guard on
# text has that edge; the header says so rather than implying otherwise.
PROC_POSITION='(^|[|;&({)`]|&&|\|\||[[:space:]]-execdir|[[:space:]]-exec)[[:space:]]*('"$RUNS_ANOTHER"'|'"$KEYWORDS"'|'"$ASSIGNMENT"')*\\?([^[:space:];&|]*/)?'

occurrences_of() {
    printf '%s\n' "$1" | grep -oE "$2[^;&|]*"
}

judge() {
    local COMMAND=$1

    # `\"` back to `"`, so the quoted runs below can be found at all.
    COMMAND=${COMMAND//\\\"/\"}

    # Quoted runs removed while the command is still one line, then the escapes decoded.
    local UNQUOTED
    UNQUOTED=$(printf '%s' "$COMMAND" | sed "s/'[^']*'//g; s/\"[^\"]*\"//g")
    UNQUOTED=$(printf '%b' "$UNQUOTED")

    # The same escapes decoded with the quotes left in, for the check
    # below: it anchors on the start of a line, and in a command of
    # several lines the `\n` is still two characters here — so the second
    # line's first word is preceded by an `n`, which is no anchor, and
    # `cd /workspace` + newline + `bash -lc "pkill -f pytest"` was never
    # looked at.
    local DECODED
    DECODED=$(printf '%b' "$COMMAND")

    # A shell handed a program as a string is the one way past the
    # stripping above: the whole of `bash -c "docker ps -q | xargs docker
    # kill"` is a quoted run, so nothing of it survives to be matched.
    # What the stripping is for is a command that merely *names* one of
    # these — `grep -rn "docker kill" scripts/` — and a shell being handed
    # one is not that.
    # `-c` wherever the words before it put it: `bash -lc "…"` writes no
    # `-c` substring at all; `bash -x -c "…"`, `bash --login -c "…"` and
    # `sh -eu -c "…"` put a space between the flag run and it; and
    # `bash -o pipefail -c "…"`, `bash --rcfile /tmp/f -c "…"` put a flag's
    # *argument* between the two, which a flag-shaped skip cannot cross —
    # the same lesson `RUNS_ANOTHER` learned below. Each of those was the
    # whole guard walked past, since the quoted program is then stripped
    # and what is left holds no kill.
    # A shell named by its path is the same shell: `/bin/bash -c "docker
    # ps -q | xargs docker kill"` is the incident verbatim and matched
    # nothing, the anchor sitting immediately before the name. The process
    # side has read a path as part of the name all along.
    #
    # `$DOCKER_VERBS` itself, not a second spelling of it: the copy here
    # knew only `container|compose|system`, so widening the first to cover
    # `image|volume|network|builder` refused `docker image prune -a` and
    # went on allowing `bash -c "docker image prune -a"` — the inversion
    # this whole branch exists to prevent.
    if printf '%s\n' "$DECODED" | grep -qE '(^|[|;&( ])([^[:space:];&|]*/)?((ba|z|k|da|a)?sh|su)([[:space:]]+[^[:space:];&|]+)*[[:space:]]+-[A-Za-z]*c([[:space:]]|$)|(^|[|;&( ])eval([[:space:]]|$)' \
       && printf '%s\n' "$DECODED" | grep -qE "$DOCKER_VERBS"'|(^|[^[:alnum:]_])(kill|pkill|killall)([^[:alnum:]_]|$)'; then
        reject "a kill inside a string handed to a shell, where nothing can read what it will do."
    fi

    local FOUND=()
    local occurrence
    while IFS= read -r occurrence; do
        [ -n "$occurrence" ] && FOUND+=("$occurrence")
    done < <(occurrences_of "$UNQUOTED" "$DOCKER_VERBS")

    # The container verbs out of the way, so the `kill` inside `docker
    # kill` is not read twice — and so `pkill` is not mistaken for one.
    local PROCESSES
    PROCESSES=$(printf '%s\n' "$UNQUOTED" | sed -E "s/$DOCKER_VERBS/docker-verb/g")
    while IFS= read -r occurrence; do
        [ -n "$occurrence" ] && FOUND+=("$occurrence")
    done < <(occurrences_of "$PROCESSES" "$PROC_POSITION"'(kill|pkill|killall)([[:space:]]|$)' \
             | sed -E 's/^.*[^A-Za-z0-9_-](kill|pkill|killall)/\1/; s/^[^kp]*//')

    # One id, one time. A command carrying two of these is a sweep written
    # out longhand, and the second is as unreviewed as an `xargs` would be.
    if [ "${#FOUND[@]}" -gt 1 ]; then
        reject "this kills ${#FOUND[@]} things in one command."
    fi

    for occurrence in "${FOUND[@]}"; do
        occurrence="${occurrence%"${occurrence##*[![:space:]]}"}"
        case "$occurrence" in
        pkill*|killall*)
            reject "\`$occurrence\` selects by pattern, so what it kills is whatever matches at the time." ;;
        docker*)
            # Asking what a verb does kills nothing, and the reader who
            # asks is usually the one who just met a refusal: answered
            # "does not name exactly one container", they get the same
            # refusal for looking up the flag that would fix it.
            if printf '%s\n' "$occurrence" \
                | grep -qE '(^|[[:space:]])(--help|-h)([[:space:]]|$)'; then
                continue
            fi
            # Anchored on the left as well, or a name *ending* in one of
            # them is read as one: `docker stop web-teardown` and `docker
            # image rm pandoc-markdown` name exactly one thing and were
            # refused for acting on whichever were there.
            if printf '%s\n' "$occurrence" \
                | grep -qE '(^|[[:space:]])(prune|down)([[:space:]]|$)'; then
                reject "\`$occurrence\` acts on whichever of them are there — containers, images, volumes, networks — not on one you named."
            fi
            if ! printf '%s\n' "$occurrence" | grep -qE "$DOCKER_ONE_ID"; then
                reject "\`$occurrence\` does not name exactly one container."
            fi ;;
        *)
            if ! printf '%s\n' "$occurrence" | grep -qE "$PROC_ONE_ID"; then
                reject "\`$occurrence\` does not name exactly one pid."
            fi ;;
        esac
    done
}

# Every `"command"` field the payload carries, judged in turn: a decoy can
# add a refusal and cannot hide one. Backslash escapes are consumed as a
# unit so an escaped quote inside a command does not end it early.
while IFS= read -r field; do
    [ -n "$field" ] || continue
    judge "$(printf '%s' "$field" \
        | sed -E 's/^"command"[[:space:]]*:[[:space:]]*"//; s/"$//')"
done < <(printf '%s' "$RAW" \
    | grep -oE '"command"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"')

exit 0
