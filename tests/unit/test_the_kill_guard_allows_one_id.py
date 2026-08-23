"""`scripts/refuse-unscoped-kills.sh` allows one id, named, one per command.

The guard exists because an agent working in this repo stopped a commit
sweep and then ran `docker ps -q | xargs docker kill` to tidy up after it —
every container on the machine, which took down a web server that had been
up since May along with the ten test containers it meant.

Its header lists the shapes it refuses and the ones it lets through, and a
list in a comment is a claim about behaviour like any other: the shapes
were probed by hand while it was written, which is exactly the evidence
this suite exists to replace. Each row below is one of those shapes.

Reading mostly passes — `grep -rn "docker kill" scripts/` searches for a
string and kills nothing, `cat /tmp/kill` reads a file, `docker stop
--help` asks what a verb does. Behind a word that runs another command it
does not: `sudo cat /tmp/kill` and `… | xargs grep -n kill` are refused as
kills, because what follows `sudo` or `xargs` is read as the command they
run. That cost is deliberate and has rows of its own below; dropping the
runner word is the way through, and refusing to read is the cheaper
mistake of the two.
"""

import json
import subprocess
from pathlib import Path

import pytest

#: From this file rather than from the working directory: the container
#: runs pytest at /workspace, and `scripts/shell.sh` after a `cd` does not
#: — where every case would die in `subprocess` with `FileNotFoundError`
#: rather than say anything about the guard.
GUARD = Path(__file__).resolve().parents[2] / 'scripts' / \
    'refuse-unscoped-kills.sh'

ALLOWED = [
    'kill 1757608',
    'kill -9 1757608',
    'kill -s TERM 1757608',
    'kill -0 1757608 2>/dev/null',
    # Behind a keyword and still one id: the waiting loop a monitor writes.
    # It used to pass because the kill after `while` was never found at
    # all, which is coverage of the hole rather than of the rule.
    'while kill -0 1757608 2>/dev/null; do sleep 20; done',
    'echo do kill',
    '/bin/kill 1757608',
    'sudo kill 1757608',
    'timeout 60 kill 1757608',
    'docker kill gnucash-dev-debian13',
    'docker kill gnucash-dev-debian13 > /dev/null 2>&1',
    'docker stop gnucash-dev-debian13',
    # One image, named — and an image is named with a colon, which the id
    # token has to hold or the ten this repo builds cannot be deleted at
    # all. A flag between the verb and the id is read past, as the flags
    # before the verb are: each of these still names exactly one thing.
    'docker image rm gnucash-dev:debian13',
    'docker rmi gnucash-dev:debian13',
    'docker image rm ghcr.io/org/img:v1',
    'docker stop -t 0 gnucash-dev-debian13',
    'docker kill -s TERM gnucash-dev-debian13',
    'docker rm -f gnucash-dev',
    # `--flag=value` carries its value inline, so it cannot eat the id
    # after it — and the same spelling before the verb was already read
    # past, which made one command two answers.
    'docker stop --time=0 gnucash-dev-debian13',
    'docker rm --force=true gnucash-dev',
    'docker --context=prod stop web',
    # `--timeout` is what `docker stop --help` prints today; `--time` is
    # the deprecated spelling of the same flag. Naming only the old one
    # made the value read as the id and the container as a second.
    'docker stop --timeout 5 gnucash-dev-debian13',
    'docker restart --timeout 5 web',
    # Asking what a verb does kills nothing — and the reader asking is
    # usually the one who just met a refusal and went looking for the
    # flag that would fix it.
    'docker stop --help',
    'docker rm --help',
    'docker kill -h',
    # A flag after the id, and a value attached to its flag. Docker takes
    # its arguments on either side of the id, so a flag with a separate
    # value has to be read past there too — or one command has two
    # answers depending on which side its flag sat.
    'docker rm gnucash-dev -f',
    'docker stop -t0 web',
    'docker stop web -t 5',
    'docker stop web --timeout 5',
    'docker kill web -s TERM',
    # A name that merely ends in one of the sweep words. Unanchored, the
    # check read `web-teardown` as `down`.
    'docker stop web-teardown',
    'docker image rm pandoc-markdown',
    'docker logs gnucash-dev',
    'docker ps --format {{.Names}}',
    'cat /tmp/kill',
    'ls /usr/bin/killer.log',
    './scripts/test.sh latest',
    'timeout 590 ./scripts/test.sh latest',
    'grep -rn "docker kill" scripts/',
    'find . -name kill',
    'bash scripts/test.sh latest',
    'command kill 1757608',
    'A=1 kill 1757608',
    'echo `date`',
    'docker image ls',
    'cd /workspace\n./scripts/test.sh latest',
    # A flag before a verb this guard does not refuse, and a subcommand
    # that is not an object group: `exec` must not read as a container
    # group, or `rm` after it would look like an unnamed removal.
    'docker compose ps',
    'docker exec gnucash-dev rm /tmp/f',
    'docker --context prod kill web',
]

