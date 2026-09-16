"""A file indented two ways is refused at the first line that breaks the pattern.

The first indented line sets how the file is indented: with tabs or with
spaces, and how many of them make one level. A later line indented with the
other character, or with a count that is not a whole number of levels, cannot
be placed under anything, so the file is refused there, with the reason.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

CASES = [
    ('a_file_indented_with_spaces_then_a_tab.txt',
     'Invalid indentation in line 10: Expected spaces but found tabs'),
    ('a_file_indented_with_a_tab_then_spaces.txt',
     'Invalid indentation in line 10: Expected tabs but found spaces'),
    ('a_file_indented_two_tabs_a_level_then_three.txt',
     'Invalid indentation in line 10: Found 3 tabs but expected multiple of 2'),
    ('a_file_indented_four_spaces_a_level_then_six.txt',
     'Invalid indentation in line 10: Found 6 spaces but expected multiple of 4'),
]


@pytest.mark.parametrize('fixture, reason', CASES,
                         ids=['spaces-then-a-tab', 'a-tab-then-spaces',
                              'three-tabs-in-twos', 'six-spaces-in-fours'])
def test_the_file_is_refused_at_that_line(tmp_path, fixture, reason):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                      f'tests/fixtures/{fixture}'])

    assert result.exit_code != 0, result.output
    assert reason in result.output, result.output
    assert 'Traceback' not in result.output, result.output
