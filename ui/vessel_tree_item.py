from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem


class VesselTreeItem(QTreeWidgetItem):

    def __lt__(self, other):

        tree = self.treeWidget()

        my_pinned = bool(self.data(0, Qt.ItemDataRole.UserRole))
        other_pinned = bool(other.data(0, Qt.ItemDataRole.UserRole))

        if my_pinned != other_pinned:

            pinned_first = my_pinned

            # Qt sorts descending by swapping the operands passed to __lt__
            # (effectively comparing other < self instead of self < other),
            # so without this the pinned rows would flip to the bottom
            # whenever the user sorts a column descending.
            if tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder:
                pinned_first = not pinned_first

            return pinned_first

        column = tree.sortColumn()

        my_data = self.data(column, Qt.ItemDataRole.UserRole)
        other_data = other.data(column, Qt.ItemDataRole.UserRole)

        if my_data is not None and other_data is not None:

            return my_data < other_data

        return super().__lt__(other)
