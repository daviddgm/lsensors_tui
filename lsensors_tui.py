#!/usr/bin/env python3
"""
LSENSORS-TUI - Hardware Monitor & lm_sensors Console Interface
HWiNFO DOS / CPU-X styled TUI with persistent custom sensor labels and TXT/HTML reporting.
"""

import curses
import glob
import json
import os
import pathlib
import platform
import re
import time
from datetime import datetime


CONFIG_DIR = pathlib.Path.home() / ".config" / "lsensors_tui"
LABELS_FILE = CONFIG_DIR / "labels.json"

TABS = [
    ("All Sensors", "all"),
    ("Temperatures", "temp"),
    ("Voltages", "in"),
    ("Fans (RPM)", "fan"),
    ("Power / Curr", "power"),
    ("Chips & Info", "chips"),
]

FRIENDLY_DRIVERS = {
    "k10temp": "AMD CPU (k10temp)",
    "zenpower": "AMD CPU (zenpower)",
    "coretemp": "Intel CPU (coretemp)",
    "amdgpu": "AMD Radeon GPU (amdgpu)",
    "nouveau": "NVIDIA GPU (nouveau)",
    "nvme": "NVMe SSD Controller",
    "drivetemp": "SATA/SAS Drive Thermal",
    "it87": "ITE Super I/O (Mainboard)",
    "nct6775": "Nuvoton Super I/O (Mainboard)",
    "nct6776": "Nuvoton Super I/O (Mainboard)",
    "nct6779": "Nuvoton Super I/O (Mainboard)",
    "nct6791": "Nuvoton Super I/O (Mainboard)",
    "nct6798": "Nuvoton Super I/O (Mainboard)",
    "acpitz": "ACPI Thermal Zone",
    "r8169": "Realtek Ethernet Thermal",
    "iwlwifi_1": "Intel Wi-Fi Thermal",
}


