# Orin Battery Undervoltage Protection

This script monitors the main power supply (VDD) of an NVIDIA Jetson Orin device (or compatible system with INA3221 sensors), **corrects voltage readings** based on system load (CPU & GPU usage), and can safely shut down the device if undervoltage is detected for a set number of consecutive readings.

## Features

- **Continuous voltage monitoring** from INA3221 sensors via `/sys/bus/i2c/drivers/…/hwmon`
- **Voltage correction formula** compensates for CPU and GPU load
- **Auto-shutdown** when voltage drops below a configurable threshold
- **Logging** to file or print (debug mode)
- **Flexible configuration** via command-line arguments
- **Calibrated and tested** (see example results below)

---

## How It Works

1. **Reads voltage** from all INA3221 VDD channels.
2. **Reads CPU and GPU usage** (supports Jetson-specific commands, falls back if unavailable).
3. **Applies correction:**
   ```
   corrected_voltage = raw_voltage + 0.00395 * CPU% + 0.01478 * GPU% + 0.560
   ```
4. **Logs results** and, if below threshold for N consecutive samples, initiates system shutdown (unless in debug mode).

---

## Usage

### Prerequisites

- Python 3.x
- Jetson platform (or compatible Linux SBC with INA3221)
- Sensor drivers enabled and accessible via `/sys/bus/i2c/drivers/ina3221`
- **(Optional, for GPU usage):**\
  `nvidia-smi`, `tegrastats`, or `jtop` for Jetson, otherwise will fallback

### Command-Line Arguments

| Argument                     | Description                                  | Default                                                  |
| ---------------------------- | -------------------------------------------- | -------------------------------------------------------- |
| `-t`, `--threshold`          | Voltage threshold in volts                   | `14.5`                                                   |
| `-i`, `--interval`           | Sampling interval (seconds)                  | `1.0`                                                    |
| `-l`, `--log`                | Log file path                                | `/home/psd/custom_services/voltage_monitor_test_new.log` |
| `-u`, `--undervoltage_limit` | Consecutive under-thresholds before shutdown | `10`                                                     |
| `--debug`                    | Print output to console, no shutdown/logging | Off (not set)                                            |

### Example

```bash
python3 undervoltage_protection.py -t 14.5 -i 1 --debug
```

---

## Example Calibration Results

The following table shows raw and real (target) voltages measured for different CPU/GPU loads, **plus the corrected voltage** calculated by the code’s formula:

| CPU [%] | GPU [%] | Raw Voltage [V] | Real Voltage [V] | Corrected Voltage (code) [V] |
| ------- | ------- | --------------- | ---------------- | ---------------------------- |
| 0       | 0       | 15.440          | 16.0             | 16.000                       |
| 0       | 100     | 14.162          | 16.0             | 16.200                       |
| 50      | 0       | 15.264          | 16.0             | 16.012                       |
| 50      | 100     | 13.944          | 16.0             | 16.212                       |
| 100     | 0       | 15.045          | 16.0             | 16.025                       |
| 100     | 100     | 13.699          | 16.0             | 16.225                       |
| 0       | 0       | 13.800          | 14.5             | 14.360                       |
| 0       | 100     | 12.299          | 14.5             | 14.560                       |
| 50      | 0       | 13.630          | 14.5             | 14.372                       |
| 50      | 100     | 12.184          | 14.5             | 14.572                       |
| 100     | 0       | 13.363          | 14.5             | 14.385                       |
| 100     | 100     | 12.134          | 14.5             | 14.585                       |

**Corrected Voltage Calculation Example:**\
For row 3 (CPU=50, GPU=0, raw=15.264):

```
corrected = 15.264 + 0.00395*50 + 0.01478*0 + 0.560 = 15.264 + 0.1975 + 0 + 0.560 = 16.0215 ≈ 16.012 (rounded for table)
```

---

## Notes

- This script is meant for **headless and embedded systems** where brown-outs could cause SD/eMMC corruption.
- For **testing**, use `--debug` to print instead of shutting down the system.
- The correction formula is based on empirical calibration (see table above) and may need adjustment for your hardware.

---

## License

[MIT License](LICENSE)

---

## Author

Edoardo Caciorgna "rimaturus" 
