import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog,
    QLabel, QPushButton, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QPen


# ==============================================================================
# 1. 可拆卸图表包装器 (保持不变)
# ==============================================================================
class DetachablePlotWrapper(QWidget):
    def __init__(self, title, plot_widget, parent=None):
        super().__init__(parent)
        self.plot_widget = plot_widget
        self.title = title
        self.is_popped = False

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Header
        self.header = QFrame()
        self.header.setStyleSheet("background-color: #333; border-bottom: 1px solid #555;")
        self.header.setFixedHeight(25)
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(5, 0, 5, 0)

        self.lbl_title = QLabel(f"{title}")
        self.lbl_title.setStyleSheet("color: #ccc; font-weight: bold; font-size: 9pt;")
        h_layout.addWidget(self.lbl_title)

        self.btn_pop = QPushButton("⇱")
        self.btn_pop.setFixedSize(20, 20)
        self.btn_pop.setStyleSheet("color: #fff; border: none; font-weight: bold;")
        self.btn_pop.clicked.connect(self.toggle_pop)
        h_layout.addWidget(self.btn_pop)

        self.layout.addWidget(self.header)
        self.layout.addWidget(self.plot_widget)

        # Dialog
        self.pop_dialog = QDialog()
        self.pop_dialog.setWindowTitle(title)
        self.pop_dialog.resize(1000, 600)
        self.pop_layout = QVBoxLayout(self.pop_dialog)
        self.pop_layout.setContentsMargins(0, 0, 0, 0)
        self.pop_dialog.finished.connect(self.on_dialog_close)

    def toggle_pop(self):
        if self.is_popped:
            self.pop_dialog.close()
        else:
            self.layout.removeWidget(self.plot_widget)
            self.pop_layout.addWidget(self.plot_widget)
            self.plot_widget.show()
            self.pop_dialog.show()
            self.is_popped = True
            self.btn_pop.setText("⇲")
            self.lbl_title.setText(f"{self.title} (Floating)")

    def on_dialog_close(self):
        if self.is_popped:
            self.pop_layout.removeWidget(self.plot_widget)
            self.layout.addWidget(self.plot_widget)
            self.is_popped = False
            self.btn_pop.setText("⇱")
            self.lbl_title.setText(f"{self.title}")

    def mouseDoubleClickEvent(self, event):
        self.toggle_pop()
        super().mouseDoubleClickEvent(event)


