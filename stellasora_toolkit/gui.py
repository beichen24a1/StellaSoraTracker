from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from PIL import Image, ImageDraw, ImageOps, ImageTk

from .admin import ensure_administrator
from .process import GameProcess, find_game_processes
from .app_updater import (
    UPDATE_MANIFEST_URL,
    AppUpdate,
    check_for_update,
    download_update,
    launch_update_installer,
)
from .catalog import (
    format_random_attr,
    gacha_item_name,
    gem_type_name,
    is_five_star_item,
    table_values,
    traveler_name,
)
from .service import LEGACY_ARCHIVE_FILENAME, Snapshot, archive_path_for_uid, extract_snapshot, load_latest_snapshot
from .upload import mark_upload_success, upload_archive
from .gacha_display import SparkReward, build_spark_rewards, insert_spark_rewards
from .gacha_stats import (
    CATEGORY_DISC_LIMITED,
    CATEGORY_DISC_STANDARD,
    CATEGORY_TRAVELER_LIMITED,
    CATEGORY_TRAVELER_STANDARD,
    FiveStarPull,
    PoolStats,
    build_category_stat,
    build_banner_stats_with_shared_pity,
    build_pool_stats,
    classify_history_category,
)


BG = "#eaf2f8"
PANEL = "#fdfefe"
INK = "#31445b"
MUTED = "#71839a"
LINE = "#cfdae6"
ACCENT = "#5a89a7"
ACCENT_DARK = "#476d8b"
WARM = "#c58b68"
HEADER = "#607d98"
POOL_COLORS = ("#7776aa", "#4d9ba0", "#5d82a9", "#8e6d9c")
FIVE_STAR_AVATAR_SIZE = 70
FIVE_STAR_TILE_IMAGE_SIZE = 78
APP_VERSION = "1.2.22"
GACHA_CATEGORY_ORDER = (
    CATEGORY_TRAVELER_LIMITED,
    CATEGORY_DISC_LIMITED,
    CATEGORY_TRAVELER_STANDARD,
    CATEGORY_DISC_STANDARD,
)
GACHA_CATEGORY_NAMES = {
    CATEGORY_TRAVELER_LIMITED: "旅人限时招募",
    CATEGORY_DISC_LIMITED: "秘纹限时招募",
    CATEGORY_TRAVELER_STANDARD: "旅人常驻招募",
    CATEGORY_DISC_STANDARD: "秘纹常驻招募",
}
GACHA_CATEGORY_PITY_LIMITS = {
    CATEGORY_TRAVELER_LIMITED: 160,
    CATEGORY_DISC_LIMITED: 120,
    CATEGORY_TRAVELER_STANDARD: 160,
    CATEGORY_DISC_STANDARD: 120,
}
OFFICIAL_LIMITED_POOL_INFO = {
    10143: ("划破黑暗的银枪", "2026-02-24", "2026-03-17", "风影"),
    20143: ("春日暖阳梦微醺", "2026-02-24", "2026-03-17", "春日纪事"),
    10130: ("篇篇心意 准点送递", "2026-03-17", "2026-04-07", "多娜"),
    20130: ("随愿启航的幸福气球", "2026-03-17", "2026-04-07", "飞越青空"),
    10145: ("夜樱尽头暗月沉", "2026-04-16", "2026-05-08", "乙叶"),
    20145: ("百合芬香伴烟起", "2026-04-16", "2026-05-08", "繁花幻梦"),
    10115: ("乘光而起的星之砂", "2026-05-14", "2026-06-02", "火垂"),
    20115: ("若能触及那片繁星", "2026-05-14", "2026-06-02", "星之所向"),
    10140: ("完美无缺的最终解", "2026-06-02", "2026-06-23", "斯帕克拉"),
    20140: ("奇思妙想，寄于手作", "2026-06-02", "2026-06-23", "微小的乐园"),
    10160: ("下水之前别忘热身！", "2026-07-21", "2026-08-11", "薇洛(盛夏)"),
    20160: ("波光荡漾，轻触的指尖", "2026-07-21", "2026-08-11", "浮光掠影"),
    20157: ("碧浪晕七彩", "2026-08-18", "2026-09-08", "伴我航行"),
    11133: ("摇曳轻风纯情香", "2026-08-04", "2026-08-25", "夏花"),
    21133: ("午后微光、共入翠梦", "2026-08-04", "2026-08-25", "鹿鸣"),
    10157: ("追晴逐日的花漫波", "2026-08-18", "2026-09-08", "花铃"),
    10137: ("优雅起舞 千金驾到", "2026-09-08", "2026-09-29", "埃莉诺"),
    20137: ("飞向梦寐以求的世界", "2026-09-08", "2026-09-29", "飞吧，笼中鸟"),
    10139: ("沐于温情笑意中", "2026-09-29", "2026-10-20", "艾蕾"),
    20139: ("空白的稚梦", "2026-09-29", "2026-10-20", "睡前童话"),
    11110: ("辉映碧玉的理型", "2026-10-06", "2026-10-27", "翡冷翠"),
    21110: ("微醺茶香，藤花幽梦", "2026-10-06", "2026-10-27", "仙踪良梦"),
    # Official limited-banner UP data sourced from Stella Sora announcements/API.
    10110: ("辉映碧玉的理型", "2026-01-13", "2026-02-03", "翡冷翠"),
    10114: ("喵次元的狙击手", "2026-06-30", "2026-07-21", "猫眼"),
    10119: ("命定奇遇", "2025-11-11", "2025-12-02", "花原"),
    10125: ("命定奇遇", "2025-12-30", "2026-01-20", "苍兰"),
    10132: ("命定奇遇", "2026-03-10", "2026-03-31", "密涅瓦"),
    10133: ("摇曳轻风纯情香", "2025-12-09", "2025-12-30", "夏花"),
    10134: ("雪融时分新芽绽", "2025-11-18", "2025-12-09", "冬香"),
    10135: ("命定奇遇", "2026-01-27", "2026-02-17", "雾语"),
    10141: ("命定奇遇", "2026-02-17", "2026-03-10", "赤霞"),
    10144: ("夜月倾流，闪烁刀影里", "2025-10-20", "2025-11-11", "千都世"),
    10149: ("命定奇遇", "2025-12-02", "2025-12-23", "格芮"),
    10155: ("直抵圆月的超巨浪", "2025-10-28", "2025-11-18", "希娅"),
    10156: ("命定奇遇", "2026-03-31", "2026-04-21", "小禾"),
    10158: ("圣夜送礼大作战！", "2025-12-23", "2026-01-13", "菈露（圣夜）"),
    10159: ("点滴心语，余温尚存时", "2026-02-03", "2026-02-24", "科洛妮丝（新春）"),
    11119: ("命定奇遇", "2026-06-16", "2026-07-07", "花原"),
    11134: ("雪融时分新芽绽", "2026-09-01", "2026-09-22", "冬香"),
    11141: ("命定奇遇", "2026-07-14", "2026-08-04", "赤霞"),
    11144: ("夜月倾流，闪烁刀影里", "2026-04-30", "2026-05-19", "千都世"),
    11155: ("直抵圆月的超巨浪", "2026-05-26", "2026-06-16", "希娅"),
    20110: ("微醺茶香，藤花幽梦", "2026-01-13", "2026-02-03", "仙踪良梦"),
    20114: ("我已喵准你的心", "2026-06-30", "2026-07-21", "猫之珍藏"),
    20115: ("若能触及那片繁星", "2026-05-14", "2026-06-02", "星之所向"),
    20119: ("心弦定音", "2025-11-11", "2025-12-02", "白日花园"),
    20125: ("心弦定音", "2025-12-30", "2026-01-20", "晴之花"),
    20130: ("随愿启航的幸福气球", "2026-03-17", "2026-04-07", "飞越青空"),
    20132: ("心弦定音", "2026-03-10", "2026-03-31", "午夜，堕天使"),
    20133: ("午后微光、共入翠梦", "2025-12-09", "2025-12-30", "鹿鸣"),
    20134: ("绚丽夜空、烟花绽放", "2025-11-18", "2025-12-09", "花火"),
    20135: ("心弦定音", "2026-01-27", "2026-02-17", "魔女的秋千"),
    20140: ("奇思妙想，寄于手作", "2026-06-02", "2026-06-23", "微小的乐园"),
    20141: ("心弦定音", "2026-02-17", "2026-03-10", "龙飞凤舞"),
    20144: ("浮月倒映清潭上", "2025-10-20", "2025-11-11", "潋滟故池水"),
    20149: ("心弦定音", "2025-12-02", "2025-12-23", "迷途的朝圣者"),
    20155: ("海天共一色", "2025-10-28", "2025-11-18", "波光漫游"),
    20156: ("心弦定音", "2026-03-31", "2026-04-21", "抓住传说"),
    20158: ("薯条之国的颂歌", "2025-12-23", "2026-01-13", "雪夜惊喜"),
    20159: ("初醒眷恋 如梦之影", "2026-02-03", "2026-02-24", "罗帷春染岁朝新"),
    21119: ("心弦定音", "2026-06-16", "2026-07-07", "白日花园"),
    21134: ("绚丽夜空、烟花绽放", "2026-09-01", "2026-09-22", "花火"),
    21141: ("心弦定音", "2026-07-14", "2026-08-04", "龙飞凤舞"),
    21144: ("浮月倒映清潭上", "2026-04-30", "2026-05-19", "潋滟故池水"),
    21155: ("海天共一色", "2026-05-26", "2026-06-16", "波光漫游"),
}


class GameProcessDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Tk, processes: list[GameProcess]):
        self.processes = processes
        super().__init__(parent, title="选择游戏客户端")

    def body(self, master: tk.Frame):
        self.tree = ttk.Treeview(master, columns=("name", "pid", "path"), show="headings", selectmode="browse", height=min(7, len(self.processes)))
        for column, label, width in (("name", "客户端", 160), ("pid", "PID", 80), ("path", "程序位置", 380)):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=width, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(master, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        for index, process in enumerate(self.processes):
            self.tree.insert("", "end", iid=str(index), values=(process.name, process.pid, process.path or "-"))
        self.path_var = tk.StringVar(master=master, value=self.processes[0].path or "-")
        ttk.Label(master, textvariable=self.path_var, wraplength=610, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.tree.bind("<<TreeviewSelect>>", self._show_path)
        self.tree.selection_set("0")
        self.tree.focus("0")
        self.tree.bind("<Double-1>", self.ok)
        return self.tree

    def _show_path(self, _event=None) -> None:
        if self.tree.selection():
            self.path_var.set(self.processes[int(self.tree.selection()[0])].path or "-")

    def buttonbox(self) -> None:
        buttons = ttk.Frame(self)
        ttk.Button(buttons, text="读取", command=self.ok).pack(side="left", padx=5)
        ttk.Button(buttons, text="取消", command=self.cancel).pack(side="left", padx=5)
        buttons.pack(pady=10)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self) -> bool:
        return bool(self.tree.selection())

    def apply(self) -> None:
        self.result = self.processes[int(self.tree.selection()[0])]


class StellaSoraApp:
    def __init__(self, root: tk.Tk, output_dir: Path):
        self.root = root
        self.output_dir = output_dir
        self._cleanup_stale_update_files()
        self.snapshot: Snapshot | None = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.gacha_rows: dict[str, dict] = {}
        self.emblem_rows: dict[str, dict] = {}
        self.avatar_images: list[ImageTk.PhotoImage] = []
        self.gacha_avatar_images: list[ImageTk.PhotoImage] = []
        self.pool_columns = tk.IntVar(value=self._load_pool_columns())
        self.gacha_page = 1
        self.gacha_grid_columns = 0
        self.busy = False
        self.uploading = False
        self.update_checking = False

        self.root.title("星塔旅人数据工具")
        self._set_window_icon()
        self.root.geometry("1180x760")
        self.root.minsize(940, 620)
        self.root.configure(bg=BG)
        self._configure_styles()
        self._build_ui()
        self.root.after(100, self._poll_events)
        self._load_latest()
        if getattr(sys, "frozen", False):
            self.root.after(1600, lambda: self.check_app_update(silent=True))

    def _set_window_icon(self) -> None:
        resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        icon_path = resource_root / "assets" / "app_icon.png"
        if not icon_path.exists():
            return
        try:
            self.app_icon = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self.app_icon)
        except tk.TclError:
            pass

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Header.TFrame", background=HEADER)
        style.configure("Header.TLabel", background=HEADER, foreground="#ffffff", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("HeaderSub.TLabel", background=HEADER, foreground="#e4edf5", font=("Microsoft YaHei UI", 9))
        style.configure("Metric.TLabel", background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("MetricName.TLabel", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("TLabel", background=BG, foreground=INK, font=("Microsoft YaHei UI", 9))
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(12, 7), borderwidth=0)
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("disabled", "#adc0cf")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 9), font=("Microsoft YaHei UI", 10), background="#dbe6ef")
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT_DARK)])
        style.configure("Treeview", rowheight=30, font=("Microsoft YaHei UI", 9), background=PANEL, fieldbackground=PANEL, bordercolor=LINE)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"), background="#e4edf5", foreground=INK, padding=(6, 7))
        style.map("Treeview", background=[("selected", "#dceaf4")], foreground=[("selected", INK)])
        style.configure("Horizontal.TProgressbar", troughcolor="#d7e2eb", background=ACCENT, borderwidth=0)
        style.configure("Layout.TRadiobutton", background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 9), padding=(5, 0))
        style.configure("FiveStarLayout.TRadiobutton", background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 9), padding=(5, 0))

    @staticmethod
    def _cleanup_stale_update_files() -> None:
        if not getattr(sys, "frozen", False):
            return
        for path in Path(sys.executable).resolve().parent.glob("stellasora-update-*.exe"):
            try:
                path.unlink()
            except OSError:
                pass

    def _build_ui(self) -> None:
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.app_canvas = tk.Canvas(self.root, background=BG, highlightthickness=0, borderwidth=0)
        self.app_scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.app_canvas.yview)
        self.app_canvas.configure(yscrollcommand=self.app_scrollbar.set)
        self.app_canvas.grid(row=0, column=0, sticky="nsew")
        self.app_scrollbar.grid(row=0, column=1, sticky="ns")
        self.app_content = ttk.Frame(self.app_canvas, style="App.TFrame")
        app_window = self.app_canvas.create_window((0, 0), window=self.app_content, anchor="nw")
        self.app_content.bind(
            "<Configure>",
            lambda _event: self.app_canvas.configure(scrollregion=self.app_canvas.bbox("all")),
        )
        self.app_canvas.bind(
            "<Configure>",
            lambda event: self.app_canvas.itemconfigure(app_window, width=event.width),
        )
        self.app_canvas.bind("<Enter>", lambda _event: self.app_canvas.bind_all("<MouseWheel>", self._scroll_app))
        self.app_canvas.bind("<Leave>", lambda _event: self.app_canvas.unbind_all("<MouseWheel>"))

        header = ttk.Frame(self.app_content, style="Header.TFrame", padding=(24, 17))
        header.pack(fill="x")
        header.columnconfigure(1, weight=1)
        title_box = ttk.Frame(header, style="Header.TFrame")
        title_box.grid(row=0, column=0, sticky="w")
        ttk.Label(title_box, text="星塔旅人数据工具", style="Header.TLabel").pack(anchor="w")
        self.account_label = tk.StringVar(value="四类卡池与五星记录")
        ttk.Label(title_box, textvariable=self.account_label, style="HeaderSub.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(header, text=f"当前版本 v{APP_VERSION}", style="HeaderSub.TLabel").grid(
            row=0, column=1, sticky="e", padx=(16, 18)
        )
        actions = ttk.Frame(header, style="Header.TFrame")
        actions.grid(row=1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.open_button = ttk.Button(actions, text="打开导出目录", command=self._open_exports)
        self.open_button.pack(side="left", padx=(0, 8))
        self.update_button = ttk.Button(actions, text="检查更新", command=self.check_app_update)
        self.update_button.pack(side="left", padx=(0, 8))
        self.upload_button = ttk.Button(actions, text="上传抽卡记录到蕾姆", command=self.upload_to_rem)
        self.upload_button.pack(side="left", padx=(0, 8))
        self.refresh_button = ttk.Button(actions, text="刷新游戏数据", style="Accent.TButton", command=self.refresh)
        self.refresh_button.pack(side="left")

        body = ttk.Frame(self.app_content, style="App.TFrame", padding=(20, 16, 20, 12))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        metrics = ttk.Frame(body, style="App.TFrame")
        metrics.grid(row=0, column=0, sticky="ew")
        for column in range(6):
            metrics.columnconfigure(column, weight=1, uniform="metric")
        self.metric_pulls = self._metric(metrics, 0, "累计抽取", "#4d9ba0", 6)
        self.metric_five_stars = self._metric(metrics, 1, "五星记录", "#c58b68", 6)
        self.metric_rate = self._metric(metrics, 2, "五星概率", "#7776aa", 6)
        self.metric_average = self._metric(metrics, 3, "平均五星抽数", "#8e6d9c", 6)
        self.metric_groups = self._metric(metrics, 4, "已加载分类", "#5d82a9", 6)
        self.metric_batches = self._metric(metrics, 5, "归档批次", "#476d8b", 6)

        status_row = ttk.Frame(body, style="App.TFrame")
        status_row.grid(row=1, column=0, sticky="ew", pady=(13, 10))
        status_row.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="等待读取")
        ttk.Label(status_row, textvariable=self.status_var, foreground=MUTED).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(status_row, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=1, sticky="e")
        self.progress.grid_remove()

        self.notebook = ttk.Notebook(body)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self._build_home_tab()
        self._build_gacha_tab()
        self._build_settings_tab()
        self._build_help_tab()

    def _scroll_app(self, event) -> None:
        self.app_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _metric(self, parent: ttk.Frame, column: int, name: str, color: str, count: int) -> tk.StringVar:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=(16, 12))
        frame.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 5, 0 if column == count - 1 else 5))
        strip = tk.Frame(frame, width=4, height=48, bg=color)
        strip.pack(side="left", fill="y", padx=(0, 12))
        content = ttk.Frame(frame, style="Panel.TFrame")
        content.pack(side="left", fill="both")
        value = tk.StringVar(value="-")
        ttk.Label(content, textvariable=value, style="Metric.TLabel").pack(anchor="w")
        ttk.Label(content, text=name, style="MetricName.TLabel").pack(anchor="w")
        return value

    def _build_gacha_tab(self) -> None:
        tab = ttk.Frame(self.notebook, style="Panel.TFrame")
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text="招募记录")

        sidebar = tk.Frame(tab, background="#edf3f7", width=220)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        tk.Label(
            sidebar,
            text="招募记录",
            background="#edf3f7",
            foreground=INK,
            font=("Microsoft YaHei UI", 14, "bold"),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(16, 2))
        self.gacha_sidebar_summary = tk.StringVar(value="等待加载本地归档")
        tk.Label(
            sidebar,
            textvariable=self.gacha_sidebar_summary,
            background="#edf3f7",
            foreground=MUTED,
            font=("Microsoft YaHei UI", 8),
            justify="left",
            anchor="w",
            wraplength=184,
        ).pack(fill="x", padx=16, pady=(0, 14))
        self.gacha_filter_sidebar = tk.Frame(sidebar, background="#edf3f7")
        self.gacha_filter_sidebar.pack(fill="x", padx=10)

        content = ttk.Frame(tab, style="Panel.TFrame", padding=(18, 16, 18, 18))
        content.grid(row=0, column=1, sticky="new")
        content.columnconfigure(0, weight=1)
        self.gacha_category_filter = tk.StringVar(value="all")

        heading = tk.Frame(content, background=PANEL)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        tk.Label(
            heading,
            text="五星招募记录",
            background=PANEL,
            foreground=INK,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(side="left")
        tk.Label(
            heading,
            text="限时池五星间隔按同类卡池继承计算 · 常驻池独立计算 · 卡片右侧为该池抽数",
            background=PANEL,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(side="right")

        self.gacha_rows_content = tk.Frame(content, background=PANEL)
        self.gacha_rows_content.grid(row=1, column=0, sticky="new")
        self.gacha_rows_content.grid_columnconfigure(0, weight=1)

    def _build_home_tab(self) -> None:
        tab = ttk.Frame(self.notebook, style="Panel.TFrame")
        tab.columnconfigure(0, weight=1)
        self.notebook.add(tab, text="首页")
        self.stats_content = ttk.Frame(tab, style="App.TFrame")
        self.stats_content.grid(row=0, column=0, sticky="new")

    def _build_settings_tab(self) -> None:
        tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(24, 20))
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text="设置")

        tk.Label(tab, text="设置", background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        tk.Label(tab, text="管理本地归档、备份与软件版本", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 9)).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 18)
        )

        archive_panel = tk.Frame(tab, background="#f4f8fb", highlightbackground=LINE, highlightthickness=1)
        archive_panel.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        data_panel = tk.Frame(tab, background="#f4f8fb", highlightbackground=LINE, highlightthickness=1)
        data_panel.grid(row=2, column=1, sticky="nsew", padx=(8, 0))
        self.settings_archive_path = tk.StringVar(value=str(self.output_dir / "UID.json"))
        self.settings_summary = tk.StringVar(value="尚未加载本地归档")

        tk.Label(archive_panel, text="本地归档", background="#f4f8fb", foreground=INK, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(archive_panel, text="招募历史会合并保存在此文件中。", background="#f4f8fb", foreground=MUTED).pack(anchor="w", padx=16)
        tk.Label(archive_panel, textvariable=self.settings_archive_path, background="#f4f8fb", foreground=ACCENT_DARK, justify="left", anchor="w", wraplength=400).pack(fill="x", padx=16, pady=(16, 14))
        actions = tk.Frame(archive_panel, background="#f4f8fb")
        actions.pack(anchor="w", padx=16, pady=(0, 16))
        ttk.Button(actions, text="打开目录", command=self._open_exports).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="复制路径", command=self._copy_archive_path).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="创建备份", style="Accent.TButton", command=self._backup_archive).pack(side="left")
        self.copy_bind_button = ttk.Button(archive_panel, text="复制蕾姆绑定指令", command=self._copy_bind_command, state="disabled")
        self.copy_bind_button.pack(anchor="w", padx=16, pady=(0, 16))

        tk.Label(data_panel, text="本地数据", background="#f4f8fb", foreground=INK, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(data_panel, textvariable=self.settings_summary, background="#f4f8fb", foreground=MUTED, justify="left", anchor="w", wraplength=400).pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(data_panel, text="软件更新", background="#f4f8fb", foreground=INK, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=16, pady=(4, 6))
        settings_actions = tk.Frame(data_panel, background="#f4f8fb")
        settings_actions.pack(anchor="w", padx=16, pady=(0, 16))
        ttk.Button(settings_actions, text="检查软件更新", command=self.check_app_update).pack(side="left")

    def _build_help_tab(self) -> None:
        tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(24, 20))
        tab.columnconfigure(0, weight=1)
        self.notebook.add(tab, text="使用说明")

        wrap_labels: list[tk.Label] = []

        def heading(text: str, *, warning: bool = False) -> None:
            tk.Label(
                tab,
                text=text,
                background=PANEL,
                foreground="#b7603f" if warning else ACCENT_DARK,
                font=("Microsoft YaHei UI", 12, "bold"),
                anchor="w",
            ).grid(row=tab.grid_size()[1], column=0, sticky="ew", pady=(14, 6))

        def paragraph(text: str, *, muted: bool = False) -> None:
            label = tk.Label(
                tab,
                text=text,
                background=PANEL,
                foreground=MUTED if muted else INK,
                font=("Microsoft YaHei UI", 9),
                justify="left",
                anchor="nw",
                wraplength=900,
            )
            label.grid(row=tab.grid_size()[1], column=0, sticky="ew", pady=2)
            wrap_labels.append(label)

        tk.Label(
            tab,
            text="使用说明与风险提示",
            background=PANEL,
            foreground=INK,
            font=("Microsoft YaHei UI", 16, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        paragraph("本工具用于整理《星塔旅人》Windows 客户端中当前账号已加载的招募历史，可自动识别 xtlr.exe / StellaSora.exe。", muted=True)

        heading("使用方法")
        paragraph("1. 登录游戏并进入主界面，在游戏内依次打开旅人限时、秘纹限时、旅人常驻、秘纹常驻四类招募记录，等待每个记录列表显示。")
        paragraph("2. 打开本工具并确认 Windows 管理员授权提示，再点击“刷新游戏数据”；多个游戏客户端同时运行时，按程序位置和 PID 选择本次要读取的客户端。取消授权时软件不会启动。")
        paragraph("3. 新角色和秘纹图片会随软件版本内置更新；软件版本可通过“检查更新”进行升级。")

        heading("数据与备份")
        paragraph("每次刷新都会合并更新 exports/UID.json，其中 UID 是当前游戏账号的数字标识。官方记录可能只保留最近半年，请定期备份该文件。")
        paragraph("归档使用从所选进程读取的完整 UID，不按 UID 前缀推断区服；当前仍使用内置中文名称和卡池资料，海外客户端的 UID 与记录读取兼容性需要实际验证。")
        paragraph("点击“上传抽卡记录到蕾姆”会上传完整 UID.json。同一 UID 在本地首次上传成功时弹出绑定指令，之后不再弹出；设置中始终可以复制指令。现有接口每次上传后仍需向蕾姆发送该指令确认更新，上传成功不代表正式记录已经更新。")
        paragraph("归档包含游戏 UID 和抽卡记录，不包含密码、Cookie、SDK token、进程地址或网络会话数据。上传仅在点击上传按钮后进行，请勿公开分享归档。")

        heading("风险与免责声明", warning=True)
        paragraph("• 本项目是非官方个人研究工具，与游戏运营方、开发方不存在关联，也未获得官方认可或授权。")
        paragraph("• 工具通过 Windows ReadProcessMemory 只读访问当前客户端已加载的招募历史；不注入 DLL、不修改游戏文件或内存、不发送游戏协议请求。上述设计不构成对账号安全、封号风险或长期可用性的保证。")
        paragraph("• 游戏客户端、反作弊策略、服务条款及适用法律法规均可能变化。使用者应自行阅读并遵守相关条款，仅对自己的账号和设备使用，并自行评估风险。")
        paragraph("• 因使用或无法使用本工具、数据不完整、游戏更新、账号处置或第三方服务变化造成的任何直接或间接损失，项目维护者不承担责任。")
        paragraph("• 使用本工具即表示使用者已理解上述工作方式与风险，并自行承担使用后果。")

        def update_wrap(event) -> None:
            wraplength = max(420, event.width - 48)
            for label in wrap_labels:
                label.configure(wraplength=wraplength)

        tab.bind("<Configure>", update_wrap)

    def _semantic_gacha_categories(self) -> dict[str, list[dict]]:
        if self.snapshot is None:
            return {}
        categories = self.snapshot.gacha_categories or {1: self.snapshot.gacha}
        semantic_categories: dict[str, list[dict]] = {}
        for groups in categories.values():
            category = classify_history_category(groups)
            semantic_categories.setdefault(category, []).extend(groups)
        return semantic_categories

    def _fill_five_star_stats(self) -> None:
        for child in self.stats_content.winfo_children():
            child.destroy()
        self.avatar_images.clear()
        if self.snapshot is None:
            return
        semantic_categories = self._semantic_gacha_categories()
        stats_by_category = {
            category: build_category_stat(semantic_categories.get(category, []))
            for category in GACHA_CATEGORY_ORDER
        }
        pity_stats_by_category = {
            category: build_category_stat(semantic_categories.get(category, []), is_up=self._is_up_item)
            for category in GACHA_CATEGORY_ORDER
        }
        spark_rewards = build_spark_rewards(semantic_categories.get(CATEGORY_TRAVELER_LIMITED, []), OFFICIAL_LIMITED_POOL_INFO)
        total_five = sum(len(stat.five_stars) for stat in stats_by_category.values() if stat is not None)
        self._build_home_summary(pity_stats_by_category, recent_stats=stats_by_category)

        intro = ttk.Frame(self.stats_content, style="Panel.TFrame", padding=(14, 11))
        intro.pack(fill="x", padx=12, pady=(12, 8))
        ttk.Label(
            intro,
            text=f"四类卡池详情 · 五星记录 {total_five}",
            background=PANEL,
            foreground=INK,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left")
        layout_switch = ttk.Frame(intro, style="Panel.TFrame")
        layout_switch.pack(side="right")
        ttk.Radiobutton(
            layout_switch,
            text="双列",
            variable=self.pool_columns,
            value=2,
            command=self._refresh_pool_layout,
            style="FiveStarLayout.TRadiobutton",
        ).pack(side="left")
        ttk.Radiobutton(
            layout_switch,
            text="单列",
            variable=self.pool_columns,
            value=1,
            command=self._refresh_pool_layout,
            style="FiveStarLayout.TRadiobutton",
        ).pack(side="left")

        pool_grid = ttk.Frame(self.stats_content, style="App.TFrame")
        pool_grid.pack(fill="x", padx=12, pady=(2, 8))
        grid_columns = self.pool_columns.get()
        for column in range(grid_columns):
            pool_grid.columnconfigure(column, weight=1, uniform="pool-column")
        color_index = 0
        for index, category in enumerate(GACHA_CATEGORY_ORDER):
            name = GACHA_CATEGORY_NAMES[category]
            category_stat = stats_by_category[category]
            panel = ttk.Frame(pool_grid, style="App.TFrame")
            panel.grid(
                row=index // grid_columns,
                column=index % grid_columns,
                sticky="nsew",
                padx=(0, 6) if grid_columns == 2 and index % grid_columns == 0 else (6, 0) if grid_columns == 2 else 0,
                pady=(0, 8),
            )
            pool_grid.rowconfigure(index // grid_columns, weight=1)
            if category_stat is None:
                self._build_missing_category(panel)
                continue
            self._build_pool_section(
                category_stat,
                POOL_COLORS[color_index % len(POOL_COLORS)],
                name,
                panel,
                category=category,
                display_entries=insert_spark_rewards(category_stat.five_stars, spark_rewards)
                if category == CATEGORY_TRAVELER_LIMITED else category_stat.five_stars,
            )
            color_index += 1

    def _build_home_summary(
        self,
        stats_by_category: dict[str, PoolStats | None],
        *,
        recent_stats: dict[str, PoolStats | None] | None = None,
    ) -> None:
        recent_stats = recent_stats or stats_by_category
        summary = ttk.Frame(self.stats_content, style="App.TFrame")
        summary.pack(fill="x", padx=12, pady=(12, 0))
        summary.columnconfigure(0, weight=3)
        summary.columnconfigure(1, weight=2)

        pity_panel = tk.Frame(summary, background=PANEL, highlightbackground=LINE, highlightthickness=1)
        pity_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        recent_panel = tk.Frame(summary, background=PANEL, highlightbackground=LINE, highlightthickness=1)
        recent_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        tk.Label(
            pity_panel,
            text="当前垫抽",
            background=PANEL,
            foreground=INK,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(
            pity_panel,
            text="各类卡池独立统计，以当前本地归档为准。",
            background=PANEL,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=16, pady=(0, 10))
        for category in GACHA_CATEGORY_ORDER:
            stat = stats_by_category.get(category)
            row = tk.Frame(pity_panel, background=PANEL)
            row.pack(fill="x", padx=16, pady=(0, 10))
            title = GACHA_CATEGORY_NAMES[category]
            if stat is None:
                tk.Label(row, text=title, background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
                tk.Label(row, text="尚未加载", background=PANEL, foreground=WARM, font=("Microsoft YaHei UI", 8)).pack(anchor="e")
                continue
            top = tk.Frame(row, background=PANEL)
            top.pack(fill="x")
            tk.Label(top, text=title, background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
            pity_limit = GACHA_CATEGORY_PITY_LIMITS[category]
            tk.Label(
                top,
                text=f"保底 {pity_limit} 抽",
                background=PANEL,
                foreground=MUTED,
                font=("Microsoft YaHei UI", 8),
            ).pack(side="right")
            progress = tk.Canvas(row, height=38, background=PANEL, highlightthickness=0, borderwidth=0)
            progress.pack(fill="x", pady=(5, 0))

            def draw_home_progress(
                event: tk.Event,
                *,
                canvas=progress,
                pity=stat.current_pity,
                limit=pity_limit,
            ) -> None:
                self._draw_pity_bar(canvas, event.width, pity, limit, height=34, font_size=10)

            progress.bind("<Configure>", draw_home_progress)

        tk.Label(
            recent_panel,
            text="最近五星",
            background=PANEL,
            foreground=INK,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 8))
        recent: list[tuple[int, str, Any]] = []
        for category, stat in recent_stats.items():
            if stat is None:
                continue
            recent.extend((pull.timestamp, category, pull) for pull in stat.five_stars)
        recent.sort(key=lambda item: item[0], reverse=True)
        if not recent:
            tk.Label(recent_panel, text="暂无五星记录", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 9)).pack(
                anchor="w", padx=16, pady=(0, 16)
            )
        for timestamp, category, pull in recent[:5]:
            row = tk.Frame(recent_panel, background=PANEL)
            row.pack(fill="x", padx=16, pady=(0, 8))
            photo = self._avatar_photo(pull.item_id, pull.kind, POOL_COLORS[GACHA_CATEGORY_ORDER.index(category)])
            self.avatar_images.append(photo)
            tk.Label(row, image=photo, background=PANEL, borderwidth=0).pack(side="left")
            text = tk.Frame(row, background=PANEL)
            text.pack(side="left", fill="x", expand=True, padx=(8, 0))
            tk.Label(text, text=pull.name, background=PANEL, foreground="#d87822", font=("Microsoft YaHei UI", 9, "bold"), anchor="w").pack(fill="x")
            tk.Label(
                text,
                text=f"{GACHA_CATEGORY_NAMES[category]} · {self._format_date(timestamp)} · {pull.pity} 抽",
                background=PANEL,
                foreground=MUTED,
                font=("Microsoft YaHei UI", 8),
                anchor="w",
            ).pack(fill="x")

    def _refresh_pool_layout(self) -> None:
        self._save_pool_columns()
        if self.snapshot is not None:
            self._fill_five_star_stats()

    def _load_pool_columns(self) -> int:
        try:
            settings = json.loads((self.output_dir / "ui_settings.json").read_text(encoding="utf-8"))
            return int(settings.get("pool_columns")) if int(settings.get("pool_columns")) in (1, 2) else 2
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 2

    def _save_pool_columns(self) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            (self.output_dir / "ui_settings.json").write_text(
                json.dumps({"pool_columns": self.pool_columns.get()}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _build_missing_category(self, parent: ttk.Frame | None = None) -> None:
        container = parent or self.stats_content
        frame = ttk.Frame(container, style="Panel.TFrame", padding=(13, 11))
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="该分类尚未进入游戏历史缓存，请在游戏中打开对应卡池的招募记录后再刷新。",
            background=PANEL,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 7),
        ).pack(anchor="w")

    def _build_pool_section(
        self,
        pool: PoolStats,
        color: str,
        category_name: str,
        parent: ttk.Frame | None = None,
        *,
        category: str,
        display_entries: tuple[FiveStarPull | SparkReward, ...] | None = None,
    ) -> None:
        container = parent or self.stats_content
        section = ttk.Frame(container, style="Panel.TFrame")
        section.pack(fill="both", expand=True)
        header = tk.Frame(section, background=color, height=82)
        header.pack(fill="x")
        header.pack_propagate(False)

        title = tk.Frame(header, background=color)
        title.pack(side="left", fill="both", expand=True, padx=20, pady=13)
        tk.Label(
            title,
            text=category_name,
            background=color,
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(anchor="w")
        date_text = f"{self._format_date(pool.start_time)}  -  {self._format_date(pool.end_time)}"
        tk.Label(
            title,
            text=date_text,
            background=color,
            foreground="#eef5fa",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(3, 0))

        summary = tk.Frame(header, background=self._darken(color))
        summary.pack(side="right", fill="y", padx=(0, 14), pady=10)
        self._pool_metric(summary, str(pool.total_pulls), "总抽数")
        self._pool_metric(summary, str(len(pool.five_stars)), "五星")
        if category in {CATEGORY_TRAVELER_LIMITED, CATEGORY_DISC_LIMITED}:
            up_average = self._up_average_pulls(pool)
            average = "-" if up_average is None else str(up_average)
            average_label = "UP 平均"
        else:
            average = "-" if pool.average_pulls is None else str(pool.average_pulls)
            average_label = "平均抽数"
        self._pool_metric(summary, average, average_label)

        hits = tk.Frame(section, background=PANEL)
        hits.pack(fill="x", padx=14, pady=(12, 14))
        entries = pool.five_stars if display_entries is None else display_entries
        if not entries:
            tk.Label(
                hits,
                text="该卡池的已加载记录中暂无五星角色",
                background=PANEL,
                foreground=MUTED,
                font=("Microsoft YaHei UI", 8),
                pady=16,
            ).pack(anchor="w")
            return
        last_columns = 0

        def render_tiles(_event=None) -> None:
            nonlocal last_columns
            columns = max(1, hits.winfo_width() // 92)
            if columns == last_columns and hits.winfo_children():
                return
            last_columns = columns
            for child in hits.winfo_children():
                child.destroy()
            for index, pull in enumerate(entries):
                tile = tk.Frame(hits, background=PANEL, width=82, height=100)
                tile.grid(row=index // columns, column=index % columns, padx=5, pady=5, sticky="nw")
                tile.grid_propagate(False)
                photo = self._square_avatar_photo(pull.item_id, pull.kind, color)
                self.avatar_images.append(photo)
                tk.Label(tile, image=photo, background=PANEL, borderwidth=0).place(
                    x=2, y=0, width=FIVE_STAR_TILE_IMAGE_SIZE, height=FIVE_STAR_TILE_IMAGE_SIZE
                )
                official_pool = OFFICIAL_LIMITED_POOL_INFO.get(pull.gid)
                if official_pool is not None:
                    is_up = self._same_item_name(pull.name, official_pool[3])
                    tk.Label(
                        tile,
                        text="UP" if is_up else "歪",
                        background="#25282d" if is_up else "#c7514a",
                        foreground="#ffffff",
                        font=("Microsoft YaHei UI", 7, "bold"),
                        padx=4,
                        pady=1,
                    ).place(x=78, y=2, anchor="ne")
                is_spark = isinstance(pull, SparkReward)
                badge_color = "#ad8138" if is_spark else "#4d9ba0" if pull.pity <= 30 else WARM if pull.pity <= 60 else "#b97a8a"
                tk.Label(
                    tile,
                    text="井" if is_spark else str(pull.pity),
                    background=badge_color,
                    foreground="#ffffff",
                    font=("Microsoft YaHei UI", 10, "bold"),
                ).place(x=2, y=78, width=FIVE_STAR_TILE_IMAGE_SIZE, height=22)

        hits.bind("<Configure>", render_tiles)
        self.root.after_idle(render_tiles)

    @staticmethod
    def _pool_metric(parent: tk.Frame, value: str, label: str) -> None:
        box = tk.Frame(parent, background=parent.cget("background"), width=41)
        box.pack(side="left", fill="y", padx=2)
        box.pack_propagate(False)
        tk.Label(
            box,
            text=value,
            background=box.cget("background"),
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(8, 0))
        tk.Label(
            box,
            text=label,
            background=box.cget("background"),
            foreground="#e5ebe7",
            font=("Microsoft YaHei UI", 8),
        ).pack()

    @classmethod
    def _up_average_pulls(cls, pool: PoolStats) -> int | None:
        up_count = sum(
            1
            for pull in pool.five_stars
            if (official_pool := OFFICIAL_LIMITED_POOL_INFO.get(pull.gid)) is not None
            and cls._same_item_name(pull.name, official_pool[3])
        )
        return round(pool.total_pulls / up_count) if up_count else None

    @classmethod
    def _is_up_item(cls, gid: int, item_id: int) -> bool:
        """Return whether a five-star belongs to the official UP on its banner.

        Standard pools have no single UP target, so their five-stars retain the
        historical reset behavior. Limited pools reset pity only on the named
        UP item; an off-banner five-star (歪) leaves pity running.
        """
        official_pool = OFFICIAL_LIMITED_POOL_INFO.get(gid)
        if official_pool is None:
            return True
        return cls._same_item_name(gacha_item_name(item_id), official_pool[3])

    @staticmethod
    def _darken(color: str) -> str:
        red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
        return f"#{int(red * .72):02x}{int(green * .72):02x}{int(blue * .72):02x}"

    @staticmethod
    def _format_date(timestamp: int) -> str:
        try:
            return datetime.fromtimestamp(timestamp).strftime("%Y.%m.%d")
        except (ValueError, OSError, OverflowError):
            return "未知日期"

    def _avatar_photo(self, item_id: int, kind: str, border_color: str) -> ImageTk.PhotoImage:
        folder = "travelers" if kind == "traveler" else "discs"
        resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        external_path = self.output_dir / "assets" / folder / f"{item_id}.png"
        path = external_path if external_path.exists() else resource_root / "assets" / folder / f"{item_id}.png"
        size = FIVE_STAR_AVATAR_SIZE
        try:
            source = Image.open(path).convert("RGBA")
            source = ImageOps.fit(source, (size - 6, size - 6), method=Image.Resampling.LANCZOS)
        except OSError:
            source = Image.new("RGBA", (size - 6, size - 6), "#dbe6ef")
            draw = ImageDraw.Draw(source)
            draw.text((12, 28), str(item_id), fill=INK)
        mask = Image.new("L", source.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, source.width - 1, source.height - 1), fill=255)
        source.putalpha(mask)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.ellipse((0, 0, size - 1, size - 1), fill=border_color)
        canvas.alpha_composite(source, (3, 3))
        return ImageTk.PhotoImage(canvas)

    def _square_avatar_photo(
        self,
        item_id: int,
        kind: str,
        border_color: str,
        *,
        size: int = FIVE_STAR_TILE_IMAGE_SIZE,
    ) -> ImageTk.PhotoImage:
        folder = "travelers" if kind == "traveler" else "discs"
        resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        external_path = self.output_dir / "assets" / folder / f"{item_id}.png"
        path = external_path if external_path.exists() else resource_root / "assets" / folder / f"{item_id}.png"
        try:
            source = Image.open(path).convert("RGBA")
            source = ImageOps.fit(source, (size - 4, size - 4), method=Image.Resampling.LANCZOS)
        except OSError:
            source = Image.new("RGBA", (size - 4, size - 4), "#dbe6ef")
            ImageDraw.Draw(source).text((10, 28), str(item_id), fill=INK)
        canvas = Image.new("RGBA", (size, size), border_color)
        canvas.alpha_composite(source, (2, 2))
        return ImageTk.PhotoImage(canvas)

    def _build_emblem_tab(self) -> None:
        tab = ttk.Frame(self.notebook, style="Panel.TFrame")
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(1, weight=1)
        self.notebook.add(tab, text="角色纹章")
        self.emblem_filter = tk.StringVar()
        self._toolbar(tab, self.emblem_filter, self._fill_emblems).grid(row=0, column=0, columnspan=2, sticky="ew")
        columns = ("traveler", "slot", "name", "lock", "attrs")
        self.emblem_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
        headings = {"traveler": "旅人", "slot": "槽位", "name": "纹章", "lock": "锁定", "attrs": "随机词条"}
        widths = {"traveler": 120, "slot": 86, "name": 150, "lock": 65, "attrs": 420}
        for column in columns:
            self.emblem_tree.heading(column, text=headings[column])
            self.emblem_tree.column(column, width=widths[column], minwidth=60, stretch=column == "attrs")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.emblem_tree.yview)
        self.emblem_tree.configure(yscrollcommand=scroll.set)
        self.emblem_tree.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=0, sticky="nse")
        self.emblem_tree.bind("<<TreeviewSelect>>", self._show_emblem_detail)

        detail = ttk.Frame(tab, style="Panel.TFrame", padding=(14, 10))
        detail.grid(row=1, column=1, sticky="nsew")
        detail.rowconfigure(1, weight=1)
        detail.columnconfigure(0, weight=1)
        ttk.Label(detail, text="纹章明细", background=PANEL, font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.detail_text = tk.Text(
            detail,
            wrap="word",
            relief="flat",
            borderwidth=0,
            background="#f3f8fc",
            foreground=INK,
            font=("Microsoft YaHei UI", 9),
            padx=12,
            pady=10,
            state="disabled",
        )
        self.detail_text.grid(row=1, column=0, sticky="nsew")

    def _load_latest(self) -> None:
        snapshot = load_latest_snapshot(self.output_dir)
        if snapshot is None:
            self.status_var.set("暂无本地数据，请启动并登录游戏后刷新")
            self._set_upload_button_state()
            return
        self._apply_snapshot(snapshot)
        self.status_var.set("已加载最近一次本地数据")
        self._set_upload_button_state()

    def refresh(self) -> None:
        if self.busy or self.update_checking or self.uploading:
            return
        try:
            processes = find_game_processes()
            if not processes:
                raise ProcessLookupError("未找到 xtlr.exe / StellaSora.exe，请先登录游戏并进入主界面")
            selected = processes[0] if len(processes) == 1 else GameProcessDialog(self.root, processes).result
            if selected is None:
                self.status_var.set("已取消读取游戏数据")
                return
        except (OSError, ValueError, LookupError) as error:
            self.status_var.set("未能选择游戏客户端")
            messagebox.showerror("读取失败", str(error), parent=self.root)
            return
        self.busy = True
        self.refresh_button.state(["disabled"])
        self.upload_button.state(["disabled"])
        self.update_button.state(["disabled"])
        self.progress.grid()
        self.progress.start(12)
        self.status_var.set(f"正在读取 {selected.name} · PID {selected.pid}")

        def work() -> None:
            try:
                snapshot = extract_snapshot(
                    self.output_dir,
                    process_name=selected.name,
                    process_id=selected.pid,
                    progress=lambda message: self.events.put(("progress", message)),
                )
                self.events.put(("complete", snapshot))
            except Exception as error:
                self.events.put(("error", error))

        threading.Thread(target=work, name="stellasora-reader", daemon=True).start()

    def _archive_path(self) -> Path:
        if self.snapshot is not None and self.snapshot.uid:
            return archive_path_for_uid(self.output_dir, self.snapshot.uid)
        return self.output_dir / LEGACY_ARCHIVE_FILENAME

    def _set_upload_button_state(self) -> None:
        if getattr(self, "upload_button", None) is None:
            return
        enabled = (
            not self.busy
            and self.snapshot is not None
            and bool(self.snapshot.uid)
            and self._archive_path().is_file()
        )
        self.upload_button.state(["!disabled"] if enabled else ["disabled"])

    def upload_to_rem(self) -> None:
        if self.busy or self.uploading or self.update_checking:
            return
        archive_path = self._archive_path()
        uid = self.snapshot.uid if self.snapshot is not None else None
        if not uid or not archive_path.is_file():
            messagebox.showinfo("上传抽卡记录", "尚未找到 UID.json，请先刷新游戏数据。", parent=self.root)
            return
        self.busy = True
        self.uploading = True
        self.refresh_button.state(["disabled"])
        self.upload_button.state(["disabled"])
        self.update_button.state(["disabled"])
        self.progress.grid()
        self.progress.start(12)
        self.status_var.set("正在上传抽卡记录到蕾姆")

        def work() -> None:
            try:
                result = upload_archive(archive_path, uid)
                state_error = None
                try:
                    first_upload = mark_upload_success(self.output_dir, uid)
                except (OSError, ValueError) as error:
                    first_upload = True
                    state_error = str(error)
                self.events.put(("upload_complete", (result, uid, first_upload, state_error)))
            except Exception as error:
                self.events.put(("upload_error", error))

        threading.Thread(target=work, name="stellasora-upload", daemon=True).start()

    def _copy_bind_command(self) -> None:
        if self.snapshot is not None and self.snapshot.uid:
            self.root.clipboard_clear()
            self.root.clipboard_append(f"星塔抽卡绑定 {self.snapshot.uid}")
            self.status_var.set("蕾姆绑定指令已复制")

    def _handle_upload_complete(self, payload: tuple) -> None:
        result, uid, first_upload, state_error = payload
        self._finish_busy()
        self.status_var.set("抽卡记录上传成功，已暂存；请向蕾姆确认更新")
        if first_upload:
            command = result.bind_command or f"星塔抽卡绑定 {uid}"
            messagebox.showinfo(
                "首次上传成功",
                "完整抽卡归档已暂存到蕾姆服务器。\n\n请发送以下指令给蕾姆：\n"
                + command
                + "\n\n可在设置中复制指令。同一 UID 后续上传不再弹出此提示。"
                + "\n现有接口每次上传仍需发送该指令确认更新。",
                parent=self.root,
            )
        if state_error:
            self.status_var.set("上传已成功，但未能保存首次提示标记；下次可能再次提示")

    def check_app_update(self, silent: bool = False) -> None:
        if self.busy or self.update_checking:
            return
        if not getattr(sys, "frozen", False):
            if not silent:
                messagebox.showinfo("检查更新", "源码运行模式不会自动替换程序，请使用打包后的 exe。", parent=self.root)
            return
        self.update_checking = True
        self.update_button.state(["disabled"])
        if not silent:
            self.status_var.set("正在检查软件更新")

        def work() -> None:
            try:
                update = check_for_update(UPDATE_MANIFEST_URL, APP_VERSION)
                self.events.put(("app_update_result", (update, silent)))
            except Exception as error:
                self.events.put(("app_update_error", (error, silent)))

        threading.Thread(target=work, name="stellasora-update-check", daemon=True).start()

    def _download_app_update(self, update: AppUpdate) -> None:
        self.busy = True
        self.refresh_button.state(["disabled"])
        self.update_button.state(["disabled"])
        self.upload_button.state(["disabled"])
        self.progress.grid()
        self.progress.start(12)
        self.status_var.set(f"正在下载软件更新 {update.version}")

        def work() -> None:
            try:
                path = download_update(
                    update,
                    self.output_dir / "updates",
                    progress=lambda message: self.events.put(("progress", message)),
                )
                self.events.put(("app_update_downloaded", (update, path)))
            except Exception as error:
                self.events.put(("app_update_download_error", error))

        threading.Thread(target=work, name="stellasora-update-download", daemon=True).start()

    def _install_app_update(self, downloaded_path: Path) -> None:
        launch_update_installer(downloaded_path, Path(sys.executable))
        self.root.destroy()

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    self.status_var.set(str(payload))
                elif event == "complete":
                    self._apply_snapshot(payload)
                    self._finish_busy()
                    self.status_var.set(f"读取完成 · {datetime.now():%H:%M:%S}")
                elif event == "error":
                    self._finish_busy()
                    self.status_var.set("读取失败")
                    messagebox.showerror("读取失败", str(payload), parent=self.root)
                elif event == "upload_complete":
                    self._handle_upload_complete(payload)
                elif event == "upload_error":
                    self._finish_busy()
                    self.status_var.set("抽卡记录上传失败")
                    messagebox.showerror("上传失败", str(payload), parent=self.root)
                elif event == "app_update_result":
                    update, silent = payload
                    self.update_checking = False
                    self.update_button.state(["!disabled"])
                    if update is None:
                        if not silent:
                            self.status_var.set(f"当前已是最新版 {APP_VERSION}")
                            messagebox.showinfo("检查更新", f"当前已是最新版 {APP_VERSION}。", parent=self.root)
                    else:
                        notes = f"\n\n{update.notes}" if update.notes else ""
                        if messagebox.askyesno(
                            "发现软件更新",
                            f"发现新版本 {update.version}，是否立即下载并安装？{notes}",
                            parent=self.root,
                        ):
                            self._download_app_update(update)
                elif event == "app_update_error":
                    error, silent = payload
                    self.update_checking = False
                    self.update_button.state(["!disabled"])
                    if not silent:
                        self.status_var.set("软件更新检查失败")
                        messagebox.showerror("检查更新失败", str(error), parent=self.root)
                elif event == "app_update_downloaded":
                    update, path = payload
                    self._finish_busy()
                    self.update_button.state(["!disabled"])
                    self.status_var.set(f"软件更新 {update.version} 下载完成")
                    if messagebox.askokcancel(
                        "更新就绪",
                        "更新包已下载并校验完成。\n\n软件将关闭，自动替换文件后重新启动。",
                        parent=self.root,
                    ):
                        try:
                            self._install_app_update(path)
                        except Exception as error:
                            self.status_var.set("更新程序启动失败")
                            messagebox.showerror("更新程序启动失败", str(error), parent=self.root)
                elif event == "app_update_download_error":
                    self._finish_busy()
                    self.update_button.state(["!disabled"])
                    self.status_var.set("软件下载失败")
                    messagebox.showerror("软件下载失败", str(payload), parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _finish_busy(self) -> None:
        self.busy = False
        self.uploading = False
        self.progress.stop()
        self.progress.grid_remove()
        self.refresh_button.state(["!disabled"])
        if not self.update_checking:
            self.update_button.state(["!disabled"])
        self._set_upload_button_state()

    def _apply_snapshot(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self.settings_archive_path.set(str(self._archive_path()))
        self.account_label.set(f"UID: {snapshot.uid}" if snapshot.uid else "旧归档尚未关联游戏 UID")
        self.copy_bind_button.state(["!disabled"] if snapshot.uid else ["disabled"])
        semantic_categories = self._semantic_gacha_categories()
        category_stats = {
            category: build_category_stat(semantic_categories.get(category, []))
            for category in GACHA_CATEGORY_ORDER
        }
        loaded_categories = sum(category in semantic_categories for category in GACHA_CATEGORY_ORDER)
        total_five_stars = sum(len(stat.five_stars) for stat in category_stats.values() if stat is not None)
        total_pulls = sum(stat.total_pulls for stat in category_stats.values() if stat is not None)
        self.metric_groups.set(str(loaded_categories))
        self.metric_pulls.set(str(total_pulls))
        self.metric_five_stars.set(str(total_five_stars))
        self.metric_rate.set(f"{total_five_stars / total_pulls * 100:.2f}%" if total_pulls else "-")
        self.metric_average.set(str(round(total_pulls / total_five_stars)) if total_five_stars else "-")
        self.metric_batches.set(str(len(snapshot.gacha)))

        timestamps = []
        for group in snapshot.gacha:
            try:
                timestamp = int(group.get("Time") or 0)
            except (TypeError, ValueError):
                continue
            if timestamp:
                timestamps.append(timestamp)
        if timestamps:
            date_range = (
                f"{datetime.fromtimestamp(min(timestamps)):%Y-%m-%d} 至 "
                f"{datetime.fromtimestamp(max(timestamps)):%Y-%m-%d}"
            )
        else:
            date_range = "暂无有效时间"
        self.settings_summary.set(
            f"{total_pulls} 抽 · {total_five_stars} 个五星\n"
            f"{date_range}\n归档批次 {len(snapshot.gacha)}"
        )
        self.gacha_sidebar_summary.set(f"{total_pulls} 抽 · {total_five_stars} 个五星\n已加载 {loaded_categories}/4 类卡池")
        self._refresh_gacha_sidebar()
        self._fill_five_star_stats()
        self._fill_gacha()

    @staticmethod
    def _format_time(value: Any) -> str:
        try:
            return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError, OverflowError):
            return "-"

    @staticmethod
    def _gacha_sort_key(group: dict) -> tuple[int, int]:
        def as_int(value: Any) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        return as_int(group.get("Time")), as_int(group.get("Gid"))

    def _reset_gacha_page(self) -> None:
        self._fill_gacha()

    def _change_gacha_page(self, delta: int) -> None:
        del delta

    def _resize_gacha_canvas(self, event: tk.Event) -> None:
        del event

    def _select_gacha_category(self, category: str) -> None:
        self.gacha_category_filter.set(category)
        self._refresh_gacha_sidebar()
        self._reset_gacha_page()

    def _refresh_gacha_sidebar(self) -> None:
        if not hasattr(self, "gacha_filter_sidebar"):
            return
        for child in self.gacha_filter_sidebar.winfo_children():
            child.destroy()
        semantic_categories = self._semantic_gacha_categories()
        selected = self.gacha_category_filter.get()
        filters = [("all", "全部卡池", None)]
        filters.extend(
            (category, GACHA_CATEGORY_NAMES[category], build_category_stat(semantic_categories.get(category, [])))
            for category in GACHA_CATEGORY_ORDER
        )
        for category, name, stat in filters:
            active = selected == category
            if category == "all":
                five_stars = sum(
                    len(pool.five_stars)
                    for groups in semantic_categories.values()
                    for pool in build_banner_stats_with_shared_pity(groups)
                )
                detail = f"{five_stars} 个五星记录"
            elif stat is None:
                detail = "尚未加载"
            else:
                detail = f"当前 {stat.current_pity} 抽 · 共 {stat.total_pulls} 抽"
            button = tk.Button(
                self.gacha_filter_sidebar,
                text=f"{name}\n{detail}",
                command=lambda value=category: self._select_gacha_category(value),
                background="#dce9f2" if active else "#edf3f7",
                activebackground="#d3e3ee",
                foreground=ACCENT_DARK if active else INK,
                font=("Microsoft YaHei UI", 9, "bold" if active else "normal"),
                justify="left",
                anchor="w",
                relief="flat",
                borderwidth=0,
                padx=10,
                pady=8,
                cursor="hand2",
            )
            button.pack(fill="x", pady=2)

    def _fill_gacha(self) -> None:
        if not hasattr(self, "gacha_rows_content"):
            return
        for child in self.gacha_rows_content.winfo_children():
            child.destroy()
        self.gacha_rows.clear()
        self.gacha_avatar_images.clear()
        if self.snapshot is None:
            return
        semantic_categories = self._semantic_gacha_categories()
        category_filter = self.gacha_category_filter.get()
        categories = (
            GACHA_CATEGORY_ORDER
            if category_filter == "all"
            else (category_filter,)
        )
        row = 0
        for category in categories:
            groups = semantic_categories.get(category, [])
            if not groups:
                continue
            pools = build_banner_stats_with_shared_pity(groups)
            spark_rewards = build_spark_rewards(groups, OFFICIAL_LIMITED_POOL_INFO) if category == CATEGORY_TRAVELER_LIMITED else {}
            pools_with_five_stars = [pool for pool in pools if pool.five_stars or pool.gid in spark_rewards]
            if not pools_with_five_stars:
                continue
            self._add_gacha_category_heading(row, category, len(pools_with_five_stars))
            row += 1
            for pool in pools_with_five_stars:
                self._add_five_star_banner_card(row, category, pool, reward=spark_rewards.get(pool.gid))
                row += 1
        if row:
            return
        tk.Label(
            self.gacha_rows_content,
            text="当前筛选范围内暂无五星记录",
            background=PANEL,
            foreground=MUTED,
            padx=12,
            pady=24,
        ).grid(row=0, column=0, sticky="w")

    def _add_gacha_category_heading(self, row: int, category: str, banner_count: int) -> None:
        heading = tk.Frame(self.gacha_rows_content, background=BG)
        heading.grid(row=row, column=0, sticky="ew", pady=(0, 7 if row == 0 else 8))
        tk.Label(
            heading,
            text=GACHA_CATEGORY_NAMES[category],
            background=BG,
            foreground=ACCENT_DARK,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        tk.Label(
            heading,
            text=f"{banner_count} 个含五星记录的卡池",
            background=BG,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(side="right")

    def _add_five_star_banner_card(self, row: int, category: str, pool: PoolStats, *, reward: SparkReward | None = None) -> None:
        color = POOL_COLORS[GACHA_CATEGORY_ORDER.index(category)]
        official_pool = OFFICIAL_LIMITED_POOL_INFO.get(pool.gid)
        standard_pool_name = {
            1: "旅人常驻招募",
            2: "秘纹常驻招募",
        }.get(pool.gid)
        card = tk.Frame(self.gacha_rows_content, background="#f4f8fb", highlightbackground=LINE, highlightthickness=1)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        card.grid_columnconfigure(0, weight=1)
        header = tk.Frame(card, background="#f4f8fb")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(13, 9))
        header.grid_columnconfigure(0, weight=1)
        title = tk.Frame(header, background="#f4f8fb")
        title.grid(row=0, column=0, sticky="w")
        tk.Label(
            title,
            text=official_pool[0] if official_pool is not None else standard_pool_name or f"卡池 {pool.gid}",
            background="#f4f8fb",
            foreground=INK,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title,
            text=(
                f"{official_pool[1]} - {official_pool[2]} · ID {pool.gid}"
                if official_pool is not None
                else f"{self._format_date(pool.start_time)} - {self._format_date(pool.end_time)}"
            ),
            background="#f4f8fb",
            foreground=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(3, 0))
        total_color = "#3f72cf"
        total = tk.Frame(header, background=total_color, width=72, height=56)
        total.grid(row=0, column=1, rowspan=2, sticky="e")
        total.grid_propagate(False)
        tk.Label(
            total,
            text=f"{pool.total_pulls}抽",
            background=total_color,
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(expand=True)
        tk.Frame(card, background=LINE, height=1).grid(row=1, column=0, sticky="ew", padx=16)
        hits = tk.Frame(card, background="#f4f8fb")
        hits.grid(row=2, column=0, sticky="ew", padx=16, pady=(9, 12))
        hits.grid_columnconfigure(0, weight=1)
        entries = insert_spark_rewards(pool.five_stars, {pool.gid: reward}) if reward is not None else pool.five_stars
        for index, pull in enumerate(entries):
            item_row = tk.Frame(hits, background="#f4f8fb")
            item_row.grid(row=index, column=0, sticky="ew", pady=4)
            item_row.grid_columnconfigure(1, weight=1)
            photo = self._square_avatar_photo(pull.item_id, pull.kind, color, size=64)
            self.gacha_avatar_images.append(photo)
            image_box = tk.Frame(item_row, background="#f4f8fb", width=64, height=64)
            image_box.grid(row=0, column=0, padx=(0, 10))
            image_box.grid_propagate(False)
            tk.Label(image_box, image=photo, background="#f4f8fb", borderwidth=0).place(x=0, y=0, width=64, height=64)
            if official_pool is not None:
                is_up = self._same_item_name(pull.name, official_pool[3])
                tk.Label(
                    image_box,
                    text="UP" if is_up else "歪",
                    background="#25282d" if is_up else "#c7514a",
                    foreground="#ffffff",
                    font=("Microsoft YaHei UI", 7, "bold"),
                    padx=4,
                    pady=1,
                ).place(relx=1.0, x=-2, y=2, anchor="ne")
            progress = tk.Canvas(item_row, height=44, background="#f4f8fb", highlightthickness=0, borderwidth=0)
            progress.grid(row=0, column=1, sticky="ew")

            def draw_progress(
                event: tk.Event,
                *,
                canvas=progress,
                entry=pull,
                pity_limit=GACHA_CATEGORY_PITY_LIMITS[category],
            ) -> None:
                self._draw_history_progress(canvas, event.width, entry, pity_limit)

            progress.bind("<Configure>", draw_progress)

    @classmethod
    def _draw_history_progress(cls, canvas: tk.Canvas, available_width: int, entry: FiveStarPull | SparkReward, pity_limit: int) -> None:
        available = max(160, min(720, available_width - 4))
        canvas.delete("all")
        is_spark = isinstance(entry, SparkReward)
        width = 80 if is_spark else cls._pity_bar_width(entry.pity, available, pity_limit)
        color = "#e7c65e" if is_spark else cls._pity_color(entry.pity)
        canvas.create_rectangle(0, 3, width, 41, fill=color, outline="")
        canvas.create_text(
            12, 22,
            text="井" if is_spark else f"{entry.pity} 抽",
            anchor="w", fill="#17212b", font=("Microsoft YaHei UI", 12, "bold"),
        )

    @staticmethod
    def _same_item_name(actual: str, expected: str) -> bool:
        translation = str.maketrans({"（": "(", "）": ")"})
        normalize = lambda value: "".join(str(value).translate(translation).split()).casefold()
        return normalize(actual) == normalize(expected)

    @staticmethod
    def _pity_color(pity: int) -> str:
        if pity <= 30:
            return "#50c69f"
        if pity <= 60:
            return "#e7c65e"
        return "#df654f"

    @staticmethod
    def _pity_bar_width(pity: int, available: int, pity_limit: int = 160) -> int:
        return max(80, int(available * min(max(pity, 1), pity_limit) / pity_limit))

    @classmethod
    def _draw_pity_bar(
        cls,
        canvas: tk.Canvas,
        available: int,
        pity: int,
        pity_limit: int,
        *,
        height: int,
        font_size: int,
    ) -> None:
        canvas.delete("all")
        track_width = max(160, available - 4)
        top = 2
        bottom = top + height
        fill_width = cls._pity_bar_width(pity, track_width, pity_limit)
        canvas.create_rectangle(0, top, track_width, bottom, fill="#dbe5ec", outline="")
        canvas.create_rectangle(0, top, fill_width, bottom, fill=cls._pity_color(pity), outline="")
        canvas.create_text(
            12,
            top + height // 2,
            text=f"{pity} 抽",
            anchor="w",
            fill="#17212b",
            font=("Microsoft YaHei UI", font_size, "bold"),
        )
        canvas.create_text(
            track_width - 10,
            top + height // 2,
            text=f"/{pity_limit}",
            anchor="e",
            fill="#526577",
            font=("Microsoft YaHei UI", max(8, font_size - 2)),
        )

    def _add_gacha_row(self, index: int, group: dict) -> None:
        ids = group.get("Ids", [])
        row = tk.Frame(self.gacha_rows_content, background=PANEL, highlightbackground=LINE, highlightthickness=1)
        row.grid(row=index, column=0, sticky="ew")
        self.gacha_rows_content.grid_columnconfigure(0, weight=1)
        widths = (170, 110, 80, 65)
        for column, width in enumerate(widths):
            row.grid_columnconfigure(column, minsize=width)
        row.grid_columnconfigure(4, weight=1)
        values = (
            self._format_time(group.get("Time")),
            group.get("Gid", "-"),
            "十连" if len(ids) > 1 else "单抽",
            len(ids),
        )
        for column, value in enumerate(values):
            tk.Label(
                row,
                text=str(value),
                background=PANEL,
                foreground=INK,
                font=("Microsoft YaHei UI", 9),
                anchor="w",
                padx=8,
                pady=7,
            ).grid(row=0, column=column, sticky="nsew")
        item_text = tk.Text(
            row,
            height=2 if len(ids) > 4 else 1,
            wrap="word",
            relief="flat",
            borderwidth=0,
            background=PANEL,
            foreground=INK,
            font=("Microsoft YaHei UI", 9),
            padx=8,
            pady=7,
            cursor="arrow",
        )
        item_text.tag_configure("five_star", foreground="#d87822")
        for position, item_id in enumerate(ids):
            item_text.insert("end", gacha_item_name(item_id), "five_star" if self._is_five_star_item(item_id) else ())
            if position + 1 < len(ids):
                item_text.insert("end", "、")
        item_text.configure(state="disabled")
        item_text.grid(row=0, column=4, sticky="nsew")
        self.gacha_rows[str(index)] = group

    def _add_gacha_list_row(self, index: int, group: dict) -> None:
        ids = group.get("Ids", [])
        category = classify_history_category([group])
        row = tk.Frame(
            self.gacha_rows_content,
            background=PANEL,
            highlightbackground=LINE,
            highlightthickness=1,
        )
        row.grid(row=index, column=0, sticky="ew", pady=(0, 6))
        self.gacha_rows_content.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(0, weight=1)
        top = tk.Frame(row, background=PANEL)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(9, 2))
        tk.Label(
            top,
            text=GACHA_CATEGORY_NAMES.get(category, "未知卡池"),
            background=PANEL,
            foreground=ACCENT_DARK,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="left")
        tk.Label(
            top,
            text=f"{self._format_time(group.get('Time'))} · ID {group.get('Gid', '-')} · {len(ids)} 抽",
            background=PANEL,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(side="right")
        self._add_gacha_items_text(row, ids, row=1, padx=12, pady=(2, 9))
        self.gacha_rows[str(index)] = group

    def _add_gacha_grid_card(self, index: int, group: dict, columns: int) -> None:
        ids = group.get("Ids", [])
        category = classify_history_category([group])
        card = tk.Frame(
            self.gacha_rows_content,
            background="#f4f8fb",
            highlightbackground=LINE,
            highlightthickness=1,
        )
        card.grid(
            row=index // columns,
            column=index % columns,
            sticky="nsew",
            padx=(0, 6) if index % columns < columns - 1 else 0,
            pady=(0, 6),
        )
        card.grid_columnconfigure(0, weight=1)
        tk.Label(
            card,
            text=GACHA_CATEGORY_NAMES.get(category, "未知卡池"),
            background="#f4f8fb",
            foreground=ACCENT_DARK,
            font=("Microsoft YaHei UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        tk.Label(
            card,
            text=f"{self._format_time(group.get('Time'))} · {len(ids)} 抽",
            background="#f4f8fb",
            foreground=MUTED,
            font=("Microsoft YaHei UI", 8),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=12)
        self._add_gacha_items_text(card, ids, row=2, padx=12, pady=(7, 10), background="#f4f8fb")
        self.gacha_rows[str(index)] = group

    def _add_gacha_items_text(
        self,
        parent: tk.Widget,
        ids: list[Any],
        *,
        row: int,
        padx: int,
        pady: tuple[int, int],
        background: str = PANEL,
    ) -> None:
        item_text = tk.Text(
            parent,
            height=max(1, min(3, (len(ids) + 3) // 4)),
            wrap="word",
            relief="flat",
            borderwidth=0,
            background=background,
            foreground=INK,
            font=("Microsoft YaHei UI", 9),
            padx=0,
            pady=0,
            cursor="arrow",
        )
        item_text.tag_configure("five_star", foreground="#d87822")
        for position, item_id in enumerate(ids):
            tag = "five_star" if self._is_five_star_item(item_id) else ()
            item_text.insert("end", gacha_item_name(item_id), tag)
            if position + 1 < len(ids):
                item_text.insert("end", "、")
        item_text.configure(state="disabled")
        item_text.grid(row=row, column=0, sticky="ew", padx=padx, pady=pady)

    @staticmethod
    def _is_five_star_item(value: Any) -> bool:
        try:
            return is_five_star_item(value)
        except (TypeError, ValueError):
            return False

    def _fill_emblems(self) -> None:
        if not hasattr(self, "emblem_tree"):
            return
        self.emblem_tree.delete(*self.emblem_tree.get_children())
        self.emblem_rows.clear()
        if self.snapshot is None:
            return
        needle = self.emblem_filter.get().strip().casefold()
        for emblem in self.snapshot.emblems:
            attrs = [format_random_attr(value) for value in table_values(emblem.get("tbRandomAttr"))]
            traveler = traveler_name(emblem.get("nCharId"))
            name = str(emblem.get("sName") or f"纹章 #{emblem.get('nGemId', '?')}")
            haystack = " ".join([traveler, name, str(emblem.get("nGemId", "")), *attrs]).casefold()
            if needle and needle not in haystack:
                continue
            iid = self.emblem_tree.insert(
                "",
                "end",
                values=(
                    traveler,
                    gem_type_name(emblem.get("nType")),
                    name,
                    "是" if emblem.get("bLock") else "否",
                    " · ".join(attrs) or "无随机词条",
                ),
            )
            self.emblem_rows[iid] = emblem

    def _show_gacha_detail(self, _event=None) -> None:
        selected = self.gacha_tree.selection()
        if not selected:
            return
        group = self.gacha_rows.get(selected[0])
        if not group:
            return
        names = "\n".join(f"{index}. {gacha_item_name(value)} ({value})" for index, value in enumerate(group.get("Ids", []), 1))
        messagebox.showinfo(
            "招募记录",
            f"时间：{self._format_time(group.get('Time'))}\n记录 ID：{group.get('Gid')}\n\n{names}",
            parent=self.root,
        )

    def _show_emblem_detail(self, _event=None) -> None:
        selected = self.emblem_tree.selection()
        emblem = self.emblem_rows.get(selected[0]) if selected else None
        if emblem is None:
            return
        attrs = "\n".join(f"  {format_random_attr(attr)}" for attr in table_values(emblem.get("tbRandomAttr"))) or "  无"
        potentials = json.dumps(emblem.get("tbPotentialAffix", []), ensure_ascii=False, indent=2)
        text = (
            f"{emblem.get('sName', '未命名纹章')}\n"
            f"旅人：{traveler_name(emblem.get('nCharId'))} ({emblem.get('nCharId')})\n"
            f"类型：{gem_type_name(emblem.get('nType'))}\n"
            f"纹章 ID：{emblem.get('nGemId')}\n"
            f"锁定：{'是' if emblem.get('bLock') else '否'}\n\n"
            f"随机词条\n{attrs}\n\n"
            f"潜能词条\n{potentials}"
        )
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def _open_exports(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(self.output_dir)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(self.output_dir)])

    def _copy_archive_path(self) -> None:
        archive_path = str(self._archive_path())
        self.root.clipboard_clear()
        self.root.clipboard_append(archive_path)
        self.status_var.set("归档路径已复制")

    def _backup_archive(self) -> None:
        archive_path = self._archive_path()
        if not archive_path.exists():
            messagebox.showinfo("创建备份", "尚未找到本地招募归档，请先刷新游戏数据。", parent=self.root)
            return
        backup_dir = self.output_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"{archive_path.stem}_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
        try:
            shutil.copy2(archive_path, target)
        except OSError as error:
            messagebox.showerror("备份失败", str(error), parent=self.root)
            return
        self.status_var.set(f"备份已创建：{target.name}")
        messagebox.showinfo("备份完成", f"已保存到：\n{target}", parent=self.root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="星塔旅人数据工具桌面界面")
    default_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    parser.add_argument("--output", type=Path, default=default_root / "exports")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output.resolve()
    if not args.smoke_test:
        try:
            if not ensure_administrator(["--output", str(output_dir)], relaunch_attempted=args.elevated):
                return 0
        except OSError as error:
            error_root = tk.Tk()
            error_root.withdraw()
            try:
                messagebox.showerror(
                    "管理员启动未完成",
                    f"未获得管理员权限，软件未启动。\n重新打开软件并确认 Windows 授权提示，或右键选择“以管理员身份运行”。\n\n{error}",
                    parent=error_root,
                )
            finally:
                error_root.destroy()
            return 1
    root = tk.Tk()
    StellaSoraApp(root, output_dir)
    if args.smoke_test:
        root.update_idletasks()
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
