"""Snapshot ("print-screening") regression tests via pytest-textual-snapshot.
First run generates the baseline `.svg` files under `__snapshots__/`, which
get committed like any other test fixture; future runs fail loudly if a
change alters the rendered output unexpectedly.
"""


def test_initial_log_view_snapshot(snap_compare, app):
    assert snap_compare(app, terminal_size=(100, 30))


def test_log_view_with_second_row_selected_snapshot(snap_compare, app):
    assert snap_compare(app, press=["down"], terminal_size=(100, 30))
