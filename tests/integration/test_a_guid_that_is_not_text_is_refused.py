"""A `guid:` the format reads as a truth value or a decimal is refused.

An unquoted all-digit guid keeps the digits it was written with, so it is read
as the guid it is. An unquoted decimal keeps its characters too: `1.5` reaches
the guid check as the text `1.5`, which is no guid, and is refused quoting it.
`True` keeps nothing. It is a truth value, no guid can be read from it and none
can be quoted back, so the import refuses the block and asks for the value in
quotes.
"""

from click.testing import CliRunner

from cli.main import cli


def _imported(tmp_path, fixture):
    return CliRunner().invoke(cli, ['import', '--new', str(tmp_path / 'book.gnucash'),
                                    fixture, '--include-business-objects'])


def test_a_truth_value_is_refused_and_asks_for_quotes(tmp_path):
    result = _imported(tmp_path, 'tests/fixtures/a_customer_whose_guid_is_true.txt')

    assert result.exit_code != 0, result.output
    assert 'guid must be a quoted string (got bool True)' in result.output, result.output


def test_a_decimal_is_refused_as_the_text_it_was_written_as(tmp_path):
    result = _imported(tmp_path, 'tests/fixtures/a_customer_whose_guid_is_a_decimal.txt')

    assert result.exit_code != 0, result.output
    assert "Invalid GUID format: '1.5'" in result.output, result.output
