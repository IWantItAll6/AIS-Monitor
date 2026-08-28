from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget

from ui.vessel_tree_item import VesselTreeItem


def test_pinned_item_stays_on_top_in_both_sort_directions(qapp):

    # Qt sorts descending by swapping the operands passed to __lt__ rather
    # than negating the result — a naive "pinned sorts first" comparator
    # would flip pinned rows to the bottom under descending order. This
    # locks in the fix.
    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.setSortingEnabled(True)

    pinned = VesselTreeItem(["", "300"])
    pinned.setData(0, Qt.ItemDataRole.UserRole, True)
    pinned.setData(1, Qt.ItemDataRole.UserRole, 300)

    unpinned = VesselTreeItem(["", "100"])
    unpinned.setData(0, Qt.ItemDataRole.UserRole, False)
    unpinned.setData(1, Qt.ItemDataRole.UserRole, 100)

    tree.addTopLevelItem(pinned)
    tree.addTopLevelItem(unpinned)

    tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    assert tree.topLevelItem(0).text(1) == "300"

    tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    assert tree.topLevelItem(0).text(1) == "300"


def test_unpinned_items_sort_normally_by_column_data(qapp):

    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.setSortingEnabled(True)

    for mmsi in (300, 100, 200):

        item = VesselTreeItem(["", str(mmsi)])
        item.setData(0, Qt.ItemDataRole.UserRole, False)
        item.setData(1, Qt.ItemDataRole.UserRole, mmsi)

        tree.addTopLevelItem(item)

    tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)

    ordered = [tree.topLevelItem(i).text(1) for i in range(3)]

    assert ordered == ["100", "200", "300"]
