#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESP32 系统监视器 - GUI 版（低资源占用修复版）
关键修复：
1. 固定时钟调度，杜绝忙循环
2. NVML 会话保持，不反复 init/shutdown
3. 非 NVIDIA 显卡默认不读占用率（避免 WMI 全表扫描）
4. CPU 温度失败后自动退避，不再高频重试
5. Tk 变量跨线程访问改为线程安全镜像
6. 内置性能日志，出问题可溯源
"""

import sys
import os
import json
import math
import time
import platform
import subprocess
import threading
import traceback

# ============================================================
#  隐藏控制台
# ============================================================
if platform.system() == 'Windows':
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

# ============================================================
#  路径 & 日志
# ============================================================
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
LOG_PATH       = os.path.join(BASE_DIR, 'monitor.log')
SETTINGS_PATH  = os.path.join(BASE_DIR, 'settings.json')


def log(msg):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


try:
    open(LOG_PATH, 'w').close()
except Exception:
    pass
log("=== 启动 ===")

DEFAULT_SETTINGS = {
    'port':         '',
    'rate':         10,
    'theme_mode':   'auto',
    'reverse_rb':   True,
    'show_gpu':     True,
    'auto_connect': True,
    'colors':       None,
}


def load_settings():
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        result = dict(DEFAULT_SETTINGS)
        result.update(data)
        return result
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(data):
    try:
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log(f"保存设置失败: {e}")


# ============================================================
#  性能统计（每 30 秒输出一次到日志）
# ============================================================
_perf_data = {}
_perf_lock = threading.Lock()


def perf_record(name, elapsed):
    with _perf_lock:
        s = _perf_data.setdefault(name, {'n': 0, 'sum': 0.0, 'max': 0.0})
        s['n'] += 1
        s['sum'] += elapsed
        s['max'] = max(s['max'], elapsed)


def perf_dump():
    with _perf_lock:
        if not _perf_data:
            return
        for name, s in _perf_data.items():
            avg_ms = s['sum'] / s['n'] * 1000
            max_ms = s['max'] * 1000
            log(f"[PERF] {name:14s} n={s['n']:6d} avg={avg_ms:7.2f}ms max={max_ms:7.2f}ms")
        _perf_data.clear()


# ============================================================
#  线程安全镜像变量
# ============================================================
class SharedState:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}

    def set(self, k, v):
        with self._lock:
            self._data[k] = v

    def get(self, k, default=None):
        with self._lock:
            return self._data.get(k, default)


SHARED = SharedState()


# ============================================================
#  依赖安装
# ============================================================
def ensure_deps():
    deps = [
        ('serial', 'pyserial'),
        ('psutil', 'psutil'),
    ]
    if platform.system() == 'Windows':
        deps.append(('wmi', 'WMI'))
    optional = [
        ('pynvml', 'nvidia-ml-py'),
    ]
    for mod, pkg in deps:
        try:
            __import__(mod)
        except ImportError:
            log(f"安装 {pkg} ...")
            try:
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])
            except Exception as e:
                log(f"安装失败 {pkg}: {e}")
    for mod, pkg in optional:
        try:
            __import__(mod)
        except ImportError:
            log(f"安装可选 {pkg} ...")
            try:
                subprocess.check_call(
                    [sys.executable, '-m', 'pip', 'install', pkg],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                log(f"跳过 {pkg}")


ensure_deps()

import serial
import serial.tools.list_ports
import psutil

try:
    import pynvml
    HAS_PYNVML = True
except ImportError:
    HAS_PYNVML = False

import tkinter as tk
from tkinter import ttk, colorchooser, messagebox


# ============================================================
#  工具
# ============================================================
def swap_rb(hex_color):
    if not hex_color or not hex_color.startswith('#'):
        return hex_color
    h = hex_color.lstrip('#')
    if len(h) != 6:
        return hex_color
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"#{b}{g}{r}"


def safe_float(v, default=0.0):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


# ============================================================
#  主题
# ============================================================
LIGHT = {
    'bg':     '#FFFFFF', 'text':   '#202020', 'dim':    '#909090',
    'grid':   '#E8E8E8', 'border': '#D0D0D0',
    'cpu':    '#1F77B4', 'mem':    '#2CA02C',
    'gpu':    '#FF7F0E', 'temp':   '#D62728',
}
DARK = {
    'bg':     '#1E1E1E', 'text':   '#FFFFFF', 'dim':    '#A0A0A0',
    'grid':   '#333333', 'border': '#444444',
    'cpu':    '#4FC3F7', 'mem':    '#66BB6A',
    'gpu':    '#FFA726', 'temp':   '#EF5350',
}


def get_system_theme():
    if platform.system() == 'Windows':
        try:
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
            v, _ = winreg.QueryValueEx(k, 'AppsUseLightTheme')
            winreg.CloseKey(k)
            return 'light' if v else 'dark'
        except Exception:
            pass
    return 'light'


# ============================================================
#  CPU 名称缓存
# ============================================================
_cpu_name_cache = None


def get_cpu_name_cached():
    global _cpu_name_cache
    if _cpu_name_cache is not None:
        return _cpu_name_cache

    name = None
    if platform.system() == 'Windows':
        try:
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'HARDWARE\DESCRIPTION\System\CentralProcessor\0')
            n, _ = winreg.QueryValueEx(k, 'ProcessorNameString')
            winreg.CloseKey(k)
            name = n.strip()
        except Exception:
            pass
    elif platform.system() == 'Linux':
        try:
            with open('/proc/cpuinfo') as f:
                for line in f:
                    if 'model name' in line:
                        name = line.split(':', 1)[1].strip()
                        break
        except Exception:
            pass

    if not name:
        name = platform.processor() or 'Unknown CPU'
    _cpu_name_cache = name
    log(f"CPU 名称: {name}")
    return name


# ============================================================
#  物理内存
# ============================================================
def get_phys_mem_percent():
    return round(psutil.virtual_memory().percent, 1)


# ============================================================
#  CPU 温度读取（自动退避）
# ============================================================
class TempReader:
    def __init__(self):
        self._disabled = False
        self._fail_count = 0
        self._last = None
        self._wmi_ok = None      # None=未检测, True/False
        self._os = platform.system()

    def read(self):
        """读取 CPU 温度，返回 float 或 None"""
        if self._disabled:
            return self._last

        t0 = time.time()
        try:
            val = self._read_raw()
        except Exception:
            val = None
        perf_record('temp_read', time.time() - t0)

        if val is None:
            self._fail_count += 1
            if self._fail_count >= 3:
                self._disabled = True
                log("CPU 温度不可用，已禁用（避免持续占用资源）")
        else:
            self._fail_count = 0
            self._last = val
        return val

    def _read_raw(self):
        if self._os == 'Linux':
            try:
                temps = psutil.sensors_temperatures()
                for name in ('coretemp', 'k10temp', 'zenpower',
                             'cpu_thermal', 'acpitz'):
                    if name in temps and temps[name]:
                        return round(float(temps[name][0].current), 1)
            except Exception:
                pass
            return None

        if self._os == 'Windows':
            # 只在首次尝试 WMI，之后根据结果缓存
            if self._wmi_ok is False:
                return None
            try:
                import wmi
            except ImportError:
                self._wmi_ok = False
                return None

            # LHM
            try:
                w = wmi.WMI(namespace='root\\LibreHardwareMonitor')
                sensors = w.Sensor()
                for s in sensors:
                    if s.SensorType == 'Temperature' and \
                       'CPU Package' in (s.Name or ''):
                        self._wmi_ok = True
                        return round(float(s.Value), 1)
                for s in sensors:
                    if s.SensorType == 'Temperature' and \
                       'CPU' in (s.Name or ''):
                        self._wmi_ok = True
                        return round(float(s.Value), 1)
            except Exception:
                pass

            # OHM
            try:
                w = wmi.WMI(namespace='root\\OpenHardwareMonitor')
                sensors = w.Sensor()
                for s in sensors:
                    if s.SensorType == 'Temperature' and \
                       'CPU Package' in (s.Name or ''):
                        self._wmi_ok = True
                        return round(float(s.Value), 1)
            except Exception:
                pass

            self._wmi_ok = False
            return None

        return None


# ============================================================
#  GPU 读取器
# ============================================================
class GPUReader:
    """
    一次枚举显卡；NVIDIA 走 pynvml 会话保持；其他只读名称。
    避免 WMI 性能计数器全表扫描。
    """

    def __init__(self):
        self._name = ''
        self._vendor = 'unknown'
        self._ok = False
        self._usage = 0.0
        self._nvml_handle = None
        self._nvml_ok = False

    def init_once(self):
        """枚举显卡（只调一次）"""
        if platform.system() != 'Windows':
            # 非 Windows 不做 GPU 检测
            return False

        try:
            import wmi
            w = wmi.WMI()
            gpus = []
            for vc in w.Win32_VideoController():
                name = (vc.Name or '').strip()
                if not name:
                    continue
                lower = name.lower()
                if any(kw in lower for kw in
                       ('microsoft basic display', 'remote display',
                        'virtual display', 'idriver', 'meta virtual')):
                    continue
                gpus.append({
                    'name':   name,
                    'compat': (vc.AdapterCompatibility or '').strip(),
                })
        except Exception as e:
            log(f"GPU 枚举失败: {e}")
            return False

        if not gpus:
            log("未检测到 GPU")
            return False

        # 优先级：NVIDIA > AMD > Intel
        def priority(g):
            v = self._detect_vendor(g['name'], g['compat'])
            return {'nvidia': 0, 'amd': 1, 'intel': 2}.get(v, 3)

        g = sorted(gpus, key=priority)[0]
        self._vendor = self._detect_vendor(g['name'], g['compat'])
        self._name = g['name'][:40]
        self._ok = True
        log(f"GPU: {self._name} ({self._vendor})")

        # NVIDIA: 一次性初始化 NVML
        if self._vendor == 'nvidia' and HAS_PYNVML:
            try:
                pynvml.nvmlInit()
                self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self._nvml_ok = True
                log("NVML 会话已建立")
            except Exception as e:
                log(f"NVML 初始化失败: {e}")
                self._nvml_ok = False

        return True

    @staticmethod
    def _detect_vendor(name, compat):
        text = f"{name} {compat}".lower()
        if any(k in text for k in ('nvidia', 'geforce', 'quadro', 'rtx', 'gtx')):
            return 'nvidia'
        if any(k in text for k in ('amd', 'radeon', 'ati ')):
            return 'amd'
        if 'intel' in text:
            return 'intel'
        return 'unknown'

    def read_usage(self):
        """
        NVIDIA: pynvml 会话保持，每次只调一个极快的 API
        其他:   返回 0.0（不启用慢查询）
        """
        if not self._ok:
            return 0.0

        if self._vendor == 'nvidia' and self._nvml_ok:
            try:
                t0 = time.time()
                util = pynvml.nvmlDeviceGetUtilizationRates(self._nvml_handle)
                perf_record('gpu_nvml', time.time() - t0)
                self._usage = round(float(util.gpu), 1)
                return self._usage
            except Exception as e:
                log(f"NVML 读取失败: {e}")
                self._nvml_ok = False
                return 0.0

        return 0.0

    def info(self):
        return self._name, self._usage, self._ok

    def shutdown(self):
        if self._nvml_ok:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml_ok = False


# ============================================================
#  后台周期任务调度（固定时钟，杜绝忙循环）
# ============================================================
def periodic_worker(name, interval_getter, work_fn, stop_flag):
    """
    固定时钟调度：
    - 每次任务结束后，next_tick 直接 += interval
    - 如果任务超时，立即进入下一轮，但不会出现"急速空转"
    - 使用 stop_flag（threading.Event）优雅退出
    """
    next_tick = time.time() + interval_getter()
    while not stop_flag.is_set():
        now = time.time()
        if now < next_tick:
            # 分段 sleep，便于及时响应退出
            time.sleep(min(next_tick - now, 0.5))
            continue

        t0 = time.time()
        try:
            work_fn()
        except Exception as e:
            log(f"[{name}] 任务异常: {e}")
        elapsed = time.time() - t0
        perf_record(name, elapsed)

        # 计算下一轮时间
        interval = interval_getter()
        next_tick += interval
        # 如果任务已经超过 2 个周期，重置基准，避免"追帧"
        if time.time() - next_tick > interval:
            next_tick = time.time() + interval


# ============================================================
#  数据采集（主循环调用，只读缓存）
# ============================================================
_gpu_reader = None       # 全局
_temp_reader = None      # 全局
_stop_flag = threading.Event()


def collect_data(show_gpu=True):
    cpu  = round(safe_float(psutil.cpu_percent(interval=None)), 1)
    mem  = get_phys_mem_percent()
    temp = _temp_reader.read() if _temp_reader else None

    if show_gpu and _gpu_reader and _gpu_reader._ok:
        gname, guse, gok = _gpu_reader.info()
    else:
        gname, guse, gok = '', 0.0, False

    return {
        'cpu':      cpu,
        'mem':      mem,
        'gpu':      guse if gok else 0.0,
        'cpu_temp': temp if temp is not None else 0.0,
        'has_temp': temp is not None,
        'cpu_name': get_cpu_name_cached(),
        'gpu_name': gname,
        'gpu_ok':   gok,
    }


# ============================================================
#  串口查找
# ============================================================
ESP32_KEYWORDS = ('cp210', 'ch340', 'ch910', 'esp32',
                  'jtag', 'wch', 'silicon labs', 'usb serial')


def find_esp32_port():
    try:
        for p in serial.tools.list_ports.comports():
            text = f"{p.description or ''} {p.hwid or ''}".lower()
            if any(k in text for k in ESP32_KEYWORDS):
                return p.device
    except Exception:
        pass
    return None


# ============================================================
#  GUI
# ============================================================
class App:
    def __init__(self, root):
        global _gpu_reader, _temp_reader

        self.root = root
        self.ser = None
        self.ser_lock = threading.Lock()
        self.running = False
        self._connecting = False
        self.thread = None
        self._rate = 10
        self._latest = None
        self._last_port = None
        self._tx_count = 0

        self.settings = load_settings()

        self.theme_mode   = tk.StringVar(value=self.settings['theme_mode'])
        self.rate_hz      = tk.IntVar(value=self.settings['rate'])
        self.port_var     = tk.StringVar(value=self.settings['port'])
        self.swap_rb      = tk.BooleanVar(value=self.settings['reverse_rb'])
        self.show_gpu     = tk.BooleanVar(value=self.settings['show_gpu'])
        self.auto_connect = tk.BooleanVar(value=self.settings['auto_connect'])

        self.custom_colors = self.settings.get('colors')
        self._rate = self.settings['rate']
        self.colors = dict(LIGHT)

        # 同步到线程安全镜像
        SHARED.set('show_gpu',     self.settings['show_gpu'])
        SHARED.set('auto_connect', self.settings['auto_connect'])
        SHARED.set('rate',         self._rate)

        # 初始化读取器
        _gpu_reader = GPUReader()
        _temp_reader = TempReader()

        self.build_ui()
        self.refresh_ports()
        self.apply_theme(initial=True)

        # 后台启动 GPU 和温度读取
        threading.Thread(target=self._gpu_worker, daemon=True).start()
        threading.Thread(target=self._temp_worker, daemon=True).start()
        threading.Thread(target=self._perf_dump_worker, daemon=True).start()

        if self.auto_connect.get():
            self.root.after(500, self.auto_connect_once)

        threading.Thread(target=self._device_scan_loop, daemon=True).start()

        self.root.after(500, self.poll_status)
        self.root.after(5000, self.check_system_theme)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- 后台 worker ----------
    def _gpu_worker(self):
        """先枚举一次显卡，然后周期读取占用率"""
        # 枚举可能慢，放后台
        t0 = time.time()
        ok = _gpu_reader.init_once()
        log(f"GPU 枚举耗时 {time.time()-t0:.2f}s ok={ok}")

        def interval():
            # NVIDIA: 1 秒；其他: 5 秒（虽然不读，但保持一致）
            if _gpu_reader._vendor == 'nvidia':
                return 1.0
            return 5.0

        def work():
            _gpu_reader.read_usage()

        periodic_worker('gpu_worker', interval, work, _stop_flag)

    def _temp_worker(self):
        def interval():
            # 禁用后不再周期调用
            if _temp_reader._disabled:
                return 60.0
            return 3.0

        def work():
            _temp_reader.read()

        periodic_worker('temp_worker', interval, work, _stop_flag)

    def _perf_dump_worker(self):
        while not _stop_flag.wait(30.0):
            perf_dump()

    # ---------- UI ----------
    def build_ui(self):
        self.root.title('ESP32 系统监视器')
        self.root.geometry('420x780')
        self.root.resizable(False, False)

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill='both', expand=True)

        sf = ttk.LabelFrame(main, text='串口', padding=6)
        sf.pack(fill='x')
        row = ttk.Frame(sf)
        row.pack(fill='x')
        ttk.Label(row, text='端口:').pack(side='left')
        self.port_cb = ttk.Combobox(row, textvariable=self.port_var, width=20)
        self.port_cb.pack(side='left', padx=4)
        ttk.Button(row, text='刷新', width=6,
                   command=self.refresh_ports).pack(side='left')

        ttk.Checkbutton(sf, text='启动时 / 设备插入时自动连接',
                        variable=self.auto_connect,
                        command=self.on_auto_connect_change
                        ).pack(anchor='w', pady=(4, 0))

        self.conn_btn = ttk.Button(main, text='连接并开始',
                                    command=self.toggle_connection)
        self.conn_btn.pack(fill='x', pady=6)

        self.status_var = tk.StringVar(value='未连接')
        ttk.Label(main, textvariable=self.status_var).pack(anchor='w')

        rf = ttk.LabelFrame(main, text='刷新率', padding=6)
        rf.pack(fill='x', pady=6)
        self.rate_scale = ttk.Scale(rf, from_=1, to=30,
                                     variable=self.rate_hz,
                                     orient='horizontal',
                                     command=self.on_rate_change)
        self.rate_scale.pack(fill='x')
        self.rate_label = ttk.Label(rf, text=f'{self._rate} Hz')
        self.rate_label.pack(anchor='e')

        tf = ttk.LabelFrame(main, text='主题', padding=6)
        tf.pack(fill='x', pady=6)
        for text, val in [('跟随系统', 'auto'),
                          ('浅色', 'light'),
                          ('深色', 'dark')]:
            ttk.Radiobutton(tf, text=text, value=val,
                            variable=self.theme_mode,
                            command=self.on_theme_change).pack(anchor='w')

        of = ttk.LabelFrame(main, text='显示选项', padding=6)
        of.pack(fill='x', pady=6)
        ttk.Checkbutton(of, text='显示 GPU 图表',
                        variable=self.show_gpu,
                        command=self.on_show_gpu_change).pack(anchor='w')
        ttk.Checkbutton(of, text='红蓝反转（屏幕颜色看起来反了时勾选）',
                        variable=self.swap_rb,
                        command=self.send_config).pack(anchor='w')

        cf = ttk.LabelFrame(main, text='颜色（点击方块更改）', padding=6)
        cf.pack(fill='x', pady=6)
        self.color_btns = {}
        for key, label in [
            ('bg',   '背景'), ('text', '文字'), ('dim',  '次要文字'),
            ('cpu',  'CPU'),  ('mem',  '内存'), ('gpu',  '显卡'),
            ('temp', '温度'),
        ]:
            row = ttk.Frame(cf)
            row.pack(fill='x', pady=1)
            ttk.Label(row, text=label, width=10).pack(side='left')
            btn = tk.Button(row, width=4, relief='solid', bd=1,
                            bg=self.colors[key],
                            command=lambda k=key: self.pick_color(k))
            btn.pack(side='right')
            self.color_btns[key] = btn

        btnrow = ttk.Frame(main)
        btnrow.pack(fill='x', pady=(6, 0))
        ttk.Button(btnrow, text='恢复默认设置',
                   command=self.reset_all_settings
                   ).pack(side='left', expand=True, fill='x', padx=(0, 3))
        ttk.Button(btnrow, text='仅重置颜色',
                   command=self.reset_colors
                   ).pack(side='left', expand=True, fill='x', padx=(3, 0))

    # ---------- 设置 ----------
    def save_current_settings(self):
        self.settings = {
            'port':         self.port_var.get(),
            'rate':         self._rate,
            'theme_mode':   self.theme_mode.get(),
            'reverse_rb':   self.swap_rb.get(),
            'show_gpu':     self.show_gpu.get(),
            'auto_connect': self.auto_connect.get(),
            'colors':       self.custom_colors if self.custom_colors else None,
        }
        save_settings(self.settings)

    def reset_all_settings(self):
        if not messagebox.askyesno('确认', '恢复全部默认设置？'):
            return
        try:
            if os.path.exists(SETTINGS_PATH):
                os.remove(SETTINGS_PATH)
        except Exception:
            pass
        self.custom_colors = None

        self.theme_mode.set('auto')
        self.rate_hz.set(10)
        self._rate = 10
        self.rate_label.config(text='10 Hz')
        self.swap_rb.set(True)
        self.show_gpu.set(True)
        self.auto_connect.set(True)

        SHARED.set('show_gpu', True)
        SHARED.set('auto_connect', True)
        SHARED.set('rate', 10)

        self.apply_theme(initial=True)
        self.send_config()
        self.save_current_settings()
        log("恢复默认设置")

    def on_auto_connect_change(self):
        SHARED.set('auto_connect', self.auto_connect.get())
        self.save_current_settings()

    def on_show_gpu_change(self):
        SHARED.set('show_gpu', self.show_gpu.get())
        self.save_current_settings()

    # ---------- 颜色 ----------
    def pick_color(self, key):
        c = colorchooser.askcolor(color=self.colors[key], title='选择颜色')
        if c and c[1]:
            self.colors[key] = c[1]
            self.custom_colors = dict(self.colors)
            self.update_color_buttons()
            self.send_config()
            self.save_current_settings()

    def reset_colors(self):
        self.custom_colors = None
        self.apply_theme()

    def update_color_buttons(self):
        for key, btn in self.color_btns.items():
            try:
                btn.config(bg=self.colors[key])
            except Exception:
                pass

    def apply_theme(self, initial=False):
        mode = self.theme_mode.get()
        theme = get_system_theme() if mode == 'auto' else mode
        base = DARK if theme == 'dark' else LIGHT
        if self.custom_colors:
            self.colors = dict(base)
            for k, v in self.custom_colors.items():
                if k in self.colors:
                    self.colors[k] = v
        else:
            self.colors = dict(base)
        self.update_color_buttons()
        if not initial:
            self.send_config()

    def on_theme_change(self):
        self.custom_colors = None
        self.apply_theme()
        self.save_current_settings()

    def check_system_theme(self):
        if self.theme_mode.get() == 'auto':
            old = dict(self.colors)
            self.apply_theme(initial=True)
            if old != self.colors:
                self.send_config()
        self.root.after(5000, self.check_system_theme)

    # ---------- 自动连接 ----------
    def auto_connect_once(self):
        if self.running:
            return
        port = find_esp32_port()
        if port:
            self.port_var.set(port)
            self.start()
        else:
            log("未找到 ESP32，等待设备插入")

    def _device_scan_loop(self):
        # 使用固定时钟，10 秒一次，不忙循环
        def work():
            if not SHARED.get('auto_connect', True):
                return
            if self.running or self._connecting:
                return
            port = find_esp32_port()
            if port and port != self._last_port:
                self._last_port = port
                self.root.after(0, lambda p=port: self._auto_connect(p))

        periodic_worker('device_scan', lambda: 10.0, work, _stop_flag)

    def _auto_connect(self, port):
        if self.running or self._connecting:
            return
        self.port_var.set(port)
        self.status_var.set(f'检测到 {port}，自动连接...')
        self.start()

    # ---------- 串口 ----------
    def refresh_ports(self):
        try:
            ports = list(serial.tools.list_ports.comports())
        except Exception:
            return
        devices = [p.device for p in ports]
        self.port_cb['values'] = devices
        if not devices:
            self.port_var.set('')
            return
        if self.port_var.get() in devices:
            return
        best = None
        for p in ports:
            text = f"{p.description or ''} {p.hwid or ''}".lower()
            if any(k in text for k in ESP32_KEYWORDS):
                best = p.device
                break
        self.port_var.set(best or devices[0])

    def toggle_connection(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        port = self.port_var.get()
        if not port:
            messagebox.showerror('错误', '请先选择串口')
            return
        try:
            self.ser = serial.Serial(port, 115200,
                                     timeout=0.3, write_timeout=2.0)
        except Exception as e:
            log(f"打开串口失败: {e}")
            messagebox.showerror('错误', f'无法打开串口:\n{e}')
            return

        log(f"串口已打开: {port}")
        self._connecting = True
        self.status_var.set(f'已连接 {port}，握手...')
        self.save_current_settings()
        threading.Thread(target=self._post_connect, daemon=True).start()

    def _post_connect(self):
        got_hello = False
        deadline = time.time() + 5.0
        while time.time() < deadline and self._connecting:
            try:
                self.ser.write(b'{"ping":1}\n')
            except Exception:
                pass
            try:
                line = self.ser.readline()
                if line:
                    text = line.decode('utf-8', errors='ignore').strip()
                    if 'hello' in text and 'esp32' in text:
                        got_hello = True
                        log(f"握手成功: {text}")
                        break
            except Exception:
                pass

        if not got_hello:
            log("握手超时，继续尝试发送")

        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception:
            pass

        self._connecting = False
        self.running = True
        self.send_config()

        self.root.after(0, lambda: self.conn_btn.config(text='停止'))
        log("开始发送数据")

        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self._connecting = False
        with self.ser_lock:
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
        self.conn_btn.config(text='连接并开始')
        self.status_var.set('未连接')
        log("已停止")

    def send_config(self):
        with self.ser_lock:
            if not self.ser:
                return
            cfg = {'cfg': 1}
            do_swap = self.swap_rb.get()
            for key, color in self.colors.items():
                cfg[key] = swap_rb(color) if do_swap else color
            try:
                line = json.dumps(cfg) + '\n'
                self.ser.write(line.encode('utf-8'))
                log("cfg 已发送")
            except Exception as e:
                log(f"配置发送失败: {e}")

    # ---------- 主发送循环（精确时钟） ----------
    def loop(self):
        psutil.cpu_percent(interval=None)
        fail_count = 0
        next_tick = time.time()

        while self.running:
            interval = 1.0 / max(1, SHARED.get('rate', self._rate))
            next_tick += interval
            now = time.time()
            if now < next_tick:
                time.sleep(next_tick - now)
            else:
                # 落后了，重置基准，不追帧
                next_tick = now

            t0 = time.time()
            try:
                data = collect_data(show_gpu=SHARED.get('show_gpu', True))
                line = json.dumps(data, ensure_ascii=False,
                                  allow_nan=False) + '\n'
                with self.ser_lock:
                    if self.ser:
                        self.ser.write(line.encode('utf-8'))
                self._tx_count += 1
                self._latest = data
                fail_count = 0
            except Exception as e:
                fail_count += 1
                log(f"发送失败 #{fail_count}: {e}")
                if fail_count <= 3 or fail_count % 50 == 0:
                    log(traceback.format_exc())
                if fail_count > 100:
                    log("连续失败 > 100，停止发送")
                    self.running = False
                    break

            perf_record('main_loop', time.time() - t0)

    # ---------- 状态刷新（500ms） ----------
    def poll_status(self):
        d = self._latest
        if d:
            gpu_str = f"{d['gpu']:5.1f}%" if d['gpu_ok'] else '  N/A'
            temp_str = f"{d['cpu_temp']:5.1f}C" if d['has_temp'] else ' N/A '
            self.status_var.set(
                f"TX#{self._tx_count}  "
                f"CPU {d['cpu']:5.1f}%  "
                f"TEMP {temp_str}  "
                f"MEM {d['mem']:5.1f}%  "
                f"GPU {gpu_str}"
            )
        elif self.running:
            self.status_var.set(f"TX#{self._tx_count}  等待数据...")
        self.root.after(500, self.poll_status)

    # ---------- 刷新率 ----------
    def on_rate_change(self, val):
        v = max(1, min(30, int(float(val))))
        if v == self._rate:
            return
        self.rate_hz.set(v)
        self._rate = v
        SHARED.set('rate', v)
        self.rate_label.config(text=f'{v} Hz')
        self.save_current_settings()

    # ---------- 关闭 ----------
    def on_close(self):
        self.running = False
        self._connecting = False
        _stop_flag.set()          # 通知后台线程退出
        if _gpu_reader:
            _gpu_reader.shutdown()
        self.save_current_settings()
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        log("退出")
        self.root.destroy()


# ============================================================
#  入口
# ============================================================
def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log("主程序崩溃:\n" + traceback.format_exc())
        raise