REFUSED = [
    # The command that did the damage, and its relatives. Every verb the
    # guard names, because dropping one from the alternation would leave
    # this file green while `docker ps -q | xargs docker stop` — the
    # incident with one word changed — went through.
    'docker ps -q | xargs -r docker kill',
    'docker ps -q | xargs docker stop',
    'docker kill $(docker ps -q)',
    'docker stop $(docker ps -q)',
    'docker restart $(docker ps -q)',
    'docker kill a b',
    'docker stop a b',
    'docker container prune -f',
    # Every object group with a destructive verb, not just `container`:
    # each of these destroys things nobody named on a shared machine.
    'docker image prune -a',
    'docker volume prune',
    'docker network prune',
    'docker builder prune',
    'docker compose down',
    'docker-compose down',
    # With the flags that sit in front of the verb in practice. This
    # repo's own `scripts/dev-stop.sh` runs `docker compose down`, so the
    # bare spelling was refused while naming the file — the obvious retry
    # after a refusal — was not.
    'docker compose -f docker-compose.yml down',
    'docker-compose -f x.yml down',
    'docker compose -p web down',
    'docker-compose rm -f',
    # A process group is not one id, however few are written down.
    'kill -- -1757608',
    '/bin/kill -- -1757608',
    'sudo kill -- -1757608',
    # Selecting by pattern is not naming an id at all.
    'pkill -f pytest',
    'killall docker',
    '/usr/bin/pkill -f pytest',
    # The shell picking the victims, in each of its spellings — a backquote
    # is its own syntax, not a variant of `$( )`, and a job spec names a
    # job rather than a pid.
    'kill $(pgrep -f pytest)',
    'kill `pgrep -f pytest`',
    'docker kill `docker ps -q`',
    'kill -9 %1',
    'ps -ef | grep pytest | xargs kill',
    'env kill -9 $(pgrep pytest)',
    'timeout 60 kill -- -1757608',
    'nice kill -- -1757608',
    # Behind a shell keyword, which holds a command position as much as a
    # `sudo` does. The first of these is the incident written longhand, and
    # it went through: a keyword matched none of the words the guard knew,
    # so the kill after it was never looked at.
    'for p in $(pgrep -f pytest); do kill $p; done',
    'pgrep -f pytest | while read p; do kill $p; done',
    'if pkill -f pytest; then echo done; fi',
    'while kill -- -1757608; do sleep 1; done',
    'until kill -- -1757608; do sleep 1; done',
    '! kill -- -1757608',
    # More than one, in one command.
    'kill 1757608 1757609',
    'kill 1757608; kill 1757609',
    'kill 1757608; docker kill caddy',
    # A program handed to a shell as a string, where nothing can read it —
    # with `-c` wherever the flags put it. `bash -lc` writes no `-c`
    # substring at all, and the separated forms put a space in front of
    # it; each of those was the whole guard walked past, since what is
    # left after the quoted program is stripped holds no kill.
    'bash -c "docker ps -q | xargs docker kill"',
    'bash -lc "pkill -f pytest"',
    'bash -x -c "docker ps -q | xargs docker kill"',
    'bash --login -c "kill -- -1757608"',
    'sh -c "kill -- -1757608"',
    'sh -eu -c "pkill -f pytest"',
    # A flag with an argument of its own between the shell and its `-c`,
    # which a flag-shaped skip cannot cross.
    'bash -o pipefail -c "docker ps -q | xargs docker kill"',
    'sh -o errexit -c "pkill -f pytest"',
    'bash --rcfile /tmp/f -c "kill -- -1757608"',
    'eval "pkill -f pytest"',
    # A docker verb rather than a kill word inside the string: the check
    # for a program handed to a shell carried its own copy of the verb
    # list, so widening the real one refused `docker image prune -a` and
    # went on allowing it behind a `bash -c`.
    'bash -c "docker image prune -a"',
    'bash -c "docker volume rm x"',
    # A shell named by its path is the same shell, and this one is the
    # incident verbatim. The process side has read a path as part of the
    # name all along — `/bin/kill` and `/usr/bin/pkill` are rows above.
    '/bin/bash -c "docker ps -q | xargs docker kill"',
    'sudo /bin/sh -c "pkill -f pytest"',
    '/usr/bin/bash -lc "kill -- -1757608"',
    # Still unnamed, whatever the verb is called.
    'docker rmi $(docker images -q)',
    'docker rmi a b',
    # Two ids behind a boolean flag, which is the everyday way to remove
    # two running containers — and the shape a generic "flag and maybe an
    # argument" skip swallows, the optional slot taking the first id and
    # leaving the second to read as the only one.
    'docker rm -f alpha beta',
    'docker rm --force a b',
    'docker rmi -f i1 i2',
    'docker container rm -f a b',
    'docker stop -t 0 a b',
    'docker rm --force=true a b',
    'docker stop --timeout 5 a b',
    'docker stop web -t 5 other',
    # A verb fed its ids through a pipe looks exactly like a verb given
    # none, which is why the id stays required and `--help` is answered
    # by name rather than by letting an id-less command through.
    'docker ps -q | xargs docker rm -f',
    'docker rm -f $(docker ps -aq)',
    'docker volume rm $(docker volume ls -q)',
    # `kill 0` signals every process in the caller's own group — the
    # negative-pid family, spelled without the minus.
    'kill 0',
    'kill -9 0',
    # `su -c` is the `sudo /bin/sh -c` above by another name, and `ash`
    # ends in `sh` without starting a word.
    'su -c "pkill -f pytest"',
    'su root -c "kill -- -1757608"',
    'ash -c "pkill -f pytest"',
    'busybox ash -c "kill -- -1757608"',
    # A command of several lines, where the kill is not on the first: the
    # check read the payload with its `\\n` still two characters, so the
    # second line's first word was preceded by an `n` and sat at no
    # command position at all.
    'cd /workspace\nbash -lc "pkill -f pytest"',
    'cd /tmp\ndocker ps -q | xargs docker kill',
    # A runner word with an argument of its own before the command it
    # runs: skipping only flags left these at no command position.
    'sudo -u jimmy kill -- -1757608',
    'env COVERAGE_FILE=/tmp/x pkill -f pytest',
    'command kill -- -1757608',
    'builtin kill -- -1757608',
    'find /proc -maxdepth 1 -name x -exec kill {} ;',
    'find . -execdir pkill -f pytest ;',
    # A `case` arm, a group and a backquote: a command follows `)`, `{` and
    # a backtick as surely as it follows a `;`, and `$(…)` was already a
    # position through its `(` — the two spellings of one substitution were
    # answered differently.
    'case x in *) kill -- -1757608;; esac',
    '{ pkill -f pytest; }',
    'echo `pkill -f pytest`',
    'echo $(pkill -f pytest)',
    # An environment assignment in front of the command, which is the
    # shorter spelling of `env VAR=v pkill …` and was caught by nothing.
    'COVERAGE_FILE=/tmp/x pkill -f pytest',
    'A=1 kill -- -1757608',
    # What the widened runner-word skip costs, written down in the script
    # and pinned here: reading is refused where a runner word precedes it.
    # `grep -rn kill scripts/` with no runner word is in ALLOWED above.
    'sudo cat /tmp/kill',
    'git ls-files | xargs grep -n kill',
    # The shell's way past an alias, which survives the quote-stripping
    # and is neither a path nor a position.
    '\\kill -- -1757608',
]

