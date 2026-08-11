"""The one date option every report and every surgical command takes.

Five commands each carried their own copy of this callback, which is how they
came to answer a mistyped date two different ways, and how one of them ended up
with an arm nothing could reach: a copy attached only to a required option can
never be handed `None`, while the same code beside an optional one is handed it
on every run that leaves the option off.
"""

from datetime import date, datetime
from typing import Optional

import click


def parse_date(ctx, param, value: Optional[str]) -> Optional[date]:
    """A `YYYY-MM-DD` option, as a date — or a refusal that quotes what came.

    `None` for an option that was not given, which click hands over for every
    optional one; a required option is refused by click before this is asked.
    """
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise click.BadParameter(
            f"Date must be in YYYY-MM-DD format, got: {value}") from e
