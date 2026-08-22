r"""What a quoted value may hold, and what comes back.

The writers put a value between quotes and the reader slices a line from its
first quote to its last and unescapes what is between. That pair has to be
symmetric or a book and its ledger disagree quietly: the comparison that
decides `unchanged` reads the same field, so a value that comes back changed
makes its invoice rebuild on every import — and a posted one is unposted,
its entries destroyed, and posted again under a new transaction each time.

Three characters need escaping and the third is the one that used to be
missed. A quote and a backslash corrupt the *value*. A newline corrupts the
*block*: the reader is one line per key, so a raw newline ends the value
mid-word and hands the rest of it to the parser as a key of its own.
Escaping two of the three is worse than escaping none, because the result
looks like a format that handles its own text.
"""

import pytest

from infrastructure.gnucash.utils import (
    decode_value_from_string,
    encode_value_as_string,
    escape_string,
    unescape_string,
)

VALUES = [
    'plain text with nothing to escape',
    'a quote: "Schedule A"',
    'a backslash: C:\\name',
    'both: "C:\\name"',
    'a newline:\nthe second line',
    'two newlines:\n\nand text after',
    'a carriage return:\rand text after',
    'windows line ending:\r\nand text after',
    'a trailing backslash: C:\\',
    'an escape that is not one: \\q',
    'every one of them: "a"\\b\nc\rd',
]


class TestTheRoundTrip:
    @pytest.mark.parametrize('value', VALUES)
    def test_a_value_comes_back_as_it_went_out(self, value):
        assert unescape_string(escape_string(value)) == value

    @pytest.mark.parametrize('value', VALUES)
    def test_and_through_the_encoder_the_writers_use(self, value):
        assert decode_value_from_string(encode_value_as_string(value)) == value


class TestWhatTheWrittenLineLooksLike:
    def test_a_newline_is_written_as_two_characters(self):
        """Which is the point: the value stays on one line, so the block
        stays a block and the reader still finds one key per line."""
        written = encode_value_as_string('first\nsecond')

        assert written == '"first\\nsecond"'
        assert '\n' not in written

    def test_a_carriage_return_likewise(self):
        assert encode_value_as_string('first\rsecond') == '"first\\rsecond"'

    def test_a_quote_and_a_backslash_are_escaped_singly(self):
        assert encode_value_as_string('say "hi"') == '"say \\"hi\\""'
        assert encode_value_as_string('C:\\name') == '"C:\\\\name"'


class TestWhyTheReaderScansRatherThanReplaces:
    r"""A chain of `replace` calls cannot carry more than one escape.

    `C:\\name` is what a value holding one backslash before an `n` is written
    as. Unescaped by `\\`→`\` and then `\n`→newline, the backslash that was
    already part of the value is read a second time, as an escape, and the
    value comes back as `C:` and a newline. Reading left to right, each
    backslash consumes exactly the character after it.
    """

    def test_a_backslash_before_an_n_is_not_a_newline(self):
        assert unescape_string('C:\\\\name') == 'C:\\name'

    def test_and_the_value_that_wrote_it_round_trips(self):
        assert escape_string('C:\\name') == 'C:\\\\name'
        assert unescape_string(escape_string('C:\\name')) == 'C:\\name'

    def test_the_two_spellings_whose_meaning_changed(self):
        r"""`\n` and `\r` meant nothing before this release and mean a
        newline and a carriage return now. A ledger written by an earlier
        release — whose invoice writers wrote values raw — can hold `C:\new`
        meaning a path, and it reads as a newline from here. RELEASE_NOTES
        says so and says how to find it; this is the behaviour it describes.
        """
        assert unescape_string('C:\\new') == 'C:\new'
        assert unescape_string('Order\\ref') == 'Order\ref'
        # Doubled — which is what every writer produces now — it stays a path.
        assert unescape_string('C:\\\\new') == 'C:\\new'

    def test_an_unknown_escape_keeps_both_characters(self):
        """A hand-written file that never meant an escape keeps its text
        rather than losing a character to a rule it did not know about."""
        assert unescape_string('\\q') == '\\q'
        assert unescape_string('ends with a backslash \\') == \
            'ends with a backslash \\'
