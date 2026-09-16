"""The last line of a string is read whether or not a newline follows it.

A file's lines come from the file itself, which hands back the last one with or
without its newline. `parse_string` splits the text on newlines itself, so the
last line, with nothing after it, is the one it has to find on its own.
"""


def test_the_last_line_is_read():
    from services.plaintext_parser import PlaintextParser

    parser = PlaintextParser()
    parser.parse_string('2024-01-01 open Assets\n2024-01-01 open Expenses')

    assert list(parser.accounts) == ['Assets', 'Expenses']
    assert parser.errors == []
