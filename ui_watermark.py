# -*- coding: utf-8 -*-
"""隐形水印 GUI：基于 PySide6 + blind_watermark 的图片/文字水印工具。

功能：嵌入图片水印、嵌入文字水印、批量处理、提取水印、设置。
运行：python ui_watermark.py
打包：见 README.md（PyInstaller + Inno Setup）。
"""

import sys
import traceback
from pathlib import Path

# ---- 基础依赖：GUI 框架本身缺失时无法弹窗，只能写日志并退出 ----
try:
    import numpy as np
    from PySide6.QtCore import Qt, QThread, Signal, QStandardPaths, QSettings
    from PySide6.QtGui import QIcon, QPalette, QColor
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLineEdit,
        QLabel,
        QMessageBox,
        QPushButton,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except Exception:
    _tb = traceback.format_exc()
    try:
        Path("error.log").write_text(_tb, encoding="utf-8")
    except Exception:
        pass
    sys.stderr.write(_tb)
    raise


def _init_engine():
    """初始化水印引擎（cv2 + blind_watermark）。

    必须在 QApplication 创建之后调用，这样失败时才能正常弹窗提示用户，
    避免在无 QApplication 的情况下弹窗导致进程直接中止（闪退）。

    注意：这里直接使用真实 OpenCV（opencv-python-headless），不再用 Pillow
    伪造 cv2。伪造的 stub 会让 DCT/SVD 全部失真、且与打包进 exe 的真实 cv2
    行为不一致，是之前“点击嵌入就崩溃”的根本原因。
    """
    global cv2, WaterMark
    import cv2 as _cv2
    cv2 = _cv2
    from blind_watermark import WaterMark as _WM
    WaterMark = _WM


class WorkerThread(QThread):
    """后台线程，用于执行耗时的水印操作，防止 UI 卡顿。

    注意：这里不能自定义一个名为 ``finished`` 的信号，否则会遮蔽 QThread
    内置的 ``finished`` 信号；而内置 ``finished`` 只在 ``run()`` 真正返回、
    底层线程确实停止后才发出，是安全的清理时机。我们改用 ``result`` 信号
    回传结果。
    """

    result = Signal(str)
    error = Signal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            value = self._func(*self._args, **self._kwargs)
            self.result.emit(str(value))
        except Exception as exc:
            tb = traceback.format_exc()
            self.error.emit(f"{exc}\n{tb}")


class WatermarkApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Blind Watermark GUI")
        self.setWindowIcon(QIcon())  # 可自行添加图标文件
        self.resize(600, 400)

        # 持久化设置：优先读取用户上次保存的默认输出目录
        self._settings = QSettings("BlindWatermark", "BlindWatermarkGUI")
        saved_dir = self._settings.value("default_out_dir", "")
        if saved_dir:
            self._default_out_dir = str(saved_dir)
        else:
            self._default_out_dir = self._build_default_out_dir()

        self.tabs = QTabWidget()
        self.tabs.addTab(self._embed_text_tab(), "嵌入文字水印")
        self.tabs.addTab(self._embed_image_tab(), "嵌入图片水印")
        self.tabs.addTab(self._batch_tab(), "批量处理")
        self.tabs.addTab(self._extract_tab(), "提取水印")
        self.tabs.addTab(self._settings_tab(), "设置")

        # 已移除自动关机选项

        # 用于在关闭窗口时管理正在运行的线程
        self._active_threads = []

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)
    # ---------------------------------------------------------------------
    # Tab: 嵌入图片水印
    # ---------------------------------------------------------------------
    def _embed_image_tab(self):
        widget = QWidget()
        layout = QFormLayout()

        self.embed_img_src = QLineEdit()
        layout.addRow(*self._file_row(self.embed_img_src, "原图文件:"))

        self.embed_img_wm = QLineEdit()
        layout.addRow(*self._file_row(self.embed_img_wm, "水印图片:"))

        self.embed_img_pwd = QLineEdit()
        self.embed_img_pwd.setPlaceholderText("仅支持整数")
        layout.addRow("密码img：", self.embed_img_pwd)

        self.embed_img_pwd_wm = QLineEdit()
        self.embed_img_pwd_wm.setPlaceholderText("仅支持整数")
        layout.addRow("密码wm：", self.embed_img_pwd_wm)

        self.embed_img_out = QLineEdit(self._default_out_dir)
        layout.addRow(*self._file_row(self.embed_img_out, "输出文件夹:", folder=True))

        self.embed_img_btn = QPushButton("开始嵌入")
        self.embed_img_btn.clicked.connect(self._run_embed_image)
        layout.addRow(self.embed_img_btn)

        self.embed_img_log = QTextEdit()
        self.embed_img_log.setReadOnly(True)
        layout.addRow(self.embed_img_log)

        widget.setLayout(layout)
        return widget

    # ---------------------------------------------------------------------
    # Tab: 嵌入文字水印
    # ---------------------------------------------------------------------
    def _embed_text_tab(self):
        widget = QWidget()
        layout = QFormLayout()

        self.embed_txt_src = QLineEdit()
        layout.addRow(*self._file_row(self.embed_txt_src, "原图文件:"))

        self.embed_txt_content = QTextEdit()
        self.embed_txt_content.setPlaceholderText("请输入文本")
        layout.addRow("文字水印内容:", self.embed_txt_content)

        self.embed_txt_pwd = QLineEdit()
        self.embed_txt_pwd.setPlaceholderText("仅支持整数")
        layout.addRow("密码img：", self.embed_txt_pwd)

        self.embed_txt_pwd_wm = QLineEdit()
        self.embed_txt_pwd_wm.setPlaceholderText("仅支持整数")
        layout.addRow("密码wm：", self.embed_txt_pwd_wm)

        self.embed_txt_out = QLineEdit(self._default_out_dir)
        layout.addRow(*self._file_row(self.embed_txt_out, "输出文件夹:", folder=True))

        self.embed_txt_btn = QPushButton("开始嵌入文字水印")
        self.embed_txt_btn.clicked.connect(self._run_embed_text)
        layout.addRow(self.embed_txt_btn)

        self.embed_txt_log = QTextEdit()
        self.embed_txt_log.setReadOnly(True)
        layout.addRow(self.embed_txt_log)

        widget.setLayout(layout)
        return widget

    # ---------------------------------------------------------------------
    # Tab: 提取水印
    # ---------------------------------------------------------------------
    def _extract_tab(self):
        widget = QWidget()
        layout = QFormLayout()

        self.extract_src = QLineEdit()
        layout.addRow(*self._file_row(self.extract_src, "嵌入后图片:"))

        self.extract_pwd_img = QLineEdit()
        self.extract_pwd_img.setPlaceholderText("仅支持整数")
        layout.addRow("密码img：", self.extract_pwd_img)

        self.extract_pwd_wm = QLineEdit()
        self.extract_pwd_wm.setPlaceholderText("仅支持整数")
        layout.addRow("密码wm：", self.extract_pwd_wm)

        self.extract_bits = QLineEdit()
        self.extract_bits.setPlaceholderText("bit")
        layout.addRow("水印位数：", self.extract_bits)

        self.extract_mode = QComboBox()
        self.extract_mode.addItem("文字水印（字符串）", "str")
        self.extract_mode.addItem("位图水印（0/1 数组）", "bit")
        self.extract_mode.addItem("图片水印", "img")
        layout.addRow("提取模式:", self.extract_mode)

        self.extract_btn = QPushButton("开始提取")
        self.extract_btn.clicked.connect(self._run_extract)
        layout.addRow(self.extract_btn)

        self.extract_log = QTextEdit()
        self.extract_log.setReadOnly(True)
        layout.addRow(self.extract_log)

        widget.setLayout(layout)
        return widget

    # ---------------------------------------------------------------------
    # Tab: 批量处理（仅支持图片水印嵌入示例）
    # ---------------------------------------------------------------------
    def _batch_tab(self):
        widget = QWidget()
        layout = QFormLayout()

        self.batch_src_dir = QLineEdit()
        layout.addRow(*self._file_row(self.batch_src_dir, "原图片文件夹:", folder=True))

        self.batch_wm_img = QLineEdit()
        layout.addRow(*self._file_row(self.batch_wm_img, "水印图片:"))

        self.batch_pwd_img = QLineEdit()
        self.batch_pwd_img.setPlaceholderText("仅支持整数")
        layout.addRow("密码img：", self.batch_pwd_img)

        self.batch_pwd_wm = QLineEdit()
        self.batch_pwd_wm.setPlaceholderText("仅支持整数")
        layout.addRow("密码wm：", self.batch_pwd_wm)

        self.batch_out_dir = QLineEdit(self._default_out_dir)
        layout.addRow(*self._file_row(self.batch_out_dir, "输出文件夹:", folder=True))

        self.batch_btn = QPushButton("开始批量嵌入")
        self.batch_btn.clicked.connect(self._run_batch)
        layout.addRow(self.batch_btn)

        self.batch_log = QTextEdit()
        self.batch_log.setReadOnly(True)
        layout.addRow(self.batch_log)

        widget.setLayout(layout)
        return widget

    # ---------------------------------------------------------------------
    # 通用文件/文件夹选择器
    # ---------------------------------------------------------------------
    def _browse_file(self, line_edit: QLineEdit):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "All Files (*)")
        if file_path:
            line_edit.setText(file_path)

    def _browse_folder(self, line_edit: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹", "")
        if folder:
            line_edit.setText(folder)

    def _file_row(self, line_edit: QLineEdit, label: str, folder: bool = False):
        """构建「标签 + 输入框 + 浏览器」一行，返回可让 addRow 使用的组件。

        folder=True 时用文件夹选择器，否则用文件选择器。
        """
        btn = QPushButton("浏览文件夹" if folder else "浏览")
        handler = self._browse_folder if folder else self._browse_file
        btn.clicked.connect(lambda: handler(line_edit))
        row = QHBoxLayout()
        row.addWidget(line_edit)
        row.addWidget(btn)
        return label, row

    # ---------------------------------------------------------------------
    # Tab: 设置
    # ---------------------------------------------------------------------
    def _settings_tab(self):
        widget = QWidget()
        layout = QFormLayout()

        self.settings_out = QLineEdit(self._default_out_dir)
        layout.addRow(*self._file_row(self.settings_out, "默认输出文件夹:", folder=True))

        hint = QLabel("设置后嵌入水印的输出文件夹默认使用该路径。")
        hint.setWordWrap(True)
        layout.addRow(hint)

        self.settings_save_btn = QPushButton("保存默认输出文件夹")
        self.settings_save_btn.clicked.connect(self._save_default_out_dir)
        layout.addRow(self.settings_save_btn)

        self.settings_status = QLabel("")
        layout.addRow(self.settings_status)

        widget.setLayout(layout)
        return widget

    def _save_default_out_dir(self):
        """保存用户设置的默认输出目录到 QSettings，并同步更新三个嵌入页。"""
        path = self.settings_out.text().strip()
        if not path:
            QMessageBox.warning(self, "设置", "输出文件夹不能为空。")
            return
        # 尝试创建目录，确保路径可用
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "设置", f"无法创建该文件夹：\n{e}")
            return
        self._default_out_dir = path
        self._settings.setValue("default_out_dir", path)
        # 同步更新三个嵌入页的输出框
        self.embed_img_out.setText(path)
        self.embed_txt_out.setText(path)
        self.batch_out_dir.setText(path)
        self.settings_status.setText("已保存，下次启动将自动使用。")

    def _build_default_out_dir(self):
        """返回默认输出目录：系统“图片”文件夹下的“隐形水印”子文件夹。

        若系统图片目录不可用，则回退到用户主目录下的 Pictures 文件夹；
        最终目录不存在时会尝试创建。
        """
        pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        if not pics:
            pics = str(Path.home() / "Pictures")
        out_dir = Path(pics) / "隐形水印"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return str(out_dir)

    def _read_image_or_none(self, path):
        """读取图片；失败时弹窗并返回 None，绝不让异常抛出槽函数导致闪退。

        使用 Unicode 兼容的读图方式（np.fromfile + imdecode），因为 cv2.imread
        在 Windows 下无法处理中文/非 ASCII 路径，会静默返回 None 导致“无反应”。
        """
        try:
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                QMessageBox.warning(self, "文件错误", f"无法读取图片：\n{path}\n\n请确认文件路径正确且文件未损坏。")
            return img
        except Exception as e:
            QMessageBox.warning(self, "文件错误", f"无法读取图片：\n{path}\n\n{e}")
            return None

    @staticmethod
    def _capacity(img):
        """返回图片可容纳的水印位数（与 blind_watermark 分块逻辑保持一致）。"""
        h, w = img.shape[:2]
        return ((h + 1) // 2 // 4) * ((w + 1) // 2 // 4)

    def _start_worker(self, func, log_widget, *args):
        """启动一个后台线程执行水印操作。

        关键点：线程对象的清理必须挂在 QThread **内置** 的 ``finished`` 信号上
        （它在 run() 返回、底层线程停止后才发出），而绝不能挂在自定义信号上，
        否则会在线程仍在运行时销毁其对象，触发
        “QThread: Destroyed while thread is still running” 导致闪退。
        """
        thread = WorkerThread(func, *args)
        self._active_threads.append(thread)
        thread.result.connect(lambda msg: log_widget.append(msg))
        thread.error.connect(lambda e: log_widget.append(f"错误: {e}"))
        # 用内置 finished 信号做清理（run() 返回后才发出），线程对象让 Qt 延迟销毁
        thread.finished.connect(lambda t=thread: self._on_thread_done(t))
        thread.start()

    def _on_thread_done(self, thread):
        """线程真正停止后的安全清理：先从活动列表移除，再让 Qt 回收对象。"""
        if thread in self._active_threads:
            self._active_threads.remove(thread)
        thread.deleteLater()

    def _next_output_name(self, out_dir, pwd_img, pwd_wm, bits, ext):
        """按模板生成不覆盖已有文件的输出名。

        模板：序号-password_img-password_wm-水印位数-扩展名（如 1-1-1-48.png）。
        若目录中已存在同名文件，则序号从 1 开始自动递增（1→2→3…），
        避免新文件覆盖旧文件。
        """
        out_dir = Path(out_dir)
        ext = ext if ext.startswith(".") else "." + ext
        seq = 1
        while True:
            name = f"{seq}-{pwd_img}-{pwd_wm}-{bits}{ext}"
            if not (out_dir / name).exists():
                return out_dir / name
            seq += 1

    # ---------------------------------------------------------------------
    # 嵌入图片水印实现
    # ---------------------------------------------------------------------
    def _run_embed_image(self):
        src = self.embed_img_src.text().strip()
        wm = self.embed_img_wm.text().strip()
        out_dir = self.embed_img_out.text().strip()
        try:
            pwd_img = int(self.embed_img_pwd.text().strip())
            pwd_wm = int(self.embed_img_pwd_wm.text().strip())
        except ValueError:
            QMessageBox.warning(self, "参数错误", "密码必须为整数。")
            return
        if not all([src, wm, out_dir]):
            QMessageBox.warning(self, "缺少参数", "请完整填写所有路径。")
            return
        # 检查水印容量是否足够
        src_img = self._read_image_or_none(src)
        wm_img = self._read_image_or_none(wm)
        if src_img is None or wm_img is None:
            QMessageBox.warning(self, "文件错误", "无法读取原图或水印图片，请检查路径。")
            return
        wm_bits = int((wm_img[:, :, 0] > 128).sum())
        if wm_bits > self._capacity(src_img):
            QMessageBox.warning(self, "水印太大", f"当前水印位数 {wm_bits} 超过可嵌入容量 {self._capacity(src_img)}，请使用更小的水印或更大的原图。")
            return

        self.embed_img_log.append("开始嵌入图片水印…")
        self._start_worker(self._embed_image_worker, self.embed_img_log, src, wm, out_dir, pwd_img, pwd_wm)
    def _embed_image_worker(self, src, wm, out_dir, pwd_img, pwd_wm):
        bwm = WaterMark(password_wm=pwd_wm, password_img=pwd_img)
        bwm.read_img(src)
        bwm.read_wm(wm)
        # 命名模板：序号-password_img-password_wm-水印位数-扩展名
        # 序号自动递增，避免覆盖已有文件
        bits = len(bwm.wm_bit)
        ext = Path(src).suffix
        out_path = self._next_output_name(out_dir, pwd_img, pwd_wm, bits, ext)
        bwm.embed(str(out_path))
        return f"已生成 {out_path}"

    # ---------------------------------------------------------------------
    # 嵌入文字水印实现
    # ---------------------------------------------------------------------
    def _run_embed_text(self):
        src = self.embed_txt_src.text().strip()
        text = self.embed_txt_content.toPlainText().strip()
        out_dir = self.embed_txt_out.text().strip()
        try:
            pwd_img = int(self.embed_txt_pwd.text().strip())
            pwd_wm = int(self.embed_txt_pwd_wm.text().strip())
        except ValueError:
            QMessageBox.warning(self, "参数错误", "密码必须为整数。")
            return
        if not all([src, text, out_dir]):
            QMessageBox.warning(self, "缺少参数", "请完整填写所有字段。")
            return
        # 检查文字水印的位数是否超过可嵌入容量（读取失败时给出提示而不是崩溃）
        src_img = self._read_image_or_none(src)
        if src_img is None:
            return
        text_bits = len(text.encode('utf-8')) * 8
        if text_bits > self._capacity(src_img):
            QMessageBox.warning(self, "文字水印太大", f"当前文字位数 {text_bits} 超过可嵌入容量 {self._capacity(src_img)}，请使用更短的文字或更大的原图。")
            return

        self.embed_txt_log.append("开始嵌入文字水印…")
        self._start_worker(self._embed_text_worker, self.embed_txt_log, src, text, out_dir, pwd_img, pwd_wm)

    def _embed_text_worker(self, src, text, out_dir, pwd_img, pwd_wm):
        bwm = WaterMark(password_wm=pwd_wm, password_img=pwd_img)
        bwm.read_img(src)
        bwm.read_wm(text, mode="str")
        bits = len(text.encode("utf-8")) * 8  # 近似位数
        ext = Path(src).suffix
        # 命名模板：序号-password_img-password_wm-水印位数-扩展名
        # 序号自动递增，避免覆盖已有文件
        out_path = self._next_output_name(out_dir, pwd_img, pwd_wm, bits, ext)
        bwm.embed(str(out_path))
        return f"已生成 {out_path}"

    # ---------------------------------------------------------------------
    # 提取水印实现
    # ---------------------------------------------------------------------
    def _run_extract(self):
        src = self.extract_src.text().strip()
        try:
            pwd_img = int(self.extract_pwd_img.text().strip())
            pwd_wm = int(self.extract_pwd_wm.text().strip())
        except ValueError:
            QMessageBox.warning(self, "参数错误", "密码必须为整数。")
            return
        try:
            bits = int(self.extract_bits.text().strip())
        except ValueError:
            bits = None
        mode = self.extract_mode.currentData()
        if not src:
            QMessageBox.warning(self, "缺少参数", "请选择嵌入后图片文件。")
            return
        self.extract_log.append("开始提取水印…")
        self._start_worker(self._extract_worker, self.extract_log, src, pwd_img, pwd_wm, bits, mode)

    def _extract_worker(self, src, pwd_img, pwd_wm, bits, mode):
        bwm = WaterMark(password_wm=pwd_wm, password_img=pwd_img)
        if mode == "str":
            # 文字水印提取
            result = bwm.extract(filename=src, wm_shape=bits, mode="str")
            return f"提取到文字水印: {result}"
        elif mode == "bit":
            result = bwm.extract(filename=src, wm_shape=bits, mode="bit")
            return f"提取到位图水印: {result}"
        else:
            # 默认图片水印提取（返回图片文件路径）
            out_path = Path(src).with_name(Path(src).stem + "_extracted.png")
            bwm.extract(filename=src, out_wm_name=str(out_path))
            return f"提取到图片水印, 已保存至 {out_path}"

    # ---------------------------------------------------------------------
    # 批量嵌入实现（图片水印示例）
    # ---------------------------------------------------------------------
    def _run_batch(self):
        src_dir = self.batch_src_dir.text().strip()
        wm_path = self.batch_wm_img.text().strip()
        out_dir = self.batch_out_dir.text().strip()
        try:
            pwd_img = int(self.batch_pwd_img.text().strip())
            pwd_wm = int(self.batch_pwd_wm.text().strip())
        except ValueError:
            QMessageBox.warning(self, "参数错误", "密码必须为整数。")
            return
        if not all([src_dir, wm_path, out_dir]):
            QMessageBox.warning(self, "缺少参数", "请完整填写所有路径。")
            return
        self.batch_log.append("开始批量嵌入…")
        self._start_worker(self._batch_worker, self.batch_log, src_dir, wm_path, out_dir, pwd_img, pwd_wm)

    def _batch_worker(self, src_dir, wm_path, out_dir, pwd_img, pwd_wm):
        src_path = Path(src_dir)
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        images = list(src_path.glob("*.png")) + list(src_path.glob("*.jpg")) + list(src_path.glob("*.jpeg"))
        if not images:
            return "未在指定文件夹中找到图片文件。"
        for img_file in sorted(images):
            bwm = WaterMark(password_wm=pwd_wm, password_img=pwd_img)
            bwm.read_img(str(img_file))
            bwm.read_wm(wm_path)
            bits = len(bwm.wm_bit)
            ext = img_file.suffix
            # 命名模板：序号-password_img-password_wm-水印位数-扩展名
            # 序号自动递增，避免覆盖已有文件
            out_file = self._next_output_name(out_dir, pwd_img, pwd_wm, bits, ext)
            bwm.embed(str(out_file))
        return f"批量处理完成。已处理 {len(images)} 张图片。"

    # ---------------------------------------------------------------------
    # 退出时清理线程（防止异常退出）
    # ---------------------------------------------------------------------
    def closeEvent(self, event):
        # 若有正在运行的线程，尝试安全退出
        for thread in list(self._active_threads):
            try:
                thread.quit()
                thread.wait(3000)  # 最多等待 3 秒
            except Exception:
                pass
        self._active_threads.clear()
        event.accept()


def main():
    app = QApplication(sys.argv)

    # 全局兜底：未捕获异常以弹窗呈现，避免静默闪退
    def _excepthook(exc_type, exc, tb):
        txt = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            QMessageBox.critical(None, "程序错误", txt)
        except Exception:
            sys.stderr.write(txt)
    sys.excepthook = _excepthook

    # Fusion 风格 + 暗色调
    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(42, 42, 42))
    dark_palette.setColor(QPalette.AlternateBase, QColor(66, 66, 66))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(dark_palette)

    # 引擎（cv2/blind_watermark）在 QApplication 就绪后再初始化，失败能正常弹窗而不是无声闪退
    try:
        _init_engine()
    except Exception as e:
        try:
            Path("error.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        QMessageBox.critical(
            None,
            "引擎初始化失败",
            f"无法初始化水印引擎：\n\n{e}\n\n详细错误已写入 error.log",
        )
        sys.exit(2)

    win = WatermarkApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
