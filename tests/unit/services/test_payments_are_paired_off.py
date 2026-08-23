"""Pairing an invoice's payments against the blocks that describe them.

The importer asks one question of a file: does it describe the book it is
being imported into? For payments that is a pairing — every payment the
invoice holds has to be a payment the file states, and what the file states
beyond them is what is being added.

Taking each payment's first match answers a different question. Where one block
names its transaction by guid and another describes the same amount, date and
memo, the described block fits either payment while the named block fits only
its own; claim the described one for the wrong payment and the named one is
left with nothing, so a pairing that exists is reported as none.

Driven here rather than through a book because the losing order is what has to
be exercised, and the lot hands its splits back in the order the payments were
applied — which is the file's own order, so the importer applies them in the
one order greedy matching survives. The rule belongs to the pairing, not to
the order a lot happens to use.
"""

import pytest

from services.gnucash_importer import _pair_off_payments


class FakeBlock:
    """Stands in for a payment directive: it knows which payments it fits."""

    def __init__(self, name, fits):
        self.name = name
        self.fits = fits

    def __repr__(self):
        return f'<block {self.name}>'


@pytest.fixture(autouse=True)
def _match_by_the_fake(monkeypatch):
    """`_single_payment_matches` is what the pairing consults; this replaces
    the answer, not the pairing. What the real one reads off a split and a
    directive is tested against real books elsewhere — here the point is the
    shape of the fit, which is stated directly so the losing case can be.
    """
    monkeypatch.setattr(
        'services.gnucash_importer._single_payment_matches',
        lambda split, block: split in block.fits)


def test_a_block_is_given_up_when_its_holder_can_be_paired_elsewhere():
    """The described block fits both payments; the named one fits only its own.

    Read in order, the first payment takes the described block — the first it
    fits — and the second payment is left with a block naming a transaction
    that is not its own. Taking the described block back and giving the first
    payment the named one pairs both, and that pairing exists, so it has to be
    found.
    """
    retargeted, applied = 'retargeted-split', 'applied-split'
    described = FakeBlock('describes either', {retargeted, applied})
    named = FakeBlock('names the retargeted tx', {retargeted})

    claimed, unclaimed = _pair_off_payments([retargeted, applied],
                                            [described, named])

    assert claimed == 2, 'both payments are described by the file'
    assert unclaimed == [], unclaimed


def test_a_payment_no_block_describes_goes_unpaired():
    """A payment the file does not state is left unpaired, not forced onto one.

    The caller compares `claimed` against how many payments there are, so one
    short is what tells it the file does not describe this invoice.
    """
    described = FakeBlock('describes the first only', {'first'})

    claimed, unclaimed = _pair_off_payments(['first', 'second'], [described])

    assert claimed == 1
    assert unclaimed == []


def test_blocks_beyond_the_payments_come_back_in_the_files_order():
    """What is left over is what is being added, and order is the file's.

    The add-a-payment path applies these in the order it gets them, and a file
    states its payments in the order it means them to be applied.
    """
    first = FakeBlock('first', {'only-payment'})
    second = FakeBlock('second', set())
    third = FakeBlock('third', set())

    claimed, unclaimed = _pair_off_payments(['only-payment'],
                                            [first, second, third])

    assert claimed == 1
    assert [block.name for block in unclaimed] == ['second', 'third']


def test_nothing_to_pair_pairs_nothing():
    assert _pair_off_payments([], []) == (0, [])


def test_a_chain_of_displacements_is_followed_to_the_end():
    """Seating the last payment moves the other two, one after the other.

    A fits every block, B fits the first two, C fits only the first. Taking
    each payment's first fit seats A on block 1 and B on block 2, and then C —
    which fits nothing else — has nowhere to go, though a pairing exists:
    C on 1, B on 2, A on 3.

    Reaching it takes two displacements, not one. C asks for block 1, which
    means moving A; A's next fit is block 2, which means moving B; B's next fit
    is block 3, which is free. A search that gives a block up once but does not
    follow where that leads stops at the first step and reports two of three
    paired.
    """
    block1 = FakeBlock('1', {'A', 'B', 'C'})
    block2 = FakeBlock('2', {'A', 'B'})
    block3 = FakeBlock('3', {'A'})

    claimed, unclaimed = _pair_off_payments(['A', 'B', 'C'],
                                            [block1, block2, block3])

    assert claimed == 3
    assert unclaimed == []