# ==============================================================================
# 2. 主图表组件 (带中心指示线)
# ==============================================================================
class LineProfileWidget(QWidget):
    sig_curve_clicked = pyqtSignal(str, int)
    sig_zoom_req = pyqtSignal(float, float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(5)

        self.vb_row_diff = None
        self.vb_col_diff = None
        self.is_external_updating = False

        # 🟢 创建图表时，接收返回的 line 对象
        # Row Chart (Y-Axis Analysis)
        self.plot_row, self.vb_row_diff, self.line_row_center = self._create_dual_axis_plot(
            "Row Profile", "Avg Intensity", "#00e676", "Max Diff", "#ff1744"
        )
        self.plot_row.sigXRangeChanged.connect(lambda: self._on_axis_change(self.plot_row, 'H'))

        # Col Chart (X-Axis Analysis)
        self.plot_col, self.vb_col_diff, self.line_col_center = self._create_dual_axis_plot(
            "Col Profile", "Avg Intensity", "#2979ff", "Max Diff", "#ff1744"
        )
        self.plot_col.sigXRangeChanged.connect(lambda: self._on_axis_change(self.plot_col, 'V'))

        # Wrappers
        self.wrap_row = DetachablePlotWrapper("Row Analysis (Y-Axis)", self.plot_row)
        self.wrap_col = DetachablePlotWrapper("Col Analysis (X-Axis)", self.plot_col)

        self.layout.addWidget(self.wrap_row)
        self.layout.addWidget(self.wrap_col)

    def _create_dual_axis_plot(self, title, name1, color1, name2, color2):
        p = pg.PlotWidget(background="#000000")
        p.showGrid(x=True, y=True, alpha=0.3)
        p.getPlotItem().hideButtons()

        p.setClipToView(True)
        p.setDownsampling(mode='peak')
        p.setMenuEnabled(False)

        # Left Axis
        p.setLabel('left', name1, color=color1)
        p.getPlotItem().getAxis('left').setPen(color1)

        curve1 = pg.PlotDataItem(pen=QPen(QColor(color1), 1), name=name1)
        curve1.setDownsampling(auto=True, method='peak')
        p.addItem(curve1)

        # Right Axis
        vb2 = pg.ViewBox()
        p.scene().addItem(vb2)
        p.getPlotItem().showAxis('right')
        p.getPlotItem().getAxis('right').linkToView(vb2)
        p.getPlotItem().getAxis('right').setLabel(name2, color=color2)
        p.getPlotItem().getAxis('right').setPen(color2)
        vb2.setXLink(p.getPlotItem())

        curve2 = pg.PlotDataItem(pen=QPen(QColor(color2), 1), name=name2)
        curve2.setDownsampling(auto=True, method='peak')
        vb2.addItem(curve2)

        # 🟢 [新增] 中心指示线 (黄色虚线)
        v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#FFFF00', width=1, style=Qt.PenStyle.DashLine))
        # ignoreBounds=True 防止这条线影响自动缩放范围
        p.addItem(v_line, ignoreBounds=True)

        def update_views():
            vb2.setGeometry(p.getPlotItem().vb.sceneBoundingRect())
            vb2.linkedViewChanged(p.getPlotItem().vb, vb2.XAxis)

        p.getPlotItem().vb.sigResized.connect(update_views)
        p.scene().sigMouseClicked.connect(lambda ev: self._on_click(ev, p))

        p.curve_avg = curve1
        p.curve_diff = curve2
        p.vb_diff = vb2

        # 返回 line 对象以便后续控制
        return p, vb2, v_line

    def _on_axis_change(self, plot_widget, orientation):
        if self.is_external_updating: return
        (x_min, x_max) = plot_widget.viewRange()[0]
        self.sig_zoom_req.emit(x_min, x_max, orientation)

    def update_data(self, row_avg, row_diff, col_avg, col_diff, start_y=0, start_x=0):
        self.is_external_updating = True
        self.plot_row.blockSignals(True)
        self.plot_col.blockSignals(True)

        r_avg = np.array(row_avg);
        r_diff = np.array(row_diff)
        c_avg = np.array(col_avg);
        c_diff = np.array(col_diff)

        y_axis = np.arange(start_y, start_y + len(r_avg))
        self.plot_row.curve_avg.setData(x=y_axis, y=r_avg)
        self.plot_row.curve_diff.setData(x=y_axis, y=r_diff)

        x_axis = np.arange(start_x, start_x + len(c_avg))
        self.plot_col.curve_avg.setData(x=x_axis, y=c_avg)
        self.plot_col.curve_diff.setData(x=x_axis, y=c_diff)

        # Reset
        self.plot_row.getPlotItem().vb.autoRange()
        self.plot_col.getPlotItem().vb.autoRange()
        self.vb_row_diff.autoRange()
        self.vb_col_diff.autoRange()

        self.plot_row.blockSignals(False)
        self.plot_col.blockSignals(False)
        self.is_external_updating = False

    def set_axis_zoom(self, rect_f):
        """ 极致性能的视图同步 + 中心线更新 """
        self.is_external_updating = True
        self.plot_row.blockSignals(True)
        self.plot_col.blockSignals(True)

        # 更新显示范围
        y_min, y_max = rect_f.y(), rect_f.y() + rect_f.height()
        self.plot_row.setXRange(y_min, y_max, padding=0)

        x_min, x_max = rect_f.x(), rect_f.x() + rect_f.width()
        self.plot_col.setXRange(x_min, x_max, padding=0)

        # 🟢 [新增] 更新中心线位置
        center = rect_f.center()
        self.line_row_center.setValue(center.y())  # Row图的X轴代表图片的Y
        self.line_col_center.setValue(center.x())  # Col图的X轴代表图片的X

        self.plot_row.blockSignals(False)
        self.plot_col.blockSignals(False)
        self.is_external_updating = False

    def _on_click(self, event, plot_widget):
        if event.double():
            pos = event.scenePos()
            if plot_widget.getPlotItem().vb:
                mouse_point = plot_widget.getPlotItem().vb.mapSceneToView(pos)
                index = int(mouse_point.x())
                if plot_widget == self.plot_row:
                    self.sig_curve_clicked.emit('H', index)
                else:
                    self.sig_curve_clicked.emit('V', index)