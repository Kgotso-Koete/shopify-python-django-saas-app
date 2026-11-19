"""
Fork addition (WhatsApp plan, 2026-11-07): counts each user story's passing tests, by kind of test, for the
"Tests passing" column of the plan's user stories file (docs/superpowers/plans/user-stories/).

A test names the stories it proves with a marker, on the test, its class, or the whole file:

    pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D5.SC.J1.A2")]

    @pytest.mark.story("WA.D5.SC.J1.A2", "WA.D5.SC.J1.A3")
    def test_...

Its kind comes from the "Kind of test:" line of its file's docstring (agents.md section 2.5): backend unit
(BU), integration (BI), sanity (BS) or smoke (BSm). After any run that included marked tests, the terminal
ends with one line per story, such as `WA.D5.SC.J1.A2: 8/8 (BU), 14/14 (BI)`, passed out of run. The
frontend's counts (FU, FI) come from Jest's results, counted by `scripts/user-story-tests.js`. A test that
failed or errored counts in the total and not in passed; a skipped test counts in neither.

Test-support code, so it has no tests of its own (agents.md section 2.1).
"""

import re
from collections import defaultdict

KIND = re.compile(r"Kind of test:\s*(sanity|unit|integration|smoke)", re.IGNORECASE)
LETTERS = {"unit": "BU", "integration": "BI", "sanity": "BS", "smoke": "BSm"}
ORDER = ["BU", "BI", "BS", "BSm"]

# story id -> kind letter -> [passed, run]
_counts = defaultdict(lambda: defaultdict(lambda: [0, 0]))
# test node id -> (story ids, kind letter), for the tests that carry the marker
_marked = {}
# test node ids already counted, so a test's setup, call and teardown reports count once
_done = set()


def pytest_configure(config):
    config.addinivalue_line("markers", "story(*ids): the user story IDs this test proves (tests/user_stories.py)")


def _kind(item) -> str:
    module = getattr(item, "module", None)
    match = KIND.search((module.__doc__ or "") if module else "")
    return LETTERS[match.group(1).lower()] if match else "?"


def pytest_collection_modifyitems(items):
    for item in items:
        ids = sorted({story for mark in item.iter_markers("story") for story in mark.args})
        if ids:
            _marked[item.nodeid] = (ids, _kind(item))


def pytest_runtest_logreport(report):
    if report.nodeid not in _marked or report.nodeid in _done:
        return
    if report.skipped:
        _done.add(report.nodeid)
        return
    finished = report.failed or report.when == "call"
    if not finished:
        return
    _done.add(report.nodeid)
    ids, kind = _marked[report.nodeid]
    for story in ids:
        _counts[story][kind][1] += 1
        if report.passed:
            _counts[story][kind][0] += 1


def pytest_terminal_summary(terminalreporter):
    if not _counts:
        return
    terminalreporter.section("user stories: tests passing")
    for story in sorted(_counts):
        kinds = _counts[story]
        letters = ORDER + sorted(set(kinds) - set(ORDER))
        parts = [f"{kinds[letter][0]}/{kinds[letter][1]} ({letter})" for letter in letters if letter in kinds]
        terminalreporter.write_line(f"{story}: {', '.join(parts)}")
