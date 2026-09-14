"""Records the test process's resident memory before and after every test, to find where a run's memory goes.

Run through `scripts/profile-test-memory.sh`, which starts the container the
way `scripts/test.sh` does and loads this with `PYTEST_ADDOPTS`, and prints a
summary of what it wrote.

Each row is the test id, then resident memory in KiB before its setup and
after its teardown, then the difference. Resident memory that does not fall
does not prove a leak by itself: freed memory can stay with the process.

The last row starts with `#` and counts the GnuCash sessions the run created,
ended and destroyed. A session ended and not destroyed keeps its whole book in
memory until the process exits; that is what grew the suite to 1.7 GB before
`GnuCashRepository.close` destroyed its session (Q-041).
"""

import os

import pytest

_OUT = os.environ.get('MEMORY_PER_TEST_OUT')
_COUNTS = {'created': 0, 'ended': 0, 'destroyed': 0}


def _resident_kib():
    with open('/proc/self/status') as status:
        for line in status:
            if line.startswith('VmRSS:'):
                return int(line.split()[1])
    return 0


def _count_sessions():
    from gnucash import Session

    def counted(method, key):
        def wrapper(self, *args, **kwargs):
            _COUNTS[key] += 1
            return method(self, *args, **kwargs)
        return wrapper

    Session.__init__ = counted(Session.__init__, 'created')
    Session.end = counted(Session.end, 'ended')
    Session.destroy = counted(Session.destroy, 'destroyed')


def pytest_configure(config):
    _count_sessions()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    before = _resident_kib()
    yield
    after = _resident_kib()
    if _OUT:
        with open(_OUT, 'a') as out:
            out.write(f'{item.nodeid}\t{before}\t{after}\t{after - before}\n')


def pytest_sessionfinish(session, exitstatus):
    if _OUT:
        with open(_OUT, 'a') as out:
            out.write('# sessions ' + ' '.join(f'{k}={v}' for k, v in _COUNTS.items()) + '\n')
