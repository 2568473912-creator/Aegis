import sys
import os
import cv2
import csv
import numpy as np
import shutil
import xlsxwriter
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# 🟢 全局性能配置
import pyqtgraph as pg

pg.setConfigOptions(imageAxisOrder='row-major', antialias=False, useOpenGL=True)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QSplitter, QGroupBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDoubleSpinBox, QListWidget, QScrollArea, QFrame, QCheckBox, QMessageBox,
    QProgressBar, QLineEdit, QDialog, QDialogButtonBox, QFormLayout
)
from PyQt6.QtCore import Qt, QSize, QRectF, QTimer, QSettings
from PyQt6.QtGui import QColor, QIcon, QPen

from ui.new_widgets import ZoomableGraphicsView
from ui.line_widgets import LineProfileWidget
from core.line_algorithm import LineDefectAlgorithm


# ==============================================================================
# 🟢 弹窗 1: 批量坐标截图设置 (Excel 矩阵版)
# ==============================================================================
class BatchSnapDialog(QDialog):
    def __init__(self, file_list, default_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Coordinate Snapper (Excel Matrix)")
        self.resize(600, 600)
        self.default_path = default_path
        self.file_list = file_list if file_list else []
        self.csv_targets = []

        self.init_ui()
        self.apply_styles()

        if not self.file_list and self.default_path and os.path.exists(self.default_path):
            self.scan_source_folder()
        else:
            self.update_count()

    def init_ui(self):
        layout = QVBoxLayout(self)

        grp_in = QGroupBox("1. Input Source")
        h_in = QHBoxLayout(grp_in)
        self.edt_in = QLineEdit()
        self.edt_in.setText(self.default_path)
        self.edt_in.setPlaceholderText("Select Input Image Folder")
        self.btn_in = QPushButton("Browse")
        self.btn_in.clicked.connect(self.select_input)
        h_in.addWidget(self.edt_in)
        h_in.addWidget(self.btn_in)
        layout.addWidget(grp_in)

        grp_filter = QGroupBox("2. Filter Files")
        v_filter = QVBoxLayout(grp_filter)
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("Filter filename (e.g. .tif)")
        self.lbl_count = QLabel(f"Total: {len(self.file_list)}")
        self.txt_filter.textChanged.connect(self.update_count)
        v_filter.addWidget(self.txt_filter)
        v_filter.addWidget(self.lbl_count)
        layout.addWidget(grp_filter)

        grp_coord = QGroupBox("3. Coordinate Settings")
        form_coord = QFormLayout(grp_coord)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Single Coordinate (Fixed)", "Batch from CSV Import"])
        self.combo_mode.currentIndexChanged.connect(self.toggle_mode_ui)
        form_coord.addRow("Mode:", self.combo_mode)

        self.combo_dir = QComboBox()
        self.combo_dir.addItems(["Horizontal (Row)", "Vertical (Col)"])
        self.lbl_dir = QLabel("Direction:")
        form_coord.addRow(self.lbl_dir, self.combo_dir)

        self.lbl_idx = QLabel("Fixed Index:")
        self.sb_idx = QSpinBox()
        self.sb_idx.setRange(0, 99999)
        form_coord.addRow(self.lbl_idx, self.sb_idx)

        self.lbl_csv = QLabel("CSV File:")
        h_csv = QHBoxLayout()
        self.edt_csv = QLineEdit()
        self.edt_csv.setPlaceholderText("Fmt: Index, [H/V]")
        self.edt_csv.setReadOnly(True)
        self.btn_csv = QPushButton("Load CSV")
        self.btn_csv.clicked.connect(self.load_csv)
        h_csv.addWidget(self.edt_csv)
        h_csv.addWidget(self.btn_csv)
        self.wid_csv = QWidget();
        self.wid_csv.setLayout(h_csv)
        form_coord.addRow(self.lbl_csv, self.wid_csv)

        self.sb_pad = QSpinBox()
        self.sb_pad.setRange(10, 2000)
        self.sb_pad.setValue(50)
        form_coord.addRow("Crop Height (±px):", self.sb_pad)

        layout.addWidget(grp_coord)

        grp_out = QGroupBox("4. Output Directory")
        h_out = QHBoxLayout(grp_out)
        self.edt_out = QLineEdit()
        self.edt_out.setText(self.default_path)
        self.btn_out = QPushButton("Browse")
        self.btn_out.clicked.connect(self.select_output)
        h_out.addWidget(self.edt_out)
        h_out.addWidget(self.btn_out)
        layout.addWidget(grp_out)

        self.pbar = QProgressBar()
        layout.addWidget(self.pbar)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.run_process)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.toggle_mode_ui(0)

    def scan_source_folder(self):
        d = self.edt_in.text()
        if not d or not os.path.exists(d):
            self.file_list = []
        else:
            exts = {'.png', '.tif', '.tiff', '.raw', '.bmp'}
            try:
                self.file_list = [os.path.join(d, f) for f in os.listdir(d) if Path(f).suffix.lower() in exts]
                self.file_list.sort()
            except:
                self.file_list = []
        self.update_count()
        if not self.edt_out.text(): self.edt_out.setText(d)

    def select_input(self):
        d = QFileDialog.getExistingDirectory(self, "Select Input Folder", self.edt_in.text())
        if d:
            self.edt_in.setText(d)
            self.scan_source_folder()
            self.edt_out.setText(d)

    def select_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.edt_out.text())
        if d: self.edt_out.setText(d)

    def toggle_mode_ui(self, idx):
        is_csv = (idx == 1)
        self.lbl_idx.setVisible(not is_csv)
        self.sb_idx.setVisible(not is_csv)
        self.combo_dir.setVisible(not is_csv)
        self.lbl_dir.setVisible(not is_csv)
        self.lbl_csv.setVisible(is_csv)
        self.wid_csv.setVisible(is_csv)

    def load_csv(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select CSV", self.default_path, "CSV (*.csv);;Txt (*.txt)")
        if not f: return
        self.edt_csv.setText(f)
        try:
            self.csv_targets = []
            with open(f, 'r', encoding='utf-8-sig') as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    if len(row) >= 1:
                        try:
                            idx = int(float(row[0]))
                            is_horz = True
                            if len(row) > 1:
                                dir_str = row[1].strip().upper()
                                if 'V' in dir_str or 'COL' in dir_str: is_horz = False
                            self.csv_targets.append((idx, is_horz))
                        except:
                            pass
            QMessageBox.information(self, "CSV Loaded", f"Loaded {len(self.csv_targets)} target lines.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load CSV: {e}")

    def update_count(self):
        f = [x for x in self.file_list if self.txt_filter.text().lower() in Path(x).name.lower()]
        self.lbl_count.setText(f"Match: {len(f)}")

    def run_process(self):
        # 1. 获取要处理的图片列表
        image_files = [x for x in self.file_list if self.txt_filter.text().lower() in Path(x).name.lower()]
        if not image_files:
            QMessageBox.warning(self, "Warn", "No images matched!")
            return

        base = self.edt_out.text()
        time_str = datetime.now().strftime('%H%M%S')
        save_dir = os.path.join(base, f"SnapMatrix_{time_str}")
        temp_img_dir = os.path.join(save_dir, "temp_images")  # 临时放图片
        os.makedirs(temp_img_dir, exist_ok=True)

        fixed_is_horz = "Horizontal" in self.combo_dir.currentText()
        pad = self.sb_pad.value()
        mode_csv = (self.combo_mode.currentIndex() == 1)

        # 2. 准备任务列表 (行)
        if mode_csv:
            if not self.csv_targets:
                QMessageBox.warning(self, "Warn", "CSV loaded but no valid targets found!")
                return
            tasks = self.csv_targets  # [(idx, is_horz), ...]
        else:
            tasks = [(self.sb_idx.value(), fixed_is_horz)]

        # 3. 创建 Excel
        excel_path = os.path.join(save_dir, f"Snap_Report_{time_str}.xlsx")
        workbook = xlsxwriter.Workbook(excel_path)
        worksheet = workbook.add_worksheet("Snapshots")

        # 样式
        fmt_header = workbook.add_format(
            {'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        fmt_row_header = workbook.add_format(
            {'bold': True, 'bg_color': '#E0E0E0', 'border': 1, 'align': 'center', 'valign': 'vcenter'})

        # 4. 写入表头 (列：图片文件名)
        worksheet.write(0, 0, "Coordinate \\ Image", fmt_header)
        worksheet.set_column(0, 0, 20)  # 第一列宽度

        for col_idx, img_path in enumerate(image_files):
            fname = Path(img_path).name
            worksheet.write(0, col_idx + 1, fname, fmt_header)
            worksheet.set_column(col_idx + 1, col_idx + 1, 40)  # 图片列宽

        # 5. 遍历处理
        self.pbar.setRange(0, len(image_files))

        # 这里的逻辑稍微反转一下：为了性能，我们按图片遍历（外层），然后切每行（内层）
        # 但写入 Excel 时，我们要按 (row, col) 写入

        for col_idx, img_path in enumerate(image_files):
            self.pbar.setValue(col_idx + 1)
            QApplication.processEvents()

            img = cv2.imread(img_path, cv2.IMREAD_UNCHANGED)
            if img is None: continue
            h, w = img.shape[:2]

            for row_idx, (idx, is_horz) in enumerate(tasks):
                # 写入行头 (只在处理第一张图时写一次)
                if col_idx == 0:
                    dir_str = "Row (H)" if is_horz else "Col (V)"
                    label = f"{dir_str} {idx}"
                    worksheet.write(row_idx + 1, 0, label, fmt_row_header)
                    worksheet.set_row(row_idx + 1, 100)  # 设置行高以容纳图片

                # 截图逻辑
                crop = None
                if is_horz:
                    y0, y1 = max(0, idx - pad), min(h, idx + pad)
                    crop = img[y0:y1, :]
                else:
                    x0, x1 = max(0, idx - pad), min(w, idx + pad)
                    crop = img[:, x0:x1]
                    # 竖线旋转
                    if crop.size > 0:
                        crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)

                if crop is not None and crop.size > 0:
                    # 转 8-bit 用于保存
                    if crop.dtype == np.uint16:
                        vis = cv2.normalize(crop, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                    else:
                        vis = crop.astype(np.uint8)

                    # 保存临时图片
                    # 命名规则: col_row.png
                    tmp_name = f"c{col_idx}_r{row_idx}.png"
                    tmp_path = os.path.join(temp_img_dir, tmp_name)
                    cv2.imwrite(tmp_path, vis)

                    # 插入 Excel
                    worksheet.insert_image(row_idx + 1, col_idx + 1, tmp_path, {
                        'x_scale': 0.5,
                        'y_scale': 0.5,
                        'object_position': 1,  # Move and size with cells
                        'x_offset': 5,
                        'y_offset': 5
                    })

        workbook.close()

        # 可选：清理临时文件夹 (如果不想要那一堆碎图)
        # shutil.rmtree(temp_img_dir)

        QMessageBox.information(self, "Done", f"Excel Matrix generated at:\n{excel_path}")
        self.accept()

    def apply_styles(self):
        self.setStyleSheet("QDialog{background:#1a1a1a;color:#fff} QGroupBox{border:1px solid #444;color:#0e6}")

# ==============================================================================
# 🟢 弹窗 2: 批量 Pass/Fail 分析设置
# ==============================================================================
class BatchAnalysisDialog(QDialog):
    def __init__(self, params, default_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Analysis")
        self.resize(500, 450)
        self.file_list = []
        self.params = params
        self.default_path = default_path
        self.output_dir = default_path

        self.init_ui()
        self.apply_styles()

        self.scan_source_folder()

    def init_ui(self):
        layout = QVBoxLayout(self)
        grp_main = QGroupBox("1. Settings")
        form = QFormLayout(grp_main)

        h_in = QHBoxLayout()
        self.edt_in = QLineEdit()
        self.edt_in.setText(self.default_path)
        self.btn_in = QPushButton("...")
        self.btn_in.setFixedWidth(40)
        self.btn_in.clicked.connect(self.select_input)
        h_in.addWidget(self.edt_in)
        h_in.addWidget(self.btn_in)
        form.addRow("Input Folder:", h_in)

        self.lbl_count = QLabel("Files: 0")
        form.addRow("", self.lbl_count)

        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("Filter files...")
        self.txt_filter.textChanged.connect(self.update_count)
        form.addRow("Filename Filter:", self.txt_filter)

        h_path = QHBoxLayout()
        self.edt_out = QLineEdit()
        self.edt_out.setText(self.default_path)
        self.btn_browse = QPushButton("...")
        self.btn_browse.setFixedWidth(40)
        self.btn_browse.clicked.connect(self.select_output)
        h_path.addWidget(self.edt_out)
        h_path.addWidget(self.btn_browse)
        form.addRow("Output Folder:", h_path)

        self.sb_pad = QSpinBox()
        self.sb_pad.setRange(10, 1000)
        self.sb_pad.setValue(20)
        form.addRow("Crop Height (±px):", self.sb_pad)

        layout.addWidget(grp_main)
        self.pbar = QProgressBar()
        layout.addWidget(self.pbar)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.run)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def select_input(self):
        d = QFileDialog.getExistingDirectory(self, "Select Input Directory", self.edt_in.text())
        if d:
            self.edt_in.setText(d)
            self.scan_source_folder()
            if not self.edt_out.text(): self.edt_out.setText(d)

    def scan_source_folder(self):
        d = self.edt_in.text()
        if not d or not os.path.exists(d):
            self.file_list = []
        else:
            exts = {'.png', '.tif', '.tiff', '.raw', '.bmp'}
            try:
                self.file_list = [os.path.join(d, f) for f in os.listdir(d) if Path(f).suffix.lower() in exts]
                self.file_list.sort()
            except:
                self.file_list = []
        self.update_count()

    def update_count(self):
        f = [x for x in self.file_list if self.txt_filter.text().lower() in Path(x).name.lower()]
        self.lbl_count.setText(f"Files: {len(self.file_list)} (Match: {len(f)})")

    def select_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.edt_out.text())
        if d: self.edt_out.setText(d)

    def process_unique_defects(self, raw_defects):
        line_map = {}
        for d in raw_defects:
            key = (d['ch'], d['type'], d['index'])
            if key not in line_map:
                line_map[key] = d
            else:
                existing = line_map[key]
                is_existing_global = "Global" in existing['mode']
                is_new_global = "Global" in d['mode']
                if is_new_global and not is_existing_global:
                    line_map[key] = d
                elif is_new_global == is_existing_global:
                    if d['diff'] > existing['diff']: line_map[key] = d
        return sorted(line_map.values(), key=lambda x: x['index'])

    def run(self):
        f_list = [x for x in self.file_list if self.txt_filter.text().lower() in Path(x).name.lower()]
        if not f_list:
            QMessageBox.warning(self, "Warn", "No matching files!")
            return

        base = self.edt_out.text() if self.edt_out.text() else self.default_path
        time_str = datetime.now().strftime('%H%M%S')
        rep_dir = os.path.join(base, f"Report_{time_str}")
        img_dir = os.path.join(rep_dir, "FAIL_Images")
        os.makedirs(img_dir, exist_ok=True)

        excel_path = os.path.join(rep_dir, f"Batch_Report_{time_str}.xlsx")
        workbook = xlsxwriter.Workbook(excel_path)

        ws_sum = workbook.add_worksheet("Summary")
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
        cell_fmt = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})

        ws_sum.write_row('A1', ["Filename", "Result", "Unique Defects", "Time (s)"], header_fmt)
        ws_sum.set_column('A:A', 30)

        ws_detail = workbook.add_worksheet("Defect_Details")
        ws_detail.write_row('A1', ["Filename", "Index", "Type", "Mode", "Channel", "Diff Value", "Image"], header_fmt)
        ws_detail.set_column('A:A', 30)
        ws_detail.set_column('B:F', 10)
        ws_detail.set_column('G:G', 50)

        pad = self.sb_pad.value()
        detail_row = 1
        block_qty = self.params.get('block_qty', 10)

        self.pbar.setRange(0, len(f_list))

        for i, p in enumerate(f_list):
            self.pbar.setValue(i + 1)
            QApplication.processEvents()

            file_name = Path(p).name
            img = cv2.imread(p, -1)
            if img is None: continue

            t0 = datetime.now()
            raw_defects, _ = LineDefectAlgorithm.run_inspection(img, self.params)
            unique_defects = self.process_unique_defects(raw_defects)
            dt = (datetime.now() - t0).total_seconds()
            res_str = "FAIL" if unique_defects else "PASS"

            ws_sum.write_row(i + 1, 0, [file_name, res_str, len(unique_defects), round(dt, 2)], cell_fmt)

            if unique_defects:
                sub_dir = os.path.join(img_dir, Path(p).stem)
                os.makedirs(sub_dir, exist_ok=True)
                h, w = img.shape[:2]
                blk_h, blk_w = h // block_qty, w // block_qty

                for di, d in enumerate(unique_defects):
                    idx = d['index']
                    x0, x1, y0, y1 = 0, w, 0, h

                    if "Part" in d['mode']:
                        try:
                            parts = d['mode'].replace("Part(", "").replace(")", "").split(",")
                            by, bx = int(parts[0]), int(parts[1])
                            if d['type'] == 'Horizontal':
                                x0, x1 = bx * blk_w, (bx + 1) * blk_w
                            else:
                                y0, y1 = by * blk_h, (by + 1) * blk_h
                        except:
                            pass

                    crop = None
                    if d['type'] == 'Horizontal':
                        cy0 = max(0, idx - pad)
                        cy1 = min(h, idx + pad)
                        crop = img[cy0:cy1, x0:x1]
                    else:
                        cx0 = max(0, idx - pad)
                        cx1 = min(w, idx + pad)
                        crop = img[y0:y1, cx0:cx1]
                        if crop.size > 0:
                            crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)

                    img_path = ""
                    if crop is not None and crop.size > 0:
                        if crop.dtype == np.uint16:
                            vis = cv2.normalize(crop, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                        else:
                            vis = crop.astype(np.uint8)

                        img_name = f"D{di}_{d['type'][0]}{idx}_diff{int(d['diff'])}.png"
                        img_path = os.path.join(sub_dir, img_name)
                        cv2.imwrite(img_path, vis)

                    ws_detail.write_row(detail_row, 0,
                                        [file_name, d['index'], d['type'], d['mode'], d['ch'], round(d['diff'], 2)],
                                        cell_fmt)

                    if img_path and os.path.exists(img_path):
                        try:
                            ws_detail.set_row(detail_row, 100)
                            ws_detail.insert_image(detail_row, 6, img_path,
                                                   {'x_scale': 0.5, 'y_scale': 0.5, 'object_position': 1, 'x_offset': 5,
                                                    'y_offset': 5})
                        except:
                            pass
                    detail_row += 1

        workbook.close()
        QMessageBox.information(self, "Done", f"Report generated:\n{excel_path}")
        self.accept()

    def apply_styles(self):
        self.setStyleSheet("QDialog{background:#1a1a1a;color:#fff} QGroupBox{border:1px solid #444;color:#0e6}")


# ==============================================================================
# 🟢 主程序 V19.1 (Fixed Missing Functions + Indentations)
# ==============================================================================
class LineInspectorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Line Defect Inspector // V19.1 (Stable)")
        self.resize(1600, 1000)

        self.current_img = None
        self.processed_img = None
        self.defects = []
        self.file_list = []
        self.current_folder = ""
        self.defect_items = []
        self.last_stats = None
        # 🟢 [修改] 1. 使用新的配置加载
        self.config_path = self.get_config_path()  # 获取路径
        self.config = self.load_config()  # 加载或生成 ini
        self.sync_driver = None
        self.chart_sync_timer = QTimer()
        self.chart_sync_timer.setSingleShot(True)
        self.chart_sync_timer.setInterval(20)
        self.chart_sync_timer.timeout.connect(self._execute_chart_driven_sync)
        self.pending_chart_req = None

        self.init_ui()
        self.apply_theme()

        # 🟢 [修改] 2. 加载上次文件夹
        last_folder = self.config.get("last_folder", "")
        if last_folder and os.path.exists(last_folder):
            self.load_source_folder(last_folder)

    # 🟢 [新增] 获取配置文件路径 (兼容 .exe 和 .py)
    def get_config_path(self):
        if getattr(sys, 'frozen', False):
            # 打包后：配置文件生成在 .exe 同级目录
            base_path = os.path.dirname(sys.executable)
        else:
            # 开发时：配置文件生成在脚本同级目录
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, "dline.config.ini")

    # 🟢 [新增] 加载配置 (若文件不存在，自动生成默认值)
    def load_config(self):
        settings = QSettings(self.config_path, QSettings.Format.IniFormat)

        # 如果文件不存在，立即写入默认配置
        if not os.path.exists(self.config_path):
            defaults = {
                "effective_bits_idx": 0, "channel_count_idx": 0, "use_robust": True,
                "thresh_global_h": 20, "thresh_global_v": 20,
                "thresh_part_h": 10, "thresh_part_v": 10,
                "block_qty": 10, "strip_h": 0, "strip_v": 0,
                "edge_gain": 1.0, "vis_pad": 5, "crop_pad": 20,
                "last_folder": ""
            }
            self.save_config(defaults)  # 调用保存生成文件
            return defaults

        # 读取配置 (注意类型转换，QSettings 读出来默认是字符串)
        cfg = {}
        cfg["effective_bits_idx"] = int(settings.value("params/effective_bits_idx", 0))
        cfg["channel_count_idx"] = int(settings.value("params/channel_count_idx", 0))
        cfg["use_robust"] = str(settings.value("params/use_robust", "true")).lower() == 'true'
        cfg["thresh_global_h"] = int(settings.value("params/thresh_global_h", 20))
        cfg["thresh_global_v"] = int(settings.value("params/thresh_global_v", 20))
        cfg["thresh_part_h"] = int(settings.value("params/thresh_part_h", 10))
        cfg["thresh_part_v"] = int(settings.value("params/thresh_part_v", 10))
        cfg["block_qty"] = int(settings.value("params/block_qty", 10))
        cfg["strip_h"] = int(settings.value("crop/strip_h", 0))
        cfg["strip_v"] = int(settings.value("crop/strip_v", 0))
        cfg["edge_gain"] = float(settings.value("params/edge_gain", 1.0))
        cfg["vis_pad"] = int(settings.value("vis/vis_pad", 5))
        cfg["crop_pad"] = int(settings.value("vis/crop_pad", 20))
        cfg["last_folder"] = settings.value("paths/last_folder", "")
        return cfg

    # 🟢 [新增] 保存配置到 .ini
    def save_config(self, data):
        settings = QSettings(self.config_path, QSettings.Format.IniFormat)
        settings.setValue("params/effective_bits_idx", data.get("effective_bits_idx", 0))
        settings.setValue("params/channel_count_idx", data.get("channel_count_idx", 0))
        settings.setValue("params/use_robust", data.get("use_robust", True))
        settings.setValue("params/thresh_global_h", data.get("thresh_global_h", 20))
        settings.setValue("params/thresh_global_v", data.get("thresh_global_v", 20))
        settings.setValue("params/thresh_part_h", data.get("thresh_part_h", 10))
        settings.setValue("params/thresh_part_v", data.get("thresh_part_v", 10))
        settings.setValue("params/block_qty", data.get("block_qty", 10))
        settings.setValue("crop/strip_h", data.get("strip_h", 0))
        settings.setValue("crop/strip_v", data.get("strip_v", 0))
        settings.setValue("params/edge_gain", data.get("edge_gain", 1.0))
        settings.setValue("vis/vis_pad", data.get("vis_pad", 5))
        settings.setValue("vis/crop_pad", data.get("crop_pad", 20))
        settings.setValue("paths/last_folder", data.get("last_folder", ""))
        settings.sync()  # 强制写入磁盘
    def init_ui(self):
        main_widget = QWidget();
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        splitter_h = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter_h)

        # Left Panel
        panel_left = QWidget();
        l_layout = QVBoxLayout(panel_left)
        l_layout.setContentsMargins(5, 5, 5, 5);
        l_layout.setSpacing(8)

        grp_src = QGroupBox("1. SOURCE FOLDER")
        v_src = QVBoxLayout(grp_src)
        self.btn_open_folder = QPushButton("📂 Load Folder")
        self.btn_open_folder.clicked.connect(self.open_folder)
        v_src.addWidget(self.btn_open_folder)

        self.lbl_info = QLabel("No Folder Loaded")
        v_src.addWidget(self.lbl_info)
        self.list_files = QListWidget()
        self.list_files.setFixedHeight(120)
        self.list_files.itemClicked.connect(self.on_file_selected)
        v_src.addWidget(self.list_files)
        l_layout.addWidget(grp_src)

        h_batch_btns = QHBoxLayout()
        self.btn_pop_analysis = QPushButton("⚡ Batch")
        self.btn_pop_analysis.clicked.connect(self.open_batch_analysis_dialog)
        self.btn_pop_snap = QPushButton("✂️ Crop")
        self.btn_pop_snap.clicked.connect(self.open_batch_snap_dialog)
        h_batch_btns.addWidget(self.btn_pop_analysis)
        h_batch_btns.addWidget(self.btn_pop_snap)
        l_layout.addLayout(h_batch_btns)

        self.btn_toggle_params = QPushButton("▼ Hide Parameters")
        self.btn_toggle_params.setCheckable(True)
        self.btn_toggle_params.clicked.connect(self.toggle_parameters_panel)
        self.btn_toggle_params.setStyleSheet(
            "text-align: left; background: transparent; border: none; padding-left: 5px;")
        l_layout.addWidget(self.btn_toggle_params)

        left_v_splitter = QSplitter(Qt.Orientation.Vertical)
        l_layout.addWidget(left_v_splitter)

        self.params_run_container = QWidget()
        v_params_run = QVBoxLayout(self.params_run_container)
        v_params_run.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        pc = QWidget()
        vp_in = QVBoxLayout(pc)
        vp_in.setContentsMargins(0, 0, 5, 0)
        self._build_params_ui(vp_in)
        scroll.setWidget(pc)
        v_params_run.addWidget(scroll)

        self.btn_run = QPushButton("▶ RUN CURRENT IMAGE")
        self.btn_run.setFixedHeight(45)
        self.btn_run.clicked.connect(self.run_analysis)
        v_params_run.addWidget(self.btn_run)

        self.btn_export = QPushButton("📊 Export Excel Report")
        self.btn_export.setFixedHeight(40)
        self.btn_export.clicked.connect(self.export_excel_report)
        v_params_run.addWidget(self.btn_export)

        left_v_splitter.addWidget(self.params_run_container)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["CH", "Type", "Mode", "Idx", "Diff"])
        self.table.setSortingEnabled(True)  # 启用排序
        self.table.itemClicked.connect(self.on_table_click)
        left_v_splitter.addWidget(self.table)
        left_v_splitter.setSizes([700, 300])
        splitter_h.addWidget(panel_left)

        # Right Panel
        right_widget = QWidget()
        r_layout = QVBoxLayout(right_widget)
        r_layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(5, 5, 5, 5)
        self.btn_roi = QPushButton("🔲 Box Zoom (ROI)")
        self.btn_roi.setCheckable(True)
        self.btn_roi.toggled.connect(self.toggle_roi_mode)
        toolbar.addWidget(self.btn_roi)
        toolbar.addStretch()
        r_layout.addLayout(toolbar)

        self.info_bar = QFrame()
        self.info_bar.setFixedHeight(35)
        self.info_bar.setStyleSheet("background:#1a1a1a;border-bottom:1px solid #333;")
        il = QHBoxLayout(self.info_bar)
        il.setContentsMargins(10, 0, 10, 0)
        sl = "color: #00e676; font-weight: bold; font-family: Consolas; font-size: 11pt;"
        self.lbl_cursor_pos = QLabel("XY: - , -");
        self.lbl_cursor_pos.setStyleSheet(sl)
        self.lbl_cursor_val = QLabel("Val: -");
        self.lbl_cursor_val.setStyleSheet(sl)
        self.lbl_cursor_rdiff = QLabel("H-Diff: -");
        self.lbl_cursor_rdiff.setStyleSheet(sl)
        self.lbl_cursor_cdiff = QLabel("V-Diff: -");
        self.lbl_cursor_cdiff.setStyleSheet(sl)
        il.addWidget(QLabel("Probe:"))
        il.addWidget(self.lbl_cursor_pos);
        il.addSpacing(20)
        il.addWidget(self.lbl_cursor_val);
        il.addSpacing(20)
        il.addWidget(self.lbl_cursor_rdiff);
        il.addSpacing(20)
        il.addWidget(self.lbl_cursor_cdiff);
        il.addStretch()
        r_layout.addWidget(self.info_bar)

        splitter_v = QSplitter(Qt.Orientation.Vertical)
        self.view_main = ZoomableGraphicsView()
        self.view_main.sig_mouse_moved.connect(self.on_mouse_moved)
        self.view_main.sig_viewport_changed.connect(self.on_viewport_changed)
        self.view_main.sig_roi_selected.connect(self.on_roi_selected)

        splitter_v.addWidget(self.view_main)
        self.widget_charts = LineProfileWidget()
        self.widget_charts.sig_curve_clicked.connect(self.on_chart_click)
        self.widget_charts.sig_zoom_req.connect(self.on_chart_zoom_req)

        splitter_v.addWidget(self.widget_charts)
        splitter_v.setSizes([700, 300])
        r_layout.addWidget(splitter_v)

        splitter_h.addWidget(right_widget)
        splitter_h.setSizes([360, 1240])

    def _build_params_ui(self, layout):
        cfg = self.config
        grp_pre = QGroupBox("2. PRE-PROCESSING");
        f_pre = QVBoxLayout(grp_pre)
        h1 = QHBoxLayout();
        h1.addWidget(QLabel("Bits:"));
        self.combo_bits = QComboBox();
        self.combo_bits.addItems(["16-bit (Original)", "10-bit", "12-bit", "14-bit"]);
        self.combo_bits.setCurrentIndex(cfg.get("effective_bits_idx", 0));
        h1.addWidget(self.combo_bits)
        h2 = QHBoxLayout();
        h2.addWidget(QLabel("Chns:"));
        self.combo_ch = QComboBox();
        self.combo_ch.addItems(["4", "16", "64"]);
        self.combo_ch.setCurrentIndex(cfg.get("channel_count_idx", 0));
        h2.addWidget(self.combo_ch)
        self.chk_robust = QCheckBox("Robust (Anti-Interference)");
        self.chk_robust.setChecked(cfg.get("use_robust", True))
        f_pre.addLayout(h1);
        f_pre.addLayout(h2);
        f_pre.addWidget(self.chk_robust);
        layout.addWidget(grp_pre)
        grp_th = QGroupBox("3. THRESHOLDS");
        f_th = QVBoxLayout(grp_th)
        h_g = QHBoxLayout();
        self.sb_g_h = self._spin(cfg.get("thresh_global_h", 20));
        h_g.addWidget(QLabel("G H/V:"));
        h_g.addWidget(self.sb_g_h);
        self.sb_g_v = self._spin(cfg.get("thresh_global_v", 20));
        h_g.addWidget(self.sb_g_v);
        f_th.addLayout(h_g)
        h_p = QHBoxLayout();
        self.sb_p_h = self._spin(cfg.get("thresh_part_h", 10));
        h_p.addWidget(QLabel("P H/V:"));
        h_p.addWidget(self.sb_p_h);
        self.sb_p_v = self._spin(cfg.get("thresh_part_v", 10));
        h_p.addWidget(self.sb_p_v);
        f_th.addLayout(h_p)
        self.sb_blk = self._spin(cfg.get("block_qty", 10), 100);
        f_th.addWidget(QLabel("Block Qty:"));
        f_th.addWidget(self.sb_blk);
        layout.addWidget(grp_th)
        grp_ed = QGroupBox("4. CROP & EDGE");
        f_ed = QVBoxLayout(grp_ed)
        h_c = QHBoxLayout();
        self.sb_strip_h = self._spin(cfg.get("strip_h", 0), 5000);
        h_c.addWidget(QLabel("Strip:"));
        h_c.addWidget(self.sb_strip_h);
        self.sb_strip_v = self._spin(cfg.get("strip_v", 0), 5000);
        h_c.addWidget(self.sb_strip_v);
        f_ed.addLayout(h_c)
        self.dsb_edge = QDoubleSpinBox();
        self.dsb_edge.setValue(cfg.get("edge_gain", 1.0));
        f_ed.addWidget(QLabel("Edge Gain:"));
        f_ed.addWidget(self.dsb_edge);
        layout.addWidget(grp_ed)
        grp_vis = QGroupBox("5. VISUAL");
        f_vis = QVBoxLayout(grp_vis)
        self.sb_vis_pad = self._spin(cfg.get("vis_pad", 5), 100);
        f_vis.addWidget(QLabel("Box Pad:"));
        f_vis.addWidget(self.sb_vis_pad);
        self.sb_exp_pad = self._spin(cfg.get("crop_pad", 20), 500);
        f_vis.addWidget(QLabel("Crop Pad:"));
        f_vis.addWidget(self.sb_exp_pad);
        layout.addWidget(grp_vis)

    def on_viewport_changed(self, visible_rect):
        if self.sync_driver == 'CHART': return
        self.sync_driver = 'IMG';
        self.widget_charts.set_axis_zoom(visible_rect);
        self.sync_driver = None

    def on_roi_selected(self, x, y, w, h):
        if self.current_img is None: return
        self.view_main.fitInView(QRectF(x, y, w, h), Qt.AspectRatioMode.KeepAspectRatio)
        self.btn_roi.setChecked(False)

    def on_chart_zoom_req(self, min_val, max_val, orientation):
        if self.sync_driver == 'IMG': return
        self.sync_driver = 'CHART';
        self.pending_chart_req = (min_val, max_val, orientation);
        self.chart_sync_timer.start()

    def _execute_chart_driven_sync(self):
        if not self.pending_chart_req or self.current_img is None: self.sync_driver = None; return
        min_v, max_v, ori = self.pending_chart_req;
        current_rect = self.view_main.mapToScene(self.view_main.viewport().rect()).boundingRect()
        vp_w = self.view_main.viewport().width();
        vp_h = self.view_main.viewport().height();
        aspect_ratio = vp_w / (vp_h if vp_h else 1);
        target_rect = None
        if ori == 'H':
            target_h = max_v - min_v; target_w = target_h * aspect_ratio; center_x = current_rect.center().x(); target_rect = QRectF(
                center_x - target_w / 2, min_v, target_w, target_h)
        else:
            target_w = max_v - min_v; target_h = target_w / aspect_ratio; center_y = current_rect.center().y(); target_rect = QRectF(
                min_v, center_y - target_h / 2, target_w, target_h)
        if target_rect.width() > 1 and target_rect.height() > 1: self.view_main.fitInView(target_rect,
                                                                                          Qt.AspectRatioMode.KeepAspectRatio)
        self.sync_driver = None

    def export_excel_report(self):
        if not self.defects or self.current_img is None:
            QMessageBox.warning(self, "Warning", "No defects to export!")
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Save", "Single_Report.xlsx", "Excel (*.xlsx)")
        if not save_path: return
        temp_dir = os.path.join(os.getcwd(), "temp_crops_single")
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        pad = self.sb_exp_pad.value();
        block_n = self.sb_blk.value()
        img_src = self.processed_img if self.processed_img is not None else self.current_img
        h, w = img_src.shape[:2];
        blk_h, blk_w = h // block_n, w // block_n
        try:
            workbook = xlsxwriter.Workbook(save_path);
            ws = workbook.add_worksheet("Defect List")
            fmt_header = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
            fmt_cell = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
            ws.write_row('A1', ["ID", "Channel", "Type", "Mode", "Index", "Diff Value", "Image"], fmt_header)
            ws.set_column('A:F', 10);
            ws.set_column('G:G', 50)
            for i, d in enumerate(self.defects):
                idx = d['index'];
                x0, x1, y0, y1 = 0, w, 0, h
                if "Part" in d['mode']:
                    try:
                        parts = d['mode'].replace("Part(", "").replace(")", "").split(",")
                        by, bx = int(parts[0]), int(parts[1])
                        if d['type'] == 'Horizontal':
                            x0, x1 = bx * blk_w, (bx + 1) * blk_w
                        else:
                            y0, y1 = by * blk_h, (by + 1) * blk_h
                    except:
                        pass

                crop = None
                if d['type'] == 'Horizontal':
                    cy0 = max(0, idx - pad);
                    cy1 = min(h, idx + pad);
                    crop = img_src[cy0:cy1, x0:x1]
                else:
                    cx0 = max(0, idx - pad);
                    cx1 = min(w, idx + pad);
                    crop = img_src[y0:y1, cx0:cx1]
                    if crop.size > 0: crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)

                if crop.size == 0: continue
                if crop.dtype == np.uint16:
                    vis_crop = cv2.normalize(crop, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                else:
                    vis_crop = crop.astype(np.uint8)
                img_name = f"temp_{i}.png";
                img_path = os.path.join(temp_dir, img_name)
                cv2.imwrite(img_path, vis_crop)
                row = i + 1
                ws.write(row, 0, i + 1, fmt_cell);
                ws.write(row, 1, d['ch'], fmt_cell);
                ws.write(row, 2, d['type'], fmt_cell)
                ws.write(row, 3, d['mode'], fmt_cell);
                ws.write(row, 4, d['index'], fmt_cell);
                ws.write(row, 5, round(d['diff'], 2), fmt_cell)
                ws.set_row(row, 100)
                ws.insert_image(row, 6, img_path,
                                {'x_scale': 0.5, 'y_scale': 0.5, 'object_position': 1, 'x_offset': 5, 'y_offset': 5})
            workbook.close()
            QMessageBox.information(self, "Success", f"Report saved:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed:\n{str(e)}")
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)

    # 🟢 [修改] 3. 关闭时保存到 ini
    def closeEvent(self, event):
        data = {
            "effective_bits_idx": self.combo_bits.currentIndex(),
            "channel_count_idx": self.combo_ch.currentIndex(),
            "use_robust": self.chk_robust.isChecked(),
            "thresh_global_h": self.sb_g_h.value(),
            "thresh_global_v": self.sb_g_v.value(),
            "thresh_part_h": self.sb_p_h.value(),
            "thresh_part_v": self.sb_p_v.value(),
            "block_qty": self.sb_blk.value(),
            "strip_h": self.sb_strip_h.value(),
            "strip_v": self.sb_strip_v.value(),
            "edge_gain": self.dsb_edge.value(),
            "vis_pad": self.sb_vis_pad.value(),
            "crop_pad": self.sb_exp_pad.value(),
            "last_folder": self.current_folder
        }
        # 调用类内部的保存方法，不再使用 ConfigManager
        self.save_config(data)
        super().closeEvent(event)

    # 🟢 修复：添加丢失的 load_source_folder 函数
    def load_source_folder(self, folder_path):
        self.current_folder = folder_path
        exts = {'.png', '.tif', '.tiff', '.raw', '.bmp'}
        try:
            self.file_list = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if
                              Path(f).suffix.lower() in exts]
            self.file_list.sort()
            self.list_files.clear()
            for f in self.file_list: self.list_files.addItem(Path(f).name)
            self.lbl_info.setText(f"{len(self.file_list)} loaded")
            if self.file_list: self.list_files.setCurrentRow(0); self.load_image(self.file_list[0])
        except Exception as e:
            print(f"Error loading folder: {e}")

    # 🟢 修复：添加丢失的 open_folder 函数
    def open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Src");
        if d: self.load_source_folder(d)

    def clear_defect_items(self):
        if hasattr(self, 'defect_items'):
            for item in self.defect_items:
                try:
                    if item.scene() is not None: self.view_main.scene_obj.removeItem(item)
                except:
                    pass
        self.defect_items = []

    def run_analysis(self):
        if self.current_img is None: return
        params = self._get_current_params()
        self.btn_run.setText("RUNNING...")
        QApplication.processEvents()
        self.processed_img = LineDefectAlgorithm.restore_image(self.current_img, params['effective_bits'])
        self.defects, stats = LineDefectAlgorithm.run_inspection(self.processed_img, params, is_preprocessed=True)
        self.last_stats = stats
        self.sync_driver = 'IMG'
        self.widget_charts.update_data(stats['row_avg'], stats['row_diff'], stats['col_avg'], stats['col_diff'], 0, 0)
        self.sync_driver = None

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for i, d in enumerate(self.defects):
            row = self.table.rowCount();
            self.table.insertRow(row)

            it0 = QTableWidgetItem();
            it0.setData(Qt.ItemDataRole.DisplayRole, d['ch']);
            it0.setData(Qt.ItemDataRole.UserRole, i);
            self.table.setItem(row, 0, it0)
            it1 = QTableWidgetItem(d['type']);
            it1.setData(Qt.ItemDataRole.UserRole, i);
            self.table.setItem(row, 1, it1)
            it2 = QTableWidgetItem(d['mode']);
            it2.setData(Qt.ItemDataRole.UserRole, i);
            self.table.setItem(row, 2, it2)
            it3 = QTableWidgetItem();
            it3.setData(Qt.ItemDataRole.DisplayRole, d['index']);
            it3.setData(Qt.ItemDataRole.UserRole, i);
            self.table.setItem(row, 3, it3)
            it4 = QTableWidgetItem();
            it4.setData(Qt.ItemDataRole.DisplayRole, round(d['diff'], 1));
            it4.setData(Qt.ItemDataRole.UserRole, i);
            self.table.setItem(row, 4, it4)

        self.table.setSortingEnabled(True)
        self.draw_defect_visualization()
        self.btn_run.setText("▶ RUN CURRENT IMAGE")

    def load_image(self, path):
        self.current_img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if self.current_img is None: return
        h, w = self.current_img.shape[:2]
        self.lbl_info.setText(f"{Path(path).name}\n{w}x{h} | {self.current_img.dtype}")
        if self.current_img.dtype == np.uint16:
            vis = cv2.normalize(self.current_img, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
        else:
            vis = self.current_img.astype(np.uint8)
        self.view_main.set_image(vis)
        self.clear_defect_items()
        self.processed_img = None;
        self.last_stats = None
        self.lbl_cursor_rdiff.setText("H-Diff: -");
        self.lbl_cursor_cdiff.setText("V-Diff: -")

    def open_batch_snap_dialog(self):
        if self.file_list:
            BatchSnapDialog(self.file_list, self.current_folder, self).exec()
        else:
            QMessageBox.warning(self, "Warn", "No files")

    def open_batch_analysis_dialog(self):
        if self.file_list:
            BatchAnalysisDialog(self._get_current_params(), self.current_folder, self).exec()
        else:
            QMessageBox.warning(self, "Warn", "No files")

    def toggle_parameters_panel(self):
        v = self.params_run_container.isVisible();
        self.params_run_container.setVisible(not v);
        self.btn_toggle_params.setText("▲ Show" if v else "▼ Hide")

    def on_file_selected(self, item):
        for f in self.file_list:
            if Path(f).name == item.text(): self.load_image(f); break

    def toggle_roi_mode(self, checked):
        if self.current_img is None: self.btn_roi.setChecked(False); return
        self.view_main.set_roi_mode(checked)

    def restore_full_charts(self):
        if self.last_stats:
            self.sync_driver = 'IMG'
            self.widget_charts.update_data(self.last_stats['row_avg'], self.last_stats['row_diff'],
                                           self.last_stats['col_avg'], self.last_stats['col_diff'], 0, 0)
            self.sync_driver = None

    def _spin(self, v, m=65535):
        s = QSpinBox(); s.setRange(0, m); s.setValue(int(v)); return s

    def _get_current_params(self):
        b = 16;
        t = self.combo_bits.currentText();
        if '10' in t:
            b = 10
        elif '12' in t:
            b = 12
        elif '14' in t:
            b = 14
        c = 4;
        t = self.combo_ch.currentText();
        if '16' in t:
            c = 16
        elif '64' in t:
            c = 64
        return {'effective_bits': b, 'channel_count': c, 'edge_gain': self.dsb_edge.value(),
                'thresh_global_h': self.sb_g_h.value(), 'thresh_global_v': self.sb_g_v.value(),
                'thresh_part_h': self.sb_p_h.value(), 'thresh_part_v': self.sb_p_v.value(),
                'block_qty': self.sb_blk.value(), 'strip_h': self.sb_strip_h.value(),
                'strip_v': self.sb_strip_v.value(),
                'use_robust': 1 if self.chk_robust.isChecked() else 0}

    def on_mouse_moved(self, x, y):
        if self.current_img is None: return
        h, w = self.current_img.shape[:2]

        if 0 <= x < w and 0 <= y < h:
            # 1. 获取原始像素值
            raw_val = self.current_img[y, x]

            # 2. 获取目标位深 (10/12/14/16)
            target_bits = 16
            txt = self.combo_bits.currentText()
            if '10' in txt:
                target_bits = 10
            elif '12' in txt:
                target_bits = 12
            elif '14' in txt:
                target_bits = 14

            # 3. 换算数值 (仅针对 16-bit 图)
            # 假设图像数据是高位对齐 (MSB Aligned) 存储在 16-bit 中的
            # 例如 10-bit 数据: 0-1023 映射到 0-65535，需要右移 6 位还原
            disp_val = raw_val
            if self.current_img.dtype == np.uint16:
                shift = max(0, 16 - target_bits)
                disp_val = raw_val >> shift

            # 4. 更新显示
            self.lbl_cursor_pos.setText(f"XY: {x}, {y}")
            self.lbl_cursor_val.setText(f"Val: {disp_val}")

            # 更新差分值显示
            if self.last_stats:
                try:
                    self.lbl_cursor_rdiff.setText(f"H:{self.last_stats['row_diff'][y]:.1f}")
                    self.lbl_cursor_cdiff.setText(f"V:{self.last_stats['col_diff'][x]:.1f}")
                except:
                    pass
        else:
            self.lbl_cursor_pos.setText("XY: - , -")

    def on_table_click(self, item):
        original_idx = item.data(Qt.ItemDataRole.UserRole)
        if original_idx is not None and 0 <= original_idx < len(self.defects):
            d = self.defects[original_idx];
            idx = d['index']
            if d['type'] == 'Horizontal':
                self.view_main.centerOn(0, idx)
            else:
                self.view_main.centerOn(idx, 0)

    def on_chart_click(self, o, i):
        if o == 'H':
            self.view_main.centerOn(0, i); self.view_main.highlight_defect(self.view_main.sceneRect().center().x(), i)
        else:
            self.view_main.centerOn(i, 0); self.view_main.highlight_defect(i, self.view_main.sceneRect().center().y())

    def draw_defect_visualization(self):
        self.clear_defect_items()
        pad = self.sb_vis_pad.value();
        h, w = self.current_img.shape[:2]
        for d in self.defects:
            idx = d['index'];
            p = QPen(QColor("#ff1744") if d['type'] == 'Horizontal' else QColor("#2979ff"), 2);
            p.setCosmetic(True)
            if d['type'] == 'Horizontal':
                y0 = max(0, idx - pad); self.defect_items.append(
                    self.view_main.scene_obj.addRect(0, y0, w, min(h, idx + pad) - y0, p))
            else:
                x0 = max(0, idx - pad); self.defect_items.append(
                    self.view_main.scene_obj.addRect(x0, 0, min(w, idx + pad) - x0, h, p))

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI'; font-size: 10pt; }
            QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2d2d2d, stop:1 #1a1a1a); border: 1px solid #444; border-bottom: 2px solid #333; color: #ccc; padding: 6px 12px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { border: 1px solid #00e676; color: #00e676; }
            QPushButton:pressed { background-color: #00e676; color: #000; }
            QLineEdit, QSpinBox, QComboBox { background-color: #0f0f0f; border: 1px solid #333; padding: 5px; color: #00e676; font-family: 'Consolas'; border-radius: 3px; }
            QGroupBox { border: 1px solid #333; margin-top: 20px; font-weight: bold; color: #888; border-radius: 4px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background-color: #121212; color: #00e676; }
            QListWidget, QTableWidget { background-color: #0a0a0a; border: 1px solid #333; outline: none; }
            QListWidget::item:selected, QTableWidget::item:selected { background-color: rgba(0, 230, 118, 0.2); border: 1px solid #00e676; color: #fff; }
            QHeaderView::section { background-color: #1a1a1a; color: #888; padding: 6px; border: none; border-bottom: 2px solid #333; }
            QTableCornerButton::section { background-color: #1a1a1a; border: 1px solid #333; }
            QHeaderView { background-color: #1a1a1a; }
            QSplitter::handle { background-color: #222; }
            QSplitter::handle:hover { background-color: #00e676; }
        """)


# line_inspector.py 的最后几行
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = LineInspectorApp() # 👈 记住这个类名
    win.show()
    sys.exit(app.exec())