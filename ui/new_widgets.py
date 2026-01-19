import pyqtgraph as pg
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QTimer
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen


class ZoomableGraphicsView(QGraphicsView):
    sig_mouse_moved = pyqtSignal(int, int)
    # 信号: 发送当前可视区域的矩形范围 (经过节流处理)
    sig_viewport_changed = pyqtSignal(QRectF)
    sig_roi_selected = pyqtSignal(int, int, int, int)
    sig_roi_cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)

        self.pixmap_item = QGraphicsPixmapItem()
        self.scene_obj.addItem(self.pixmap_item)

        # 🟢 渲染优化
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)

        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor("#000000"))
        self.setMouseTracking(True)

        # ROI 变量
        self.is_roi_mode = False
        self.roi_start_pos = None
        self.roi_rect_item = None
        self.highlight_item = None

        # 🟢 [核心优化] 信号节流器
        self._last_scene_rect = QRectF()
        self.throttle_timer = QTimer()
        self.throttle_timer.setSingleShot(True)
        self.throttle_timer.setInterval(16)  # 16ms ≈ 60FPS，人眼流畅极限
        self.throttle_timer.timeout.connect(self._perform_emit_viewport)

    def set_image(self, numpy_img_8u):
        # 🟢 [新增] 切换图片时，清除上一次的高亮框 (那个绿色的坏点框)
        if self.highlight_item:
            try:
                self.scene_obj.removeItem(self.highlight_item)
            except:
                pass
            self.highlight_item = None
        h, w = numpy_img_8u.shape[:2]
        qimg = QImage(numpy_img_8u.data, w, h, w, QImage.Format.Format_Grayscale8)
        self.pixmap_item.setPixmap(QPixmap.fromImage(qimg))
        self.scene_obj.setSceneRect(0, 0, w, h)
        self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._emit_viewport()

    def set_roi_mode(self, enabled: bool):
        self.is_roi_mode = enabled
        if enabled:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if self.roi_rect_item:
                self.scene_obj.removeItem(self.roi_rect_item)
                self.roi_rect_item = None

    # 🟢 触发节流
    def _emit_viewport(self):
        if not self.throttle_timer.isActive():
            self.throttle_timer.start()

    # 🟢 实际发送信号 (由 Timer 调用)
    def _perform_emit_viewport(self):
        vp_rect = self.viewport().rect()
        scene_rect = self.mapToScene(vp_rect).boundingRect()
        img_rect = self.scene_obj.sceneRect()
        intersect = scene_rect.intersected(img_rect)

        # 只有变化超过 1 像素才发送，避免浮点数抖动
        if intersect != self._last_scene_rect:
            self.sig_viewport_changed.emit(intersect)
            self._last_scene_rect = intersect

    def wheelEvent(self, event):
        factor = 1.1
        if event.angleDelta().y() < 0: factor = 1.0 / factor
        self.scale(factor, factor)
        self._emit_viewport()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._emit_viewport()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._emit_viewport()

    def mousePressEvent(self, event):
        if self.is_roi_mode and event.button() == Qt.MouseButton.LeftButton:
            self.roi_start_pos = self.mapToScene(event.pos())
            if self.roi_rect_item: self.scene_obj.removeItem(self.roi_rect_item)
            self.roi_rect_item = QGraphicsRectItem()
            self.roi_rect_item.setPen(QPen(QColor("#FFD700"), 1, Qt.PenStyle.DashLine))
            self.scene_obj.addItem(self.roi_rect_item)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_roi_mode and self.roi_start_pos and (event.buttons() & Qt.MouseButton.LeftButton):
            curr = self.mapToScene(event.pos())
            x = min(self.roi_start_pos.x(), curr.x())
            y = min(self.roi_start_pos.y(), curr.y())
            w = abs(self.roi_start_pos.x() - curr.x())
            h = abs(self.roi_start_pos.y() - curr.y())
            self.roi_rect_item.setRect(x, y, w, h)

        scene_pos = self.mapToScene(event.pos())
        self.sig_mouse_moved.emit(int(scene_pos.x()), int(scene_pos.y()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.is_roi_mode and self.roi_start_pos and event.button() == Qt.MouseButton.LeftButton:
            if self.roi_rect_item:
                rect = self.roi_rect_item.rect()
                x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
                if w > 1 and h > 1:
                    # 优先发送信号，再移除框
                    self.sig_roi_selected.emit(x, y, w, h)
                self.scene_obj.removeItem(self.roi_rect_item)
                self.roi_rect_item = None
            self.roi_start_pos = None
        super().mouseReleaseEvent(event)

    def highlight_defect(self, x, y, size=50):
        if self.highlight_item:
            try:
                self.scene_obj.removeItem(self.highlight_item)
            except:
                pass
        rect_x = x - size // 2;
        rect_y = y - size // 2
        self.highlight_item = self.scene_obj.addRect(rect_x, rect_y, size, size, QPen(QColor("#00e676"), 2))