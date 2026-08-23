"""One release's own notes, for the tests that check a refusal is written up.

A refusal belongs to the release that introduced it and stays there, so a
test cannot anchor to "the newest section" — the sentence would have to be
copied forward into every release after it, or the assertion deleted the
first time a `## v0.5.0` was opened above it.

Reading the whole file instead is the other failure: a sentence surviving
anywhere, in any historical section, satisfies the check forever, and what
these tests exist to catch is a note that outlived the behaviour it
describes. So each test names the release its note belongs to, and reads
that section alone.
"""

from pathlib import Path

NOTES = Path('RELEASE_NOTES.md')


def notes_for(version: str) -> str:
    """The notes under `## <version> …`, up to the next `## ` heading."""
    text = NOTES.read_text(encoding='utf-8')
    heading = f'\n## {version} '
    start = text.find(heading)
    assert start >= 0, f'RELEASE_NOTES.md has no section for {version}'
    rest = text[start + 1:]
    end = rest.find('\n## ')
    return rest if end < 0 else rest[:end]
