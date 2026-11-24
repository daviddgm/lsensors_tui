# LSENSORS-TUI

**LSENSORS-TUI** is a lightweight, zero-dependency terminal user interface (TUI) hardware monitor for Linux, styled after classic **HWiNFO DOS** and **CPU-X** console utilities.

It reads telemetry directly from the Linux kernel's `hwmon` subsystem (`/sys/class/hwmon`), organizes sensors by category, tracks live session Minimum/Maximum values, allows persistent custom sensor renaming, and exports clean `.TXT` and `.HTML` telemetry reports.

---

## Features

* **Zero External Dependencies:** Built exclusively with Python 3's standard library (`curses`, `json`, `pathlib`, `glob`). No `pip` packages required.
* **Categorized Multi-Tab Layout:**
  * **All Sensors:** Unified overview of every detected sensor across all hardware adapters.
  * **Temperatures:** Thermal readings (`temp*_input`) in `°C` with color-coded thresholds and hardware `High` / `Crit` limits.
  * **Voltages:** Rail and core voltages (`in*_input`) in `V` with `Min..Max` hardware tolerances.
  * **Fans (RPM):** Cooling fan speeds (`fan*_input`) in `RPM`.
  * **Power / Curr:** Package/board power draw (`power*_average`/`input` in `W`), electrical current (`curr*_input` in `A`), and sensor clocks (`freq*_input` in `MHz`).
  * **Chips & Info:** Summary of detected `hwmon` kernel drivers (`k10temp`, `zenpower`, `coretemp`, `amdgpu`, `nvme`, `it87`, `nct6775`, `acpitz`, etc.) and bus paths (`PCI`, `I2C/SMBus`, `ISA/Platform`, `NVMe`).
* **Persistent Custom Sensor Titles:** Rename any sensor directly inside the TUI. Labels are keyed by `driver:channel` (e.g., `k10temp:temp1`, `amdgpu:fan1`) in `~/.config/lsensors_tui/labels.json`, preserving your custom names across reboots even if `hwmon` device indices change.
* **Live Session Min/Max Tracking:** Automatically records minimum and maximum readings since launch, with one-key reset.
* **Instant Report Export:** Generates formatted `.TXT` and styled `.HTML` reports directly into `~/Downloads`, reflecting your custom sensor labels and session statistics.
* **Dual Color Themes:** Switch on the fly between classic **HWiNFO DOS Blue** and **LHWDI Dark** modes.

---

## Requirements

* **OS:** Linux with `/sys/class/hwmon` enabled (standard on modern kernels).
* **Runtime:** Python 3.8 or newer with `curses` support.
* **Optional:** `lm-sensors` (`sensors-detect`) configured on your system so Super I/O and motherboard sensors (`it87`, `nct6775`, etc.) are exposed by the kernel.

---

## Installation & Usage

Clone the repository and make the script executable:

```bash
git clone [https://github.com/daviddgm/lsensors-tui.git](https://github.com/daviddgm/lsensors-tui.git)
cd lsensors-tui
chmod +x lsensors_tui.py
./lsensors_tui.py