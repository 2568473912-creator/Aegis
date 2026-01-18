import sys
import os
import multiprocessing
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QVBoxLayout, QWidget, QLabel
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt


# ==========================================
# 🟢 [关键修复] 防止 --noconsole 模式下 print 报错
# ==========================================
class NullWriter:
    """一个什么都不做的虚拟输出流"""

    def write(self, text):
        pass

    def flush(self):
        pass


# 如果检测到没有控制台 (sys.stdout 为 None)，则重定向到虚拟流
if sys.stdout is None:
    sys.stdout = NullWriter()
if sys.stderr is None:
    sys.stderr = NullWriter()


# ==========================================
# 🟢 资源路径辅助函数
# ==========================================
def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


# ==========================================
# 🟢 导入子系统
# ==========================================
try:
    from line_inspector import LineInspectorApp
except ImportError:
    LineInspectorApp = None

try:
    from ui.main_window import CyberApp
except ImportError:
    try:
        from main_window import CyberApp
    except ImportError:
        CyberApp = None


# ==========================================
# 🟢 主窗口逻辑
# ==========================================
class IntegratedSystem(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Defect Aegis Combat System // Integrated V2.2")
        self.resize(1650, 1000)

        # 设置图标
        icon_path = get_resource_path("logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 核心容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 标签页控件
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)

        # --- 加载子系统 1: 坏点检测 ---
        if CyberApp:
            try:
                self.tab_dead_pixel = CyberApp()
                self.tab_dead_pixel.setWindowFlags(Qt.WindowType.Widget)
                self.tabs.addTab(self.tab_dead_pixel, "🔴 坏点克星 (Defect Pixel Nemesis)")
            except Exception as e:
                # 即使出错也尽量不弹窗崩溃，而是显示在界面上
                self.tabs.addTab(QLabel(f"Error Loading Dead Pixel: {e}"), "🔴 Error")
        else:
            self.tabs.addTab(QLabel("Failed to load Dead Pixel System"), "🔴 Error")

        # --- 加载子系统 2: 坏线检测 ---
        if LineInspectorApp:
            try:
                self.tab_line_defect = LineInspectorApp()
                self.tab_line_defect.setWindowFlags(Qt.WindowType.Widget)
                self.tabs.addTab(self.tab_line_defect, "➖ 坏线天敌 (Defect Line Natural Enemy)")
            except Exception as e:
                self.tabs.addTab(QLabel(f"Error Loading Line Inspector: {e}"), "➖ Error")
        else:
            self.tabs.addTab(QLabel("Failed to load Line Inspector"), "➖ Error")

        main_layout.addWidget(self.tabs)
        self.apply_global_theme()

    def apply_global_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI'; }
            QTabWidget::pane { border-top: 1px solid #333; }
            QTabBar::tab { background: #1a1a1a; color: #888; padding: 10px 30px; margin-right: 2px; border-top-left-radius: 6px; border-top-right-radius: 6px; font-weight: bold; font-size: 11pt; }
            QTabBar::tab:selected { background: #252525; color: #00e676; border-bottom: 3px solid #00e676; }
            QTabBar::tab:hover { background: #333; color: #fff; }
        """)


if __name__ == "__main__":
    multiprocessing.freeze_support()

    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # 确保任务栏图标显示
    icon_path = get_resource_path("logo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = IntegratedSystem()
    window.show()
    sys.exit(app.exec())