#: A hook payload carrying a second `command` field, as a nested tool input
#: does. Written with `json.dumps` so the inner one is a real field rather
#: than an escaped mention: `{"description": "a \"command\":\"ls\" decoy"}`
#: never reaches the extractor at all, so a test built on that shape passes
#: whichever field the guard reads and proves nothing.
TWO_FIELDS = [
    ('the kill second',
     {'command': 'ls -la',
      'tool_input': {'command': 'docker ps -q | xargs docker kill'}}),
    ('the kill first',
     {'command': 'docker ps -q | xargs docker kill',
      'tool_input': {'command': 'ls -la'}}),
]


def _run(payload: dict):
    done = subprocess.run([str(GUARD)], input=json.dumps(payload), text=True,
                          capture_output=True, check=False)
    assert done.returncode in (0, 2), (done.returncode, done.stderr)
    return done


def _verdict(command: str) -> bool:
    """`True` where the guard would let the command run."""
    return _run({'command': command}).returncode == 0


@pytest.mark.parametrize('command', ALLOWED)
def test_one_id_named_once_is_allowed(command):
    assert _verdict(command), f'{command!r} should be allowed'


@pytest.mark.parametrize('command', REFUSED)
def test_anything_the_shell_chooses_is_refused(command):
    assert not _verdict(command), f'{command!r} should be refused'