def read_sysfs(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return None


def get_downloads_dir() -> pathlib.Path:
    dl = pathlib.Path.home() / "Downloads"
    dl.mkdir(parents=True, exist_ok=True)
    return dl


def load_custom_labels() -> dict:
    try:
        if LABELS_FILE.exists():
            return json.loads(LABELS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_custom_labels(labels: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_FILE.write_text(
        json.dumps(labels, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def resolve_hwmon_bus(hw_dir: str) -> str:
    """Identifies the underlying bus/PCI/ACPI device path for a hwmon node."""
    dev_link = os.path.join(hw_dir, "device")
    if not os.path.exists(dev_link):
        return "Virtual / Platform"
    real = os.path.realpath(dev_link)
    base = os.path.basename(real)
    if "/pci" in real:
        return f"PCI ({base})"
    if "/i2c" in real:
        return f"I2C/SMBus ({base})"
    if "/platform" in real:
        return f"ISA/Platform ({base})"
    if "/nvme" in real:
        return f"NVMe ({base})"
    return base


def scan_hwmon_sensors(custom_labels: dict, stats_cache: dict):
    """
    Scans /sys/class/hwmon/hwmon* for all sensor types:
    - temp*_input (milli-Celsius -> °C)
    - in*_input (milli-Volts -> V)
    - fan*_input (RPM)
    - power*_average / power*_input (micro-Watts -> W)
    - curr*_input (milli-Amps -> A)
    - freq*_input (Hz -> MHz)
    """
    chips = []
    all_sensors = []

    hw_dirs = sorted(
        glob.glob("/sys/class/hwmon/hwmon*"),
        key=lambda p: int(re.search(r"hwmon(\d+)", p).group(1))
    )

    for hw_dir in hw_dirs:
        hw_node = os.path.basename(hw_dir)
        driver = read_sysfs(os.path.join(hw_dir, "name")) or hw_node
        chip_title = FRIENDLY_DRIVERS.get(driver, driver)
        bus_info = resolve_hwmon_bus(hw_dir)

        chip_sensors = []

        # 1. Temperatures (temp*_input)
        for path in sorted(glob.glob(os.path.join(hw_dir, "temp*_input")),
                           key=lambda p: int(re.search(r"temp(\d+)_input", p).group(1))):
            raw = read_sysfs(path)
            if not raw or not raw.lstrip("-").isdigit():
                continue
            val = round(int(raw) / 1000.0, 1)
            if val <= -50.0 or val >= 160.0:
                continue

            idx = re.search(r"temp(\d+)_input", path).group(1)
            default_lbl = read_sysfs(os.path.join(hw_dir, f"temp{idx}_label")) or f"Temp #{idx}"
            crit_raw = read_sysfs(os.path.join(hw_dir, f"temp{idx}_crit"))
            max_raw = read_sysfs(os.path.join(hw_dir, f"temp{idx}_max"))

            crit_val = round(int(crit_raw) / 1000.0, 1) if crit_raw and crit_raw.lstrip("-").isdigit() else None
            max_val = round(int(max_raw) / 1000.0, 1) if max_raw and max_raw.lstrip("-").isdigit() else None

            limit_str = "-"
            if crit_val is not None:
                limit_str = f"Crit {crit_val:.1f}°C"
            elif max_val is not None:
                limit_str = f"High {max_val:.1f}°C"

            chip_sensors.append({
                "key": f"{driver}:temp{idx}",
                "hwmon": hw_node,
                "driver": driver,
                "chip": chip_title,
                "channel": f"temp{idx}",
                "category": "temp",
                "default_label": default_lbl,
                "value": val,
                "unit": "°C",
                "fmt": "{:.1f}",
                "limit_str": limit_str,
                "crit": crit_val,
                "max_limit": max_val,
            })

        # 2. Voltages (in*_input)
        for path in sorted(glob.glob(os.path.join(hw_dir, "in*_input")),
                           key=lambda p: int(re.search(r"in(\d+)_input", p).group(1))):
            raw = read_sysfs(path)
            if not raw or not raw.lstrip("-").isdigit():
                continue
            val = round(int(raw) / 1000.0, 3)

            idx = re.search(r"in(\d+)_input", path).group(1)
            default_lbl = read_sysfs(os.path.join(hw_dir, f"in{idx}_label")) or f"in{idx} (Voltage)"
            min_raw = read_sysfs(os.path.join(hw_dir, f"in{idx}_min"))
            max_raw = read_sysfs(os.path.join(hw_dir, f"in{idx}_max"))

            limit_parts = []
            if min_raw and min_raw.lstrip("-").isdigit():
                limit_parts.append(f"{int(min_raw)/1000.0:.2f}V")
            if max_raw and max_raw.lstrip("-").isdigit():
                limit_parts.append(f"{int(max_raw)/1000.0:.2f}V")
            limit_str = " .. ".join(limit_parts) if limit_parts else "-"

            chip_sensors.append({
                "key": f"{driver}:in{idx}",
                "hwmon": hw_node,
                "driver": driver,
                "chip": chip_title,
                "channel": f"in{idx}",
                "category": "in",
                "default_label": default_lbl,
                "value": val,
                "unit": "V",
                "fmt": "{:.3f}",
                "limit_str": limit_str,
                "crit": None,
                "max_limit": None,
            })

        # 3. Fans (fan*_input)
        for path in sorted(glob.glob(os.path.join(hw_dir, "fan*_input")),
                           key=lambda p: int(re.search(r"fan(\d+)_input", p).group(1))):
            raw = read_sysfs(path)
            if not raw or not raw.isdigit():
                continue
            val = float(int(raw))

            idx = re.search(r"fan(\d+)_input", path).group(1)
            default_lbl = read_sysfs(os.path.join(hw_dir, f"fan{idx}_label")) or f"Fan #{idx}"
            min_raw = read_sysfs(os.path.join(hw_dir, f"fan{idx}_min"))
            limit_str = f"Min {min_raw} RPM" if min_raw and min_raw.isdigit() else "-"

            chip_sensors.append({
                "key": f"{driver}:fan{idx}",
                "hwmon": hw_node,
                "driver": driver,
                "chip": chip_title,
                "channel": f"fan{idx}",
                "category": "fan",
                "default_label": default_lbl,
                "value": val,
                "unit": "RPM",
                "fmt": "{:.0f}",
                "limit_str": limit_str,
                "crit": None,
                "max_limit": None,
            })

        # 4. Power (power*_average or power*_input)
        power_indices = set()
        for p in glob.glob(os.path.join(hw_dir, "power*_*")):
            m = re.search(r"power(\d+)_(?:average|input)", p)
            if m:
                power_indices.add(int(m.group(1)))

        for idx in sorted(power_indices):
            raw = (
                read_sysfs(os.path.join(hw_dir, f"power{idx}_average"))
                or read_sysfs(os.path.join(hw_dir, f"power{idx}_input"))
            )
            if not raw or not raw.isdigit():
                continue
            val = round(int(raw) / 1_000_000.0, 2)
            default_lbl = read_sysfs(os.path.join(hw_dir, f"power{idx}_label")) or f"Power #{idx}"
            cap_raw = read_sysfs(os.path.join(hw_dir, f"power{idx}_cap"))
            limit_str = f"Cap {int(cap_raw)/1_000_000.0:.1f}W" if cap_raw and cap_raw.isdigit() else "-"

            chip_sensors.append({
                "key": f"{driver}:power{idx}",
                "hwmon": hw_node,
                "driver": driver,
                "chip": chip_title,
                "channel": f"power{idx}",
                "category": "power",
                "default_label": default_lbl,
                "value": val,
                "unit": "W",
                "fmt": "{:.2f}",
                "limit_str": limit_str,
                "crit": None,
                "max_limit": None,
            })

        # 5. Current (curr*_input)
        for path in sorted(glob.glob(os.path.join(hw_dir, "curr*_input")),
                           key=lambda p: int(re.search(r"curr(\d+)_input", p).group(1))):
            raw = read_sysfs(path)
            if not raw or not raw.lstrip("-").isdigit():
                continue
            val = round(int(raw) / 1000.0, 2)
            idx = re.search(r"curr(\d+)_input", path).group(1)
            default_lbl = read_sysfs(os.path.join(hw_dir, f"curr{idx}_label")) or f"Current #{idx}"

            chip_sensors.append({
                "key": f"{driver}:curr{idx}",
                "hwmon": hw_node,
                "driver": driver,
                "chip": chip_title,
                "channel": f"curr{idx}",
                "category": "power",
                "default_label": default_lbl,
                "value": val,
                "unit": "A",
                "fmt": "{:.2f}",
                "limit_str": "-",
                "crit": None,
                "max_limit": None,
            })

        # 6. Frequency (freq*_input)
        for path in sorted(glob.glob(os.path.join(hw_dir, "freq*_input")),
                           key=lambda p: int(re.search(r"freq(\d+)_input", p).group(1))):
            raw = read_sysfs(path)
            if not raw or not raw.isdigit():
                continue
            val = round(int(raw) / 1_000_000.0, 0)
            idx = re.search(r"freq(\d+)_input", path).group(1)
            default_lbl = read_sysfs(os.path.join(hw_dir, f"freq{idx}_label")) or f"Clock #{idx}"

            chip_sensors.append({
                "key": f"{driver}:freq{idx}",
                "hwmon": hw_node,
                "driver": driver,
                "chip": chip_title,
                "channel": f"freq{idx}",
                "category": "power",
                "default_label": default_lbl,
                "value": val,
                "unit": "MHz",
                "fmt": "{:.0f}",
                "limit_str": "-",
                "crit": None,
                "max_limit": None,
            })

        # Aplica títulos personalizados e atualiza Min/Max da sessão
        for s in chip_sensors:
            k = s["key"]
            custom = custom_labels.get(k)
            s["label"] = custom if custom else s["default_label"]
            s["is_custom"] = bool(custom)

            st = stats_cache.get(k)
            if st is None:
                st = {"min": s["value"], "max": s["value"]}
                stats_cache[k] = st
            else:
                if s["value"] < st["min"]:
                    st["min"] = s["value"]
                if s["value"] > st["max"]:
                    st["max"] = s["value"]
            s["min"] = st["min"]
            s["max"] = st["max"]

        if chip_sensors:
            chips.append({
                "hwmon": hw_node,
                "driver": driver,
                "title": chip_title,
                "bus": bus_info,
                "count": len(chip_sensors),
            })
            all_sensors.extend(chip_sensors)

    # Ordena chips por relevância (CPU -> GPU -> Storage -> Mainboard -> Outros)
    priority = {"k10temp": 0, "zenpower": 0, "coretemp": 0, "amdgpu": 1, "nouveau": 1, "nvme": 2}
    chips.sort(key=lambda c: (priority.get(c["driver"], 5), c["hwmon"]))
    all_sensors.sort(key=lambda s: (priority.get(s["driver"], 5), s["hwmon"], s["category"], s["channel"]))

    return chips, all_sensors


def build_sensors_txt_report(chips: list, sensors: list) -> str:
    hostname = platform.node()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kernel = f"{platform.system()} {platform.release()}"

    lines = [
        "=========================================================================================",
        "  LSENSORS-TUI — HARDWARE MONITOR & LM_SENSORS REPORT",
        "=========================================================================================",
        f"Generated : {now_str}",
        f"Hostname  : {hostname}",
        f"Kernel    : {kernel}",
        f"Chips     : {len(chips)} active hwmon adapters ({len(sensors)} total sensors)",
        "",
    ]

    grouped = {}
    for s in sensors:
        grouped.setdefault((s["hwmon"], s["chip"], s["driver"]), []).append(s)

    for (hwmon, chip_title, driver), items in grouped.items():
        lines.append("-----------------------------------------------------------------------------------------")
        lines.append(f"  [{hwmon}] {chip_title} (driver: {driver})")
        lines.append("-----------------------------------------------------------------------------------------")
        lines.append(f"  {'Sensor Title':<30} {'Type':<6} {'Current':>11} {'Min':>11} {'Max':>11}  {'Limits'}")
        lines.append(f"  {'-'*30} {'-'*6} {'-'*11} {'-'*11} {'-'*11}  {'-'*14}")
        for s in items:
            cur_s = f"{s['fmt'].format(s['value'])} {s['unit']}"
            min_s = f"{s['fmt'].format(s['min'])} {s['unit']}"
            max_s = f"{s['fmt'].format(s['max'])} {s['unit']}"
            tag = "*" if s["is_custom"] else " "
            lines.append(
                f" {tag}{s['label']:<30} {s['category'].upper():<6} {cur_s:>11} {min_s:>11} {max_s:>11}  {s['limit_str']}"
            )
        lines.append("")

    lines.append("* Indicates custom user-defined sensor label.")
    return "\n".join(lines)


def build_sensors_html_report(chips: list, sensors: list) -> str:
    hostname = platform.node()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kernel = f"{platform.system()} {platform.release()}"

    grouped = {}
    for s in sensors:
        grouped.setdefault((s["hwmon"], s["chip"], s["driver"]), []).append(s)

    sections_html = ""
    for (hwmon, chip_title, driver), items in grouped.items():
        rows = ""
        for s in items:
            cur_s = f"{s['fmt'].format(s['value'])} {s['unit']}"
            min_s = f"{s['fmt'].format(s['min'])} {s['unit']}"
            max_s = f"{s['fmt'].format(s['max'])} {s['unit']}"
            badge = '<span class="badge">Custom</span>' if s["is_custom"] else ""
            val_cls = "val"
            if s["category"] == "temp":
                if s["value"] >= 85:
                    val_cls += " crit"
                elif s["value"] >= 70:
                    val_cls += " warn"
            rows += f"""
            <tr>
                <td><strong>{s['label']}</strong> {badge}<br><small class="muted">{s['channel']} ({s['default_label']})</small></td>
                <td><span class="cat">{s['category'].upper()}</span></td>
                <td class="{val_cls}">{cur_s}</td>
                <td class="num">{min_s}</td>
                <td class="num">{max_s}</td>
                <td class="muted">{s['limit_str']}</td>
            </tr>"""

        sections_html += f"""
        <div class="card">
            <h2>{chip_title} <span class="chip-meta">({hwmon} • driver: {driver})</span></h2>
            <table>
                <thead>
                    <tr>
                        <th>Sensor Title</th>
                        <th>Type</th>
                        <th style="text-align:right;">Current</th>
                        <th style="text-align:right;">Session Min</th>
                        <th style="text-align:right;">Session Max</th>
                        <th>Hardware Limits</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Hardware Sensors Report - {hostname}</title>
<style>
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #eef1f5; color: #1f2328; margin: 0; padding: 24px; }}
    .container {{ max-width: 920px; margin: auto; background: #fff; border: 1px solid #d0d7de; border-radius: 6px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(90deg, #0b3d91, #1565c0); color: #fff; padding: 18px 24px; display: flex; justify-content: space-between; align-items: center; }}
    .header h1 {{ margin: 0; font-size: 20px; }}
    .meta {{ font-size: 12px; text-align: right; opacity: 0.92; }}
    .content {{ padding: 18px 24px; }}
    .card {{ border: 1px solid #d8dee4; border-radius: 5px; margin-bottom: 16px; overflow: hidden; }}
    h2 {{ margin: 0; padding: 10px 14px; font-size: 14px; background: #f6f8fa; border-bottom: 1px solid #d8dee4; color: #0b3d91; }}
    .chip-meta {{ font-weight: normal; font-size: 12px; color: #57606a; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{ padding: 7px 12px; border-bottom: 1px solid #eaeef2; text-align: left; }}
    th {{ background: #fbfcfd; color: #57606a; font-size: 11px; text-transform: uppercase; }}
    tr:last-child td {{ border-bottom: none; }}
    .num {{ text-align: right; font-family: monospace; }}
    .val {{ text-align: right; font-family: monospace; font-weight: bold; color: #0969da; font-size: 13px; }}
    .val.warn {{ color: #bf8700; }}
    .val.crit {{ color: #cf222e; }}
    .muted {{ color: #6e7781; font-size: 11px; }}
    .cat {{ background: #ddf4ff; color: #0969da; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: bold; }}
    .badge {{ background: #fff8c5; color: #9a6700; border: 1px solid #d4a72c; padding: 1px 5px; border-radius: 3px; font-size: 10px; margin-left: 6px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1>LSENSORS-TUI — Hardware Telemetry Report</h1>
            <div style="font-size:12px; margin-top:4px;">{kernel}</div>
        </div>
        <div class="meta">
            <div>Host: <strong>{hostname}</strong></div>
            <div>{now_str}</div>
        </div>
    </div>
    <div class="content">
        {sections_html or '<p>No HWMON sensors detected.</p>'}
    </div>
</div>
</body>
</html>"""


class LSensorsTUI:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.current_tab = 0
        self.dos_theme = True

        self.custom_labels = load_custom_labels()
        self.stats_cache = {}
        self.chips, self.sensors = scan_hwmon_sensors(self.custom_labels, self.stats_cache)

        self.selected_idx = 0
        self.scroll_offset = 0
        self.last_poll = time.time()
        self.running = True

        self.toast_msg = ""
        self.toast_expire = 0.0
        self.toast_err = False

        self.init_colors()

    def init_colors(self):
        curses.start_color()
        curses.use_default_colors()

        if self.dos_theme:
            bg = curses.COLOR_BLUE
            curses.init_pair(1, curses.COLOR_WHITE, bg)                # Texto normal
            curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_CYAN)  # Header / Aba ativa
            curses.init_pair(3, curses.COLOR_YELLOW, bg)               # Títulos / Chip headers
            curses.init_pair(4, curses.COLOR_CYAN, bg)                 # Bordas / Labels
            curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE) # Linha selecionada / Input
            curses.init_pair(6, curses.COLOR_GREEN, bg)                # Leitura OK
            curses.init_pair(7, curses.COLOR_YELLOW, bg)               # Alerta / Custom tag
            curses.init_pair(8, curses.COLOR_RED, bg)                  # Crítico / Erro
            curses.init_pair(9, curses.COLOR_BLACK, curses.COLOR_CYAN)  # Rodapé
        else:
            bg = curses.COLOR_BLACK
            curses.init_pair(1, curses.COLOR_WHITE, bg)
            curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
            curses.init_pair(3, curses.COLOR_MAGENTA, bg)
            curses.init_pair(4, curses.COLOR_CYAN, bg)
            curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(6, curses.COLOR_GREEN, bg)
            curses.init_pair(7, curses.COLOR_YELLOW, bg)
            curses.init_pair(8, curses.COLOR_RED, bg)
            curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_MAGENTA)

        self.stdscr.bkgd(' ', curses.color_pair(1))

    def show_toast(self, msg: str, is_error: bool = False, duration: float = 3.5):
        self.toast_msg = msg
        self.toast_err = is_error
        self.toast_expire = time.time() + duration

    def safe_addstr(self, y: int, x: int, text: str, attr=0, max_w: int = None):
        h, w = self.stdscr.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        limit = w - x if max_w is None else min(max_w, w - x)
        if limit <= 0:
            return
        try:
            self.stdscr.addnstr(y, x, text, limit, attr)
        except curses.error:
            pass

    def draw_box(self, y: int, x: int, h: int, w: int, title: str = ""):
        max_h, max_w = self.stdscr.getmaxyx()
        if h < 2 or w < 4 or y >= max_h or x >= max_w:
            return
        w = min(w, max_w - x)
        h = min(h, max_h - y)

        b_attr = curses.color_pair(4)
        t_attr = curses.color_pair(3) | curses.A_BOLD

        self.safe_addstr(y, x, "┌" + "─" * (w - 2) + "┐", b_attr)
        for r in range(1, h - 1):
            self.safe_addstr(y + r, x, "│", b_attr)
            self.safe_addstr(y + r, x + w - 1, "│", b_attr)
        self.safe_addstr(y + h - 1, x, "└" + "─" * (w - 2) + "┘", b_attr)

        if title and w > 6:
            self.safe_addstr(y, x + 2, f" {title[:w - 6]} ", t_attr)

    def get_filtered_sensors(self) -> list:
        _, cat = TABS[self.current_tab]
        if cat == "all":
            return self.sensors
        return [s for s in self.sensors if s["category"] == cat]

    def draw_header_and_tabs(self):
        _, w = self.stdscr.getmaxyx()
        title = " LSENSORS-TUI — Linux Hardware Monitor & Sensor Manager "
        theme_tag = "[DOS-Blue]" if self.dos_theme else "[LHWDI-Dark]"
        bar = f"{title:<{max(1, w - len(theme_tag) - 1)}}{theme_tag} "
        self.safe_addstr(0, 0, bar, curses.color_pair(2) | curses.A_BOLD)

        x = 1
        for idx, (label, cat) in enumerate(TABS):
            if cat == "all":
                cnt = len(self.sensors)
            elif cat == "chips":
                cnt = len(self.chips)
            else:
                cnt = sum(1 for s in self.sensors if s["category"] == cat)

            tag = f" {label} ({cnt}) "
            if x + len(tag) >= w - 1:
                break
            attr = (curses.color_pair(2) | curses.A_BOLD) if idx == self.current_tab else curses.color_pair(4)
            self.safe_addstr(1, x, tag, attr)
            x += len(tag) + 1

        self.safe_addstr(2, 0, "═" * w, curses.color_pair(4))

    def draw_footer(self):
        h, w = self.stdscr.getmaxyx()
        _, cat = TABS[self.current_tab]
        if cat == "chips":
            keys = "[←/→]Tab [↑/↓]Scroll [T]Save TXT [H]Save HTML [C]Theme [Q]Quit"
        else:
            keys = "[↑/↓]Select [E/Enter]Rename [D]Default Name [R]Reset Min/Max [T]TXT [H]HTML [Q]Quit"

        self.safe_addstr(h - 2, 0, "─" * w, curses.color_pair(4))
        host = platform.node()
        footer = f" Host: {host} │ {keys}"
        self.safe_addstr(h - 1, 0, f"{footer:<{w}}", curses.color_pair(9) | curses.A_BOLD)

        if self.toast_msg and time.time() < self.toast_expire:
            t_attr = (curses.color_pair(8) if self.toast_err else curses.color_pair(6)) | curses.A_BOLD | curses.A_REVERSE
            msg = f" {self.toast_msg} "
            tx = max(1, (w - len(msg)) // 2)
            self.safe_addstr(h - 3, tx, msg, t_attr)

    def draw_sensors_table(self, top: int, bottom: int, w: int):
        items = self.get_filtered_sensors()
        tab_name, _ = TABS[self.current_tab]
        box_h = bottom - top
        self.draw_box(top, 1, box_h, w - 2, f"{tab_name} ({len(items)} readings) — Press [E] to rename selected sensor")

        if not items:
            self.safe_addstr(top + 2, 3, "No sensors detected in this category.", curses.color_pair(1))
            return

        self.selected_idx = max(0, min(self.selected_idx, len(items) - 1))

        # Cabeçalho da tabela
        hdr_y = top + 1
        inner_w = w - 4
        # Layout dinâmico das colunas
        title_w = max(20, inner_w - 64)
        hdr = (
            f" {'Sensor Title':<{title_w}} {'Adapter / Driver':<22} "
            f"{'Current':>10} {'Min':>10} {'Max':>10}  {'Limits'}"
        )
        self.safe_addstr(hdr_y, 2, hdr, curses.color_pair(3) | curses.A_BOLD, max_w=inner_w)
        self.safe_addstr(hdr_y + 1, 2, "─" * inner_w, curses.color_pair(4))

        list_top = hdr_y + 2
        rows_avail = max(1, (top + box_h - 1) - list_top)

        # Ajusta scroll para manter o item selecionado visível
        if self.selected_idx < self.scroll_offset:
            self.scroll_offset = self.selected_idx
        elif self.selected_idx >= self.scroll_offset + rows_avail:
            self.scroll_offset = self.selected_idx - rows_avail + 1

        visible = items[self.scroll_offset:self.scroll_offset + rows_avail]

        for row_i, s in enumerate(visible):
            abs_idx = self.scroll_offset + row_i
            y = list_top + row_i
            is_sel = (abs_idx == self.selected_idx)

            mark = "*" if s["is_custom"] else " "
            lbl_txt = f"{mark}{s['label']}"
            if len(lbl_txt) > title_w:
                lbl_txt = lbl_txt[:title_w - 1] + "…"

            chip_txt = f"{s['driver']} ({s['channel']})"
            if len(chip_txt) > 22:
                chip_txt = chip_txt[:21] + "…"

            cur_s = f"{s['fmt'].format(s['value'])} {s['unit']}"
            min_s = f"{s['fmt'].format(s['min'])} {s['unit']}"
            max_s = f"{s['fmt'].format(s['max'])} {s['unit']}"
            lim_s = s["limit_str"]

            line = (
                f" {lbl_txt:<{title_w}} {chip_txt:<22} "
                f"{cur_s:>10} {min_s:>10} {max_s:>10}  {lim_s}"
            )

            if is_sel:
                self.safe_addstr(y, 2, f"{line:<{inner_w}}", curses.color_pair(5) | curses.A_BOLD, max_w=inner_w)
            else:
                # Colore apenas o valor atual conforme criticidade
                base_attr = curses.color_pair(7) if s["is_custom"] else curses.color_pair(1)
                self.safe_addstr(y, 2, f" {lbl_txt:<{title_w}} {chip_txt:<22} ", base_attr, max_w=inner_w)

                val_attr = curses.color_pair(6) | curses.A_BOLD
                if s["category"] == "temp":
                    if s["value"] >= 85.0:
                        val_attr = curses.color_pair(8) | curses.A_BOLD
                    elif s["value"] >= 70.0:
                        val_attr = curses.color_pair(7) | curses.A_BOLD

                val_x = 2 + 1 + title_w + 1 + 22 + 1
                self.safe_addstr(y, val_x, f"{cur_s:>10}", val_attr, max_w=inner_w - (val_x - 2))
                rest_x = val_x + 10
                self.safe_addstr(y, rest_x, f" {min_s:>10} {max_s:>10}  {lim_s}", curses.color_pair(4), max_w=inner_w - (rest_x - 2))

    def draw_chips_tab(self, top: int, bottom: int, w: int):
        box_h = bottom - top
        self.draw_box(top, 1, box_h, w - 2, f"Detected HWMON Adapters ({len(self.chips)} chips) & Config Storage")

        inner_w = w - 6
        self.safe_addstr(top + 1, 3, f"Custom Labels File : {LABELS_FILE} ({len(self.custom_labels)} saved)", curses.color_pair(3) | curses.A_BOLD, max_w=inner_w)
        self.safe_addstr(top + 2, 3, "Tip: Sensors marked with '*' use your persistent custom titles.", curses.color_pair(4), max_w=inner_w)

        hdr_y = top + 4
        hdr = f" {'Node':<10} {'Driver':<14} {'Adapter Description':<32} {'Bus / Path':<24} {'Sensors'}"
        self.safe_addstr(hdr_y, 2, hdr, curses.color_pair(3) | curses.A_BOLD, max_w=w - 4)
        self.safe_addstr(hdr_y + 1, 2, "─" * (w - 4), curses.color_pair(4))

        rows_avail = max(1, (top + box_h - 1) - (hdr_y + 2))
        self.scroll_offset = max(0, min(self.scroll_offset, max(0, len(self.chips) - rows_avail)))
        visible = self.chips[self.scroll_offset:self.scroll_offset + rows_avail]

        for idx, c in enumerate(visible):
            y = hdr_y + 2 + idx
            line = f" {c['hwmon']:<10} {c['driver']:<14} {c['title']:<32} {c['bus']:<24} {c['count']:>4}"
            self.safe_addstr(y, 2, line, curses.color_pair(1), max_w=w - 4)

    def prompt_rename_sensor(self):
        items = self.get_filtered_sensors()
        if not items or TABS[self.current_tab][1] == "chips":
            return

        sensor = items[self.selected_idx]
        h, w = self.stdscr.getmaxyx()
        dlg_w = min(68, w - 4)
        dlg_h = 8
        dy = max(2, (h - dlg_h) // 2)
        dx = max(2, (w - dlg_w) // 2)

        # Desenha janela modal sobre o conteúdo
        for r in range(dlg_h):
            self.safe_addstr(dy + r, dx, " " * dlg_w, curses.color_pair(1))
        self.draw_box(dy, dx, dlg_h, dlg_w, f"Rename Sensor ({sensor['key']})")

        self.safe_addstr(dy + 2, dx + 2, f"Original Name : {sensor['default_label']}", curses.color_pair(4), max_w=dlg_w - 4)
        self.safe_addstr(dy + 3, dx + 2, "New Title     : (Enter=Save, Esc=Cancel, Empty=Restore Default)", curses.color_pair(1), max_w=dlg_w - 4)

        input_w = dlg_w - 6
        buf = list(sensor["label"])

        self.stdscr.nodelay(False)
        curses.curs_set(1)

        try:
            while True:
                txt = "".join(buf)
                disp = txt[-(input_w - 2):] if len(txt) >= input_w - 1 else txt
                self.safe_addstr(dy + 5, dx + 3, f"{disp:<{input_w}}", curses.color_pair(5) | curses.A_BOLD, max_w=input_w)
                self.stdscr.move(dy + 5, min(dx + 3 + len(disp), dx + 3 + input_w - 1))
                self.stdscr.refresh()

                ch = self.stdscr.getch()
                if ch in (10, 13, curses.KEY_ENTER):
                    new_title = "".join(buf).strip()
                    if not new_title or new_title == sensor["default_label"]:
                        self.custom_labels.pop(sensor["key"], None)
                        save_custom_labels(self.custom_labels)
                        self.show_toast(f"Restored default label: {sensor['default_label']}")
                    else:
                        self.custom_labels[sensor["key"]] = new_title
                        save_custom_labels(self.custom_labels)
                        self.show_toast(f"Saved label: '{new_title}'")
                    self.chips, self.sensors = scan_hwmon_sensors(self.custom_labels, self.stats_cache)
                    break
                elif ch == 27:  # Esc
                    break
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if buf:
                        buf.pop()
                elif 32 <= ch <= 126 or ch >= 160:
                    if len(buf) < 48:
                        buf.append(chr(ch))
        finally:
            curses.curs_set(0)
            self.stdscr.nodelay(True)

    def restore_default_label(self):
        items = self.get_filtered_sensors()
        if not items or TABS[self.current_tab][1] == "chips":
            return
        sensor = items[self.selected_idx]
        if sensor["key"] in self.custom_labels:
            self.custom_labels.pop(sensor["key"], None)
            save_custom_labels(self.custom_labels)
            self.chips, self.sensors = scan_hwmon_sensors(self.custom_labels, self.stats_cache)
            self.show_toast(f"Restored default: {sensor['default_label']}")
        else:
            self.show_toast("Sensor already uses its default driver label.")

    def export_report(self, fmt: str):
        try:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            hostname = platform.node()
            filename = f"lsensors-{hostname}-{ts}.{fmt}"
            target = get_downloads_dir() / filename
            content = (
                build_sensors_txt_report(self.chips, self.sensors)
                if fmt == "txt"
                else build_sensors_html_report(self.chips, self.sensors)
            )
            target.write_text(content, encoding="utf-8")
            self.show_toast(f"Report saved to ~/Downloads/{filename}")
        except Exception as exc:
            self.show_toast(f"Export error: {exc}", is_error=True)

    def handle_input(self, ch: int):
        if ch == -1:
            return
        if ch in (ord('q'), ord('Q'), 27):
            self.running = False
        elif ch in (curses.KEY_RIGHT, 9):
            self.current_tab = (self.current_tab + 1) % len(TABS)
            self.selected_idx = 0
            self.scroll_offset = 0
        elif ch in (curses.KEY_LEFT, curses.KEY_BTAB):
            self.current_tab = (self.current_tab - 1) % len(TABS)
            self.selected_idx = 0
            self.scroll_offset = 0
        elif ord('1') <= ch <= ord('6'):
            self.current_tab = ch - ord('1')
            self.selected_idx = 0
            self.scroll_offset = 0
        elif ch == curses.KEY_DOWN:
            if TABS[self.current_tab][1] == "chips":
                self.scroll_offset += 1
            else:
                self.selected_idx += 1
        elif ch == curses.KEY_UP:
            if TABS[self.current_tab][1] == "chips":
                self.scroll_offset = max(0, self.scroll_offset - 1)
            else:
                self.selected_idx = max(0, self.selected_idx - 1)
        elif ch == curses.KEY_NPAGE:
            if TABS[self.current_tab][1] == "chips":
                self.scroll_offset += 10
            else:
                self.selected_idx += 10
        elif ch == curses.KEY_PPAGE:
            if TABS[self.current_tab][1] == "chips":
                self.scroll_offset = max(0, self.scroll_offset - 10)
            else:
                self.selected_idx = max(0, self.selected_idx - 10)
        elif ch in (ord('e'), ord('E'), 10, 13, curses.KEY_ENTER):
            self.prompt_rename_sensor()
        elif ch in (ord('d'), ord('D')):
            self.restore_default_label()
        elif ch in (ord('r'), ord('R')):
            self.stats_cache.clear()
            self.chips, self.sensors = scan_hwmon_sensors(self.custom_labels, self.stats_cache)
            self.show_toast("Session Min/Max readings reset.")
        elif ch in (ord('t'), ord('T')):
            self.export_report("txt")
        elif ch in (ord('h'), ord('H')):
            self.export_report("html")
        elif ch in (ord('c'), ord('C')):
            self.dos_theme = not self.dos_theme
            self.init_colors()
            self.show_toast("Theme: " + ("HWiNFO DOS Blue" if self.dos_theme else "LHWDI Dark"))

    def run(self):
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)

        while self.running:
            now = time.time()
            if now - self.last_poll >= 1.0:
                self.chips, self.sensors = scan_hwmon_sensors(self.custom_labels, self.stats_cache)
                self.last_poll = now

            self.stdscr.erase()
            h, w = self.stdscr.getmaxyx()

            if h < 16 or w < 72:
                self.safe_addstr(1, 2, f"Terminal too small ({w}x{h}). Resize to at least 72x16.", curses.color_pair(8) | curses.A_BOLD)
            else:
                self.draw_header_and_tabs()
                top = 3
                bottom = h - 2
                if TABS[self.current_tab][1] == "chips":
                    self.draw_chips_tab(top, bottom, w)
                else:
                    self.draw_sensors_table(top, bottom, w)
                self.draw_footer()

            self.stdscr.refresh()

            ch = self.stdscr.getch()
            if ch != -1:
                self.handle_input(ch)
            else:
                time.sleep(0.05)


def main():
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(lambda stdscr: LSensorsTUI(stdscr).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()