'''
 created by jim.qiu on 2025-07-17
'''
import sys
import os
import re
import time
import usb.core
import usb.util
import threading
import queue
import platform
import inspect
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit,
                             QGroupBox, QGridLayout, QMessageBox, QProgressBar, QListWidget,
                             QSplitter, QComboBox, QCheckBox, QFrame, QSizePolicy)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDir
from PyQt5.QtGui import QFont, QPalette, QColor

# 自定义UI组件
class RoundedButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(35)
        self.setStyleSheet(
            """
            QPushButton {
                background-color: #4a86e8;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 8px;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #3a76d8;
            }
            QPushButton:pressed {
                background-color: #2a66c8;
            }
            QPushButton:disabled {
                background-color: #aaaaaa;
                color: #888888;
            }
            """
        )

class SectionTitle(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("""
            font-weight: bold;
            font-size: 14px;
            color: #333333;
            padding: 5px 0px;
            background-color: #f0f0f0;
            border-radius: 4px;
        """)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(30)

class HighlightLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("""
            font-weight: bold;
            font-size: 13px;
            border: 1px solid #cccccc;
            border-radius: 6px;
            padding: 3px 8px;
            background-color: #f9f9f9;
        """)

class UsbTransferThread(QThread):
    update_progress = pyqtSignal(int)
    update_status = pyqtSignal(str)
    log_message = pyqtSignal(str)
    transfer_complete = pyqtSignal()
    error_occurred = pyqtSignal(str)
    data_received = pyqtSignal(bytes)

    def __init__(self, vid, pid, interface, ep_in, ep_out, file_path, packet_size=64,auto_read=False):
        super().__init__()
        self.vid = vid
        self.pid = pid
        self.interface = interface
        self.ep_in = ep_in
        self.ep_out = ep_out
        self.file_path = file_path
        self.packet_size = packet_size
        self.is_cancelled = False
        self.usb_device = None
        self.data_queue = queue.Queue()
        self.auto_read = auto_read

    def run(self):
        try:
            # 转换VID/PID为整数
            vid_int = int(self.vid, 16)
            pid_int = int(self.pid, 16)
            interface_num = int(self.interface)
            
            # 查找USB设备
            self.update_status.emit("正在连接USB设备...")
            self.log_message.emit(f"尝试连接设备: VID=0x{self.vid}, PID=0x{self.pid}, 接口={self.interface}, 输入端点={hex(self.ep_in)}, 输出端点={hex(self.ep_out)}")
            
            self.usb_device = usb.core.find(idVendor=vid_int, idProduct=pid_int)
            if self.usb_device is None:
                raise ValueError("未找到指定的USB设备")
            
            # 配置设备
            print(f"当前平台: {platform.system()}")
            if platform.system() == 'Windows':
                print('当前运行的系统是 Windows')
            else:
                print('当前运行的系统不是 Windows')

#            if self.usb_device.is_kernel_driver_active(interface_num):
#                self.usb_device.detach_kernel_driver(interface_num)
                
            configuration = self.usb_device.get_active_configuration()
            interface = configuration[(interface_num, 0)]
            
            # 获取端点
            ep_in = usb.util.find_descriptor(
                interface,
                custom_match=lambda e: \
                    usb.util.endpoint_direction(e.bEndpointAddress) == \
                    usb.util.ENDPOINT_IN and \
                    e.bEndpointAddress == self.ep_in
            )
            
            ep_out = usb.util.find_descriptor(
                interface,
                custom_match=lambda e: \
                    usb.util.endpoint_direction(e.bEndpointAddress) == \
                    usb.util.ENDPOINT_OUT and \
                    e.bEndpointAddress == self.ep_out
            )
            
            if ep_in is None or ep_out is None:
                raise ValueError("无法找到指定的端点")
            
            # 获取文件大小
            file_size = os.path.getsize(self.file_path)
            bytes_sent = 0
            
            self.update_status.emit(f"开始发送文件: {os.path.basename(self.file_path)}")
            self.log_message.emit(f"文件大小: {file_size} 字节 | 包大小: {self.packet_size} 字节")
            
            # 创建接收数据的线程
            if self.auto_read :
                self.log_message.emit("自动读取已启用，启动接收线程")
                receive_thread = threading.Thread(target=self.receive_data, args=(ep_in,))
                receive_thread.daemon = False  # 修改为非守护线程 True
                receive_thread.start()
            else:
                self.log_message.emit("自动读取未启用，接收线程不会启动")

            # 发送文件数据
            print(self.file_path)
            with open(self.file_path, 'rb') as file:
                while not self.is_cancelled:
                    chunk = file.read(self.packet_size)
                    if not chunk:
                        break
                    
                    # 发送数据到输出端点
                    #print(f"发送数据: {chunk.hex()}")
                    self.send_data(ep_out, chunk)
                    bytes_sent += len(chunk)
                    
                    # 更新进度
                    progress = int((bytes_sent / file_size) * 100)
                    self.update_progress.emit(progress)
                    
                    # 添加一点延迟以防止USB过载
                    time.sleep(0.01)
            
            if not self.is_cancelled:
                self.update_status.emit("文件发送完成!")
                self.log_message.emit(f"成功发送 {bytes_sent} 字节")
                self.transfer_complete.emit()
        
        except Exception as e:
            self.error_occurred.emit(f"传输错误: {str(e)}")
            self.log_message.emit(f"错误: {str(e)}")
        finally:
            # 清理资源
            self.is_cancelled = True
            #if self.usb_device:
                #usb.util.dispose_resources(self.usb_device)
    
    def send_data(self, ep_out, data):
        """发送数据到USB设备"""
        print(f"{inspect.currentframe().f_code.co_name},line={inspect.currentframe().f_lineno}")
        try:
            # 如果数据长度小于包大小，补齐
            if len(data) < self.packet_size:
                data += b'\x00' * (self.packet_size - len(data))
            
            #print(data)  # 调试输出数据内容
            self.log_message.emit(f"发送数据(16进制): {data.hex()}")
            # 发送数据
            ep_out.write(data)
            
        except usb.core.USBError as e:
            if e.errno != 110:  # 忽略超时错误
                raise
    
    def receive_data(self, ep_in):
        """在后台线程中持续接收USB数据"""
        print(f"{inspect.currentframe().f_code.co_name},line={inspect.currentframe().f_lineno}")
        try:
            while not self.is_cancelled:
                # 尝试从输入端点读取数据
                try:
                    data = ep_in.read(self.packet_size, timeout=100)
                    if data:
                        self.data_received.emit(bytes(data))
                except usb.core.USBError as e:
                    if e.errno != 110:  # 忽略超时错误
                        self.log_message.emit(f"读取错误: {str(e)}")
                time.sleep(0.01)
        except Exception as e:
            self.log_message.emit(f"接收线程错误: {str(e)}")
    
    def cancel(self):
        print(f"{inspect.currentframe().f_code.co_name}: line {inspect.currentframe().f_lineno}: ")
        self.is_cancelled = True
        self.update_status.emit("操作已取消")
        # 立即释放资源
        if self.usb_device:
            usb.util.dispose_resources(self.usb_device)


class UsbTransferApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("USB 文件传输工具 (带接口支持)")
        self.setGeometry(100, 50, 1000, 800)
        
        # 设置应用样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                border: 1px solid #cccccc;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit, QComboBox {
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 5px;
            }
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4a86e8;
                width: 10px;
            }
            QTextEdit {
                border: 1px solid #cccccc;
                border-radius: 4px;
                font-family: Consolas, Courier New;
                font-size: 12px;
            }
        """)
        
        # 初始化USB设备列表
        self.usb_devices = []
        self.selected_file = ""
        
        # 初始化UI
        self.init_ui()
        
        # USB传输线程
        self.transfer_thread = None

    def init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        
        # 创建分割器，使界面可调整
        splitter = QSplitter(Qt.Vertical)
        
        # ==== 上半部分：文件选择 ====
        file_frame = QFrame()
        file_frame.setFrameShape(QFrame.StyledPanel)
        file_layout = QVBoxLayout(file_frame)
        file_layout.setContentsMargins(10, 10, 10, 10)
        file_layout.setSpacing(10)
        
        # 标题
        file_layout.addWidget(SectionTitle("文件选择"))
        
        # 文件路径区域
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(QDir.homePath())
        self.path_edit.setPlaceholderText("选择目录路径")
        
        browse_btn = RoundedButton("浏览目录")
        browse_btn.clicked.connect(self.browse_directory)
        
        path_layout.addWidget(QLabel("目录路径:"), 1)
        path_layout.addWidget(self.path_edit, 5)
        path_layout.addWidget(browse_btn, 1)
        
        # 文件搜索区域
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入文件名关键字")
        
        search_btn = RoundedButton("搜索文件")
        search_btn.clicked.connect(self.search_files)
        
        search_layout.addWidget(QLabel("文件名过滤:"), 1)
        search_layout.addWidget(self.search_edit, 5)
        search_layout.addWidget(search_btn, 1)
        
        # 文件列表
        file_layout.addLayout(path_layout)
        file_layout.addLayout(search_layout)
        
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(180)
        self.file_list.itemClicked.connect(self.file_selected)
        file_layout.addWidget(self.file_list)
        
        # 显示选中的文件
        self.selected_file_label = HighlightLabel("未选择文件")
        file_layout.addWidget(self.selected_file_label)
        
        # ==== 下半部分：USB传输控制 ====
        usb_frame = QFrame()
        usb_frame.setFrameShape(QFrame.StyledPanel)
        usb_layout = QVBoxLayout(usb_frame)
        usb_layout.setContentsMargins(10, 10, 10, 10)
        usb_layout.setSpacing(10)
        
        # 标题
        usb_layout.addWidget(SectionTitle("USB传输控制"))
        
        # USB参数配置
        param_layout = QGridLayout()
        param_layout.setColumnStretch(0, 1)
        param_layout.setColumnStretch(1, 2)
        param_layout.setColumnStretch(2, 1)
        param_layout.setColumnStretch(3, 2)
        param_layout.setColumnStretch(4, 1)
        
        # VID/PID输入
        self.vid_input = QLineEdit("0483")
        self.pid_input = QLineEdit("8004")
        
        # 接口号
        self.interface_input = QComboBox()
        self.interface_input.setEditable(True)
        self.interface_input.addItems(["0", "1", "2", "3"])
        self.interface_input.setCurrentIndex(3)
        
        # 端点地址输入
        self.ep_in_input = QComboBox()
        self.ep_in_input.setEditable(True)
        self.ep_in_input.addItems(["0x81", "0x82", "0x83", "0x84", "0x85", "0x86", "0x87", "0x88", "0x89", "0x8A", "0x8B", "0x8C", "0x8D", "0x8E",])
        self.ep_in_input.setCurrentIndex(5)
        
        self.ep_out_input = QComboBox()
        self.ep_out_input.setEditable(True)
        self.ep_out_input.addItems(["0x01", "0x02", "0x03", "0x04", "0x05", "0x06", "0x07", "0x08", "0x09", "0x0A", "0x0B", "0x0C", "0x0D", "0x0E"])
        self.ep_out_input.setCurrentIndex(5)
        
        # 包大小设置
        self.packet_size = QComboBox()
        self.packet_size.addItems(["8", "16", "32", "64", "128", "256"])
        self.packet_size.setCurrentIndex(3)  # 默认64
        
        # 刷新设备按钮
        refresh_btn = RoundedButton("🔍 刷新USB设备")
        refresh_btn.clicked.connect(self.scan_usb_devices)
        
        # 第一行：VID/PID
        param_layout.addWidget(QLabel("VID (十六进制):"), 0, 0)
        param_layout.addWidget(self.vid_input, 0, 1)
        param_layout.addWidget(QLabel("PID (十六进制):"), 0, 2)
        param_layout.addWidget(self.pid_input, 0, 3)
        
        # 第二行：接口号
        param_layout.addWidget(QLabel("接口号:"), 1, 0)
        param_layout.addWidget(self.interface_input, 1, 1)
        
        # 第三行：端点
        param_layout.addWidget(QLabel("输入端点:"), 2, 0)
        param_layout.addWidget(self.ep_in_input, 2, 1)
        param_layout.addWidget(QLabel("输出端点:"), 2, 2)
        param_layout.addWidget(self.ep_out_input, 2, 3)
        
        # 第四行：包大小和刷新按钮
        param_layout.addWidget(QLabel("包大小:"), 3, 0)
        param_layout.addWidget(self.packet_size, 3, 1)
        param_layout.addWidget(refresh_btn, 3, 2, 1, 2)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        self.send_btn = RoundedButton("🚀 发送文件")
        self.send_btn.clicked.connect(self.start_transfer)
        self.cancel_btn = RoundedButton("❌ 取消传输")
        self.cancel_btn.clicked.connect(self.cancel_transfer)
        self.cancel_btn.setEnabled(False)
        self.clear_log_btn = RoundedButton("🧹 清除日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        
        btn_layout.addWidget(self.send_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.clear_log_btn)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        
        # 状态标签
        self.status_label = QLabel("准备就绪")
        self.status_label.setStyleSheet("font-weight: bold; padding: 5px;")
        
        # 日志区域
        usb_layout.addLayout(param_layout)
        usb_layout.addWidget(self.progress_bar)
        usb_layout.addLayout(btn_layout)
        usb_layout.addWidget(self.status_label)
        
        # 日志标题
        log_title_layout = QHBoxLayout()
        log_title_layout.addWidget(SectionTitle("通信日志"))
        self.show_hex = QCheckBox("显示十六进制")
        self.show_hex.setChecked(True)
        self.auto_read = QCheckBox("发送后自动读取")  # 新增复选框
        self.auto_read.setChecked(True)
        log_title_layout.addStretch()
        log_title_layout.addWidget(self.show_hex)
        log_title_layout.addWidget(self.auto_read)    # 添加到布局
        usb_layout.addLayout(log_title_layout)
        
        # 日志视图
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier", 10))
        self.log_view.setMinimumHeight(180)
        usb_layout.addWidget(self.log_view)
        
        # 添加组件到分割器
        splitter.addWidget(file_frame)
        splitter.addWidget(usb_frame)
        splitter.setSizes([300, 500])
        
        main_layout.addWidget(splitter)
        self.setCentralWidget(main_widget)
        
        # 初始扫描USB设备
        self.scan_usb_devices()
    
    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "选择目录", self.path_edit.text())
        if directory:
            self.path_edit.setText(directory)
    
    def search_files(self):
        directory = self.path_edit.text()
        keyword = self.search_edit.text().strip().lower()
        
        if not directory:
            QMessageBox.warning(self, "错误", "请先选择目录")
            return
            
        if not os.path.isdir(directory):
            QMessageBox.warning(self, "错误", "目录路径无效")
            return
        
        self.file_list.clear()
        self.selected_file = ""
        self.selected_file_label.setText("未选择文件")
        
        try:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if keyword in file.lower():
                        full_path = os.path.join(root, file)
                        relative_path = os.path.relpath(full_path, directory)
                        self.file_list.addItem(relative_path)
            
            if self.file_list.count() == 0:
                self.log_message(f"在目录 '{directory}' 中未找到包含 '{keyword}' 的文件")
            else:
                self.log_message(f"找到 {self.file_list.count()} 个包含 '{keyword}' 的文件")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"搜索文件时出错: {str(e)}")
    
    def file_selected(self, item):
        directory = self.path_edit.text()
        relative_path = item.text()
        full_path = os.path.join(directory, relative_path)
        
        if os.path.isfile(full_path):
            self.selected_file = full_path
            file_size = os.path.getsize(full_path)
            size_kb = file_size / 1024.0
            self.selected_file_label.setText(f"已选择: {relative_path} ({size_kb:.2f} KB)")
            self.log_message(f"已选择文件: {relative_path}")
        else:
            self.selected_file = ""
            self.selected_file_label.setText("文件无效或不存在")
    
    def scan_usb_devices(self):
        """扫描并显示连接的USB设备"""
        try:
            self.usb_devices = list(usb.core.find(find_all=True))
            count = len(self.usb_devices)
            self.log_message(f"发现 {count} 个USB设备")
            
            for dev in self.usb_devices:
                self.log_message(f"设备: VID=0x{dev.idVendor:04x} PID=0x{dev.idProduct:04x}")
                
                # 显示设备配置信息
                try:
                    for cfg in dev:
                        self.log_message(f"  配置: {cfg.bConfigurationValue}")
                        for intf in cfg:
                            self.log_message(f"    接口: {intf.bInterfaceNumber}")
                            for ep in intf:
                                ep_type = "控制" if usb.util.endpoint_type(ep.bmAttributes) == usb.ENDPOINT_TYPE_CONTROL else \
                                          "中断" if usb.util.endpoint_type(ep.bmAttributes) == usb.ENDPOINT_TYPE_INTERRUPT else \
                                          "批量" if usb.util.endpoint_type(ep.bmAttributes) == usb.ENDPOINT_TYPE_BULK else \
                                          "等时"
                                direction = "IN" if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.ENDPOINT_IN else "OUT"
                                self.log_message(f"      端点: 0x{ep.bEndpointAddress:02x} ({direction}, {ep_type})")
                except usb.core.USBError as e:
                    self.log_message(f"  无法获取配置信息: {str(e)}")
        
        except Exception as e:
            self.log_message(f"扫描USB设备错误: {str(e)}")
    
    def log_message(self, message):
        """添加带时间戳的消息到日志"""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self.log_view.append(f"[{timestamp}] {message}")
        
        # 滚动到底部
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_log(self):
        self.log_view.clear()
    
    def start_transfer(self):
        if not self.selected_file or not os.path.isfile(self.selected_file):
            QMessageBox.warning(self, "错误", "请先选择一个有效文件")
            return
        
        # 获取USB参数
        vid = self.vid_input.text().strip()
        pid = self.pid_input.text().strip()
        interface = self.interface_input.currentText().strip()
        ep_in_text = self.ep_in_input.currentText().strip()
        ep_out_text = self.ep_out_input.currentText().strip()
        packet_size = int(self.packet_size.currentText())
        
        # 验证参数
        if not all([vid, pid, interface, ep_in_text, ep_out_text]):
            QMessageBox.warning(self, "错误", "请填写所有USB参数")
            return
        
        try:
            # 转换端点地址为整数
            ep_in = int(ep_in_text, 16)
            ep_out = int(ep_out_text, 16)
        except ValueError:
            QMessageBox.warning(self, "错误", "端点地址格式无效，请使用十六进制格式 (如0x81)")
            return
        
        # 禁用UI控件
        self.send_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setStyleSheet("font-weight: bold; color: #d35400;")
        self.status_label.setText("正在准备传输...")
        
        # 创建并启动传输线程
        self.transfer_thread = UsbTransferThread(
            vid, 
            pid, 
            interface,
            ep_in, 
            ep_out, 
            self.selected_file,
            packet_size,
            self.auto_read.isChecked()
        )
        self.transfer_thread.update_progress.connect(self.progress_bar.setValue)
        self.transfer_thread.update_status.connect(self.status_label.setText)
        self.transfer_thread.log_message.connect(self.log_message)
        self.transfer_thread.error_occurred.connect(self.handle_error)
        self.transfer_thread.transfer_complete.connect(self.transfer_completed)
        self.transfer_thread.data_received.connect(self.handle_received_data)
        self.transfer_thread.start()
    
    def cancel_transfer(self):
        if self.transfer_thread and self.transfer_thread.isRunning():
            self.transfer_thread.cancel()
            self.status_label.setText("正在取消操作...")
    
    def transfer_completed(self):
        self.send_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setStyleSheet("font-weight: bold; color: #27ae60;")
        self.status_label.setText("传输完成!")
    
    def handle_error(self, message):
        self.send_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setStyleSheet("font-weight: bold; color: #c0392b;")
        self.status_label.setText("传输错误")
        QMessageBox.critical(self, "错误", message)
    
    def handle_received_data(self, data):
        """处理收到的USB数据"""
        if self.show_hex.isChecked():
            # 十六进制格式显示
            hex_data = ' '.join(f'{b:02X}' for b in data)
            self.log_message(f"收到数据(16进制): {hex_data}")
            ascii_data = ''.join([chr(byte) if 32 <= byte <= 126 else '.' for byte in data])
            self.log_message(f"收到数据(ASCII): {ascii_data}")
        else:
            # 尝试解码为文本
            try:
                text = data.decode('utf-8', errors='replace').strip()
                self.log_message(f"收到文本: {text}")
            except:
                # 如果解码失败，显示十六进制
                hex_data = ' '.join(f'{b:02X}' for b in data)
                self.log_message(f"出现异常，收到数据: {hex_data}")

    def closeEvent(self, event):
        """窗口关闭时确保停止传输线程"""
        if self.transfer_thread and self.transfer_thread.isRunning():
            self.transfer_thread.cancel()
            self.transfer_thread.wait(2000)  # 等待2秒让线程结束
        event.accept()


if __name__ == "__main__":
    print(f"__name__ is {__name__},sys.argv is {sys.argv}")
    app = QApplication(sys.argv)
    
    # 检查pyusb是否可用
    try:
        usb.core.find()
    except:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("USB库错误")
        msg.setText("无法访问USB设备。请确保：")
        msg.setInformativeText(
            "1. 已安装pyusb (pip install pyusb)\n"
            "2. 在Linux上可能需要设置USB权限\n"
            "3. 在Windows上可能需要安装libusb驱动"
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
        sys.exit(1)
    
    window = UsbTransferApp()
    window.show()
    sys.exit(app.exec_())