@pytest.mark.parametrize('where,payload', TWO_FIELDS,
                         ids=[row[0] for row in TWO_FIELDS])
def test_a_second_command_field_cannot_hide_a_kill(where, payload):
    """Every `"command"` the payload carries is judged, so a decoy beside
    the real one can add a refusal and cannot hide one.

    Both orders, because picking a single field is picking *which*: the
    first lets a kill hide behind a benign one, the last lets it hide in
    front of one, and the guard's own header says the extraction it
    replaced happened to return the right field by `sed`'s tie-break
    rather than by any rule.
    """
    assert _run(payload).returncode == 2, where


def test_it_says_what_to_do_instead():
    """A guard that only says no teaches nothing."""
    said = _run({'command': 'docker ps -q | xargs docker kill'}).stderr

    assert 'One id, named, one per command' in said, said
    assert 'docker kill gnucash-dev-debian13' in said, said
    # And the way out of a refused *read*, which the two rows above
    # (`sudo cat /tmp/kill`, `… | xargs grep -n kill`) make load-bearing:
    # the guard's advice is the only thing standing between a person and
    # a refusal they cannot explain.
    assert 'Drop the runner word' in said, said


def test_it_is_wired_in_as_a_bash_hook():
    """Every row above is worth nothing if the script is never called.

    The guard reaches a command only through the `PreToolUse` matcher in
    `.claude/settings.json`, which is tracked in git like anything else:
    renaming the script, or dropping its entry, leaves this file green
    against something nothing invokes. That the wiring exists is a claim
    about behaviour too.
    """
    settings = json.loads(
        (GUARD.parents[1] / '.claude' / 'settings.json').read_text())

    wired = [
        hook.get('command', '')
        for entry in settings['hooks']['PreToolUse']
        if entry.get('matcher') == 'Bash'
        for hook in entry.get('hooks', [])
    ]

    assert any(GUARD.name in command for command in wired), wired
    # Its sibling with it: the rsync that carries this file into every
    # test container is justified by *both* guards being wired, so a
    # dropped entry for either one has to fail here.
    assert any('refuse-bash-file-edits.sh' in command
               for command in wired), wired
