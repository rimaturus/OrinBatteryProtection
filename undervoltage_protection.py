#!/usr/bin/env python3
import time
import os
import glob
import statistics
import argparse
import logging
import sys
import subprocess
import re

class VoltageMonitor:
    def __init__(self,
                 driver_bus='ina3221',
                 i2c_addr='1-0040',
                 threshold=14.0,
                 interval=1.0,
                 log_file='/home/psd/custom_services/voltage_monitor_test_new.log',
                 undervoltage_limit=10,
                 debug=False):
        self.threshold = threshold
        self.interval = interval
        self.log_file = log_file
        self.undervoltage_limit = undervoltage_limit
        self.undervoltage_cnt = 0
        self.debug = debug

        base = f'/sys/bus/i2c/drivers/{driver_bus}/{i2c_addr}/hwmon'
        self.hwmon_paths = glob.glob(os.path.join(base, 'hwmon*'))
        if not self.hwmon_paths:
            raise FileNotFoundError(f"No hwmon directories found under {base}")

        # Initialize CPU usage tracking
        self._prev_idle = None
        self._prev_total = None

        if not self.debug:
            self._setup_logging()

    def _setup_logging(self):
        self.logger = logging.getLogger('VoltageMonitor')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler(self.log_file)
        fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(fmt)
        self.logger.addHandler(handler)

    def get_cpu_usage(self):
        """Get current CPU usage percentage"""
        try:
            with open('/proc/stat', 'r') as f:
                line = f.readline()
            cpu_times = [int(x) for x in line.split()[1:]]
            idle_time = cpu_times[3]
            total_time = sum(cpu_times)
            
            # Store previous values for calculation
            if self._prev_idle is None:
                self._prev_idle = idle_time
                self._prev_total = total_time
                return 0.0
            
            idle_delta = idle_time - self._prev_idle
            total_delta = total_time - self._prev_total
            
            self._prev_idle = idle_time
            self._prev_total = total_time
            
            if total_delta == 0:
                return 0.0
            
            cpu_usage = 100.0 * (1.0 - idle_delta / total_delta)
            return max(0.0, min(100.0, cpu_usage))
        except Exception as e:
            if self.debug:
                print(f"CPU usage error: {e}")
            return 0.0

    def get_gpu_usage(self):
        """Get current GPU usage percentage - improved for Jetson devices"""
        # Method 1: Try nvidia-smi
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu', 
                                   '--format=csv,noheader,nounits'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip().isdigit():
                gpu_usage = float(result.stdout.strip())
                if self.debug:
                    print(f"GPU usage from nvidia-smi: {gpu_usage}%")
                return gpu_usage
        except Exception as e:
            if self.debug:
                print(f"nvidia-smi failed: {e}")
        
        # Method 2: Try tegrastats for Jetson devices
        try:
            # Run tegrastats briefly
            proc = subprocess.Popen(['tegrastats', '--interval', '100'], 
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            time.sleep(0.3)  # Let it collect one sample
            proc.terminate()
            stdout, _ = proc.communicate(timeout=1)
            
            # Parse the output for GPU usage
            lines = stdout.strip().split('\n')
            for line in lines:
                if 'GR3D_FREQ' in line:
                    # Look for pattern like "GR3D_FREQ 45%@..."
                    match = re.search(r'GR3D_FREQ\s+(\d+)%', line)
                    if match:
                        gpu_usage = float(match.group(1))
                        if self.debug:
                            print(f"GPU usage from tegrastats: {gpu_usage}%")
                        return gpu_usage
        except Exception as e:
            if self.debug:
                print(f"tegrastats failed: {e}")
        
        # Method 3: Try /sys/devices/gpu.0/load (if available)
        try:
            gpu_load_paths = [
                '/sys/devices/gpu.0/load',
                '/sys/devices/platform/gpu.0/load',
                '/sys/class/devfreq/17000000.gv11b/load'
            ]
            for path in gpu_load_paths:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        load_str = f.read().strip()
                    # Parse load (might be in format "45" or "45%" or "45/100")
                    match = re.search(r'(\d+)', load_str)
                    if match:
                        gpu_usage = float(match.group(1))
                        # If the value seems to be a fraction (like 45/100), adjust
                        if '/' in load_str and gpu_usage > 100:
                            gpu_usage = gpu_usage / 100.0 * 100.0
                        if self.debug:
                            print(f"GPU usage from {path}: {gpu_usage}%")
                        return min(100.0, gpu_usage)
        except Exception as e:
            if self.debug:
                print(f"sysfs GPU load failed: {e}")
        
        # Method 4: Try jetson_stats (if available)
        try:
            result = subprocess.run(['jtop', '--json'], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                if 'gpu' in data and 'val' in data['gpu']:
                    gpu_usage = float(data['gpu']['val'])
                    if self.debug:
                        print(f"GPU usage from jtop: {gpu_usage}%")
                    return gpu_usage
        except Exception as e:
            if self.debug:
                print(f"jtop failed: {e}")
        
        if self.debug:
            print("GPU usage: falling back to 0% (no method worked)")
        return 0.0

    def correct_voltage(self, raw_voltage, cpu_usage, gpu_usage):
        """Apply voltage correction formula based on CPU and GPU load"""
        # Formula: real[V] = raw[V] + 0.00395 * CPU + 0.01278 * GPU + 0.560
        corrected = raw_voltage + (0.00395 * cpu_usage) + (0.01478 * gpu_usage) + 0.560
        return corrected

    def read_mean_voltage(self):
        voltages = []
        for hwmon in self.hwmon_paths:
            # look for any in*_label file
            for lbl_path in glob.glob(os.path.join(hwmon, 'in*_label')):
                try:
                    with open(lbl_path, 'r') as f:
                        label = f.read().strip()
                except Exception:
                    continue
                if 'VDD' not in label:
                    continue
                # derive channel name, e.g. "in1" from "in1_label"
                channel = os.path.basename(lbl_path).split('_')[0]
                input_path = os.path.join(hwmon, f'{channel}_input')
                try:
                    with open(input_path, 'r') as f:
                        raw = int(f.read().strip())
                    voltages.append(raw / 1000.0)
                except Exception:
                    # skip channels that fail to read
                    continue

        if not voltages:
            return None, None, 0.0, 0.0
        
        raw_mean = statistics.mean(voltages)
        
        # Get CPU and GPU usage for correction
        cpu_usage = self.get_cpu_usage()
        gpu_usage = self.get_gpu_usage()
        
        # Apply voltage correction
        corrected_mean = self.correct_voltage(raw_mean, cpu_usage, gpu_usage)
        
        return raw_mean, corrected_mean, cpu_usage, gpu_usage

    def shutdown_system(self):
        if not self.debug:
            self.logger.warning("Undervoltage threshold exceeded. Initiating shutdown.")
            os.system('/sbin/shutdown now')

    def monitor(self):
        if not self.debug:
            self.logger.info(f"Starting monitor (threshold={self.threshold}V, interval={self.interval}s)")
        
        while True:
            raw_v, corrected_v, cpu_usage, gpu_usage = self.read_mean_voltage()
            
            if raw_v is not None and corrected_v is not None:
                if self.debug:
                    # Debug mode: print raw, corrected voltage, and load info
                    print(f"Raw: {raw_v:.3f}V, Corrected: {corrected_v:.3f}V, CPU: {cpu_usage:.1f}%, GPU: {gpu_usage:.1f}%")
                else:
                    # Normal mode: full logging and monitoring
                    self.logger.info(f"Raw VDD: {raw_v:.3f}V, Corrected: {corrected_v:.3f}V, CPU: {cpu_usage:.1f}%, GPU: {gpu_usage:.1f}%")
                    
                    if corrected_v < self.threshold:
                        self.undervoltage_cnt += 1
                        self.logger.warning(f"Below threshold ({corrected_v:.3f}V). Count: {self.undervoltage_cnt}/{self.undervoltage_limit}")
                        if self.undervoltage_cnt >= self.undervoltage_limit:
                            self.shutdown_system()
                            return
                    else:
                        self.undervoltage_cnt = 0
            else:
                if self.debug:
                    print("Error: No VDD channels found or failed to read voltages")
                else:
                    self.logger.error("No VDD channels found or failed to read any voltages")
            
            time.sleep(self.interval)

def parse_args():
    parser = argparse.ArgumentParser(description="Monitor VDD voltages from INA3221")
    parser.add_argument('-t', '--threshold', type=float, default=14.5,
                        help='Voltage threshold in volts')
    parser.add_argument('-i', '--interval', type=float, default=1.0,
                        help='Sampling interval in seconds')
    parser.add_argument('-l', '--log', default='/home/psd/custom_services/voltage_monitor_test_new.log',
                        help='Path to log file')
    parser.add_argument('-u', '--undervoltage_limit', type=int, default=10,
                        help='Consecutive under-threshold readings before shutdown')
    parser.add_argument('--debug', action='store_true',
                        help='Debug mode: only print raw and corrected voltage with load info')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    try:
        vm = VoltageMonitor(
            threshold=args.threshold,
            interval=args.interval,
            log_file=args.log,
            undervoltage_limit=args.undervoltage_limit,
            debug=args.debug
        )
        vm.monitor()
    except KeyboardInterrupt:
        if args.debug:
            print("\nMonitoring stopped by user")
        sys.exit(0)
    except Exception as e:
        if args.debug:
            print(f"Error: Failed to start VoltageMonitor: {e}")
        else:
            logging.error(f"Failed to start VoltageMonitor: {e}")
        sys.exit(1)
