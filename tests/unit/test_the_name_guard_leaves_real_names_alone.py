"""`scripts/refuse-name-as-a-verb.sh` refuses "name" used of a nameless thing.

A guid is not a name and neither is a split, so "the message names the split"
tells a reader something untrue and sends them looking for a name that is not
there. The rule is in CLAUDE.md; it was written down, agreed to, and broken
again in the same session, which is why there is a hook.

What matters as much is what it leaves alone. A name is a name — an account's,
a customer's, `name:` in a block — and a guard that refused those would be
turned off within the hour. Both halves are asserted here.

`.claude/settings.json` is read to check the hook is actually wired, the way
`test_the_kill_guard_allows_one_id.py` does for the other two: a guard nothing
invokes is not a guard.
"""

import json
import subprocess
from pathlib import Path

import pytest

GUARD = Path('scripts/refuse-name-as-a-verb.sh')
SETTINGS = Path('.claude/settings.json')


def _judge(text, field='content'):
    """Hand the guard one Write or Edit payload; True when it refuses."""
    payload = json.dumps({'tool_input': {field: text}})
    result = subprocess.run([str(GUARD)], input=payload, capture_output=True,
                            text=True)
    assert result.returncode in (0, 2), (result.returncode, result.stderr)
    return result.returncode == 2


REFUSED = [
    'the report names the split',
    'refused, naming them',
    'a block naming a guid',
    'the guid names the cost basis it draws on',
    'it names that transaction and the route that works',
    'the listing names each cost basis',
    'prose is fine until it names it halfway down',
    'naming the transaction it was linked to',
    'naming the lot the payment settled',
]

ALLOWED = [
    'get_account_full_name(account)',
    'the customer name, and the account name beside it',
    'name: "US Customer"',
    'addressed by name rather than by guid',
    'prints the split\'s guid',
    'lists them, with their dates and amounts',
    'the block gives a guid',
    'a payment applies the splits the block gives',
    'the error gives the account\'s name',
    'KNOWN_SPLIT_METADATA_KEYS holds every field name',
    # A noun with a determiner after it, which is ordinary English and reads
    # like the verb to anything matching words alone. These are what cost the
    # bare `name` alternation its place: the imperative it was there for —
    # "name the transaction" — is rare beside them, and a wrong refusal has no
    # way past it but editing the guard.
    'the account name the error prints',
    'the file name a block states',
    'the name that GnuCash keeps',
    'the column name each row is written under',
    'name the transaction it refuses over',
    # The plural of the same shape, which reads to a word-matcher exactly like
    # the verb. A determiner in front, or a noun this repo pluralises, is what
    # separates them.
    'the account names the file declares are all CAD',
    'the column names this report prints',
    'the tax table names a file states',
    'sorted by the names each account carries',
    'its names that the export writes out',
    # The verb doing its correct work: a thing that has a name, named. The
    # rule is about the thing, not about the word, so these are the sentences
    # it exists to keep — and a guard refusing them would leave the right
    # form unwritable.
    'the error naming the account it posts to',
    'a refusal naming the customer',
    'the run names the file it could not read',
    'naming each command it refuses',
]


@pytest.mark.parametrize('text', REFUSED)
def test_the_verb_is_refused(text):
    assert _judge(text), f'let through: {text!r}'


@pytest.mark.parametrize('text', ALLOWED)
def test_a_real_name_is_left_alone(text):
    assert not _judge(text), f'wrongly refused: {text!r}'


def test_an_edit_is_judged_by_what_it_writes():
    """Edit puts its text in `new_string`, Write in `content`."""
    assert _judge('the message names the split', field='new_string')
    assert not _judge('the account name', field='new_string')


def test_the_guard_and_its_test_may_be_edited():
    """Both quote the shape they refuse, so both have to be exempt.

    Without it, correcting a word in either file is blocked by the rule the
    file exists to state, and the only way to change it is to turn the hook
    off. A shape wrongly refused is a defect.
    """
    offending = 'it names the split'
    exempt = (str(GUARD),
              'tests/unit/test_the_name_guard_leaves_real_names_alone.py')
    for path in exempt:
        payload = json.dumps({'tool_input': {'file_path': path,
                                             'new_string': offending}})
        result = subprocess.run([str(GUARD)], input=payload,
                                capture_output=True, text=True)
        assert result.returncode == 0, (path, result.stderr)

    # And no other file gets that exemption.
    payload = json.dumps({'tool_input': {'file_path': 'services/whatever.py',
                                         'new_string': offending}})
    result = subprocess.run([str(GUARD)], input=payload, capture_output=True,
                            text=True)
    assert result.returncode == 2, result.stdout


def test_a_payload_with_no_text_in_it_passes():
    """A Read, or a call whose fields this does not touch, is not its business."""
    result = subprocess.run([str(GUARD)], input='{"tool_input":{}}',
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_malformed_input_does_not_block_the_call():
    """A guard that fails closed on junk stops all work; this one lets it by."""
    result = subprocess.run([str(GUARD)], input='not json at all',
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_hook_is_wired_for_write_and_edit():
    settings = json.loads(SETTINGS.read_text())
    commands = [
        hook['command']
        for entry in settings['hooks']['PreToolUse']
        if 'Write' in entry['matcher'] and 'Edit' in entry['matcher']
        for hook in entry['hooks']
    ]
    assert any(GUARD.name in command for command in commands), settings


class TestALineTheFileAlreadyHolds:
    """Only what an edit puts in that is not in the file already is judged.

    The rule arrived after the prose: hundreds of tracked files hold a
    sentence it refuses, CLAUDE.md and README among them. Judged whole, every
    one of those files became unwritable and every move of such a paragraph
    impossible — and a paragraph here is one line, so moving one is an
    ordinary edit. A refusal exits 2 with no override, which makes that not a
    strict guard but a file nobody can touch.
    """

    def _judge_against(self, tmp_path, held, written):
        target = tmp_path / 'prose.md'
        target.write_text(held)
        payload = json.dumps({'tool_input': {'file_path': str(target),
                                             'new_string': written}})
        result = subprocess.run([str(GUARD)], input=payload,
                                capture_output=True, text=True)
        assert result.returncode in (0, 2), (result.returncode, result.stderr)
        return result.returncode == 2

    def test_a_line_already_there_is_left_alone(self, tmp_path):
        held = 'the report names the split\nand a second line\n'
        assert not self._judge_against(tmp_path, held,
                                       'the report names the split')

    def test_moving_it_beside_new_prose_is_left_alone(self, tmp_path):
        held = 'the report names the split\n'
        assert not self._judge_against(
            tmp_path, held,
            'a heading\nthe report names the split\nsomething ordinary')

    def test_a_new_one_is_still_refused(self, tmp_path):
        held = 'the report names the split\n'
        assert self._judge_against(tmp_path, held, 'the guid names the cost basis')

    def test_a_file_that_is_not_there_yet_is_judged_whole(self, tmp_path):
        target = tmp_path / 'new.md'
        payload = json.dumps({'tool_input': {'file_path': str(target),
                                             'content': 'it names the split'}})
        result = subprocess.run([str(GUARD)], input=payload,
                                capture_output=True, text=True)
        assert result.returncode == 2, result.stderr


def test_the_refusal_says_what_to_write_instead():
    payload = json.dumps({'tool_input': {'content': 'it names the split'}})
    result = subprocess.run([str(GUARD)], input=payload, capture_output=True,
                            text=True)
    assert result.returncode == 2
    # The offending line, so the author can find it, and a replacement.
    assert 'it names the split' in result.stderr, result.stderr
    assert "prints the split's guid" in result.stderr, result.stderr
