#!/usr/bin/env python3
"""
Performance Monitoring Script for GrowMate Raspberry Pi

This script monitors system performance metrics in real-time and logs them
for analysis. Useful for validating system stability and resource usage.

Metrics monitored:
- Memory usage (total, available, percent)
- CPU usage (percent, per-core)
- Network statistics (bytes sent/received)
- Disk I/O
- Process-specific metrics (if GrowMate service is running)
- Uptime

This is a bonus feature not present in ESP32, but valuable for production
monitoring on Linux systems.

Usage:
    # Monitor for 60 seconds with 5-second intervals
    python3 scripts/monitor_performance.py --duration 60 --interval 5
    
    # Continuous monitoring (Ctrl+C to stop)
    python3 scripts/monitor_performance.py --continuous
    
    # Monitor and log to file
    python3 scripts/monitor_performance.py --output /var/log/growmate-perf.log
"""

import sys
import os
import time
import argparse
import signal
from datetime import datetime

try:
    import psutil
except ImportError:
    print("Error: psutil library not found")
    print("Install with: pip3 install psutil")
    sys.exit(1)


class PerformanceMonitor:
    """Monitor system performance metrics"""
    
    def __init__(self, output_file=None):
        """
        Initialize performance monitor
        
        Args:
            output_file: Optional file path to log metrics
        """
        self.output_file = output_file
        self.start_time = time.time()
        self.running = True
        
        # Initial network counters
        self.net_io_start = psutil.net_io_counters()
        
        # Find GrowMate process if running
        self.growmate_process = self._find_growmate_process()
        
        # Set up signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        print("\nShutting down monitor...")
        self.running = False
    
    def _find_growmate_process(self):
        """Find the GrowMate service process"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                cmdline = proc.info.get('cmdline', [])
                if cmdline and 'main.py' in ' '.join(cmdline):
                    return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return None
    
    def get_memory_stats(self):
        """Get memory usage statistics"""
        mem = psutil.virtual_memory()
        return {
            'total_mb': mem.total / (1024 * 1024),
            'available_mb': mem.available / (1024 * 1024),
            'used_mb': mem.used / (1024 * 1024),
            'percent': mem.percent
        }
    
    def get_cpu_stats(self):
        """Get CPU usage statistics"""
        cpu_percent = psutil.cpu_percent(interval=1, percpu=False)
        cpu_per_core = psutil.cpu_percent(interval=0, percpu=True)
        
        return {
            'overall_percent': cpu_percent,
            'per_core': cpu_per_core,
            'load_avg': os.getloadavg() if hasattr(os, 'getloadavg') else None
        }
    
    def get_network_stats(self):
        """Get network statistics"""
        net_io = psutil.net_io_counters()
        
        # Calculate delta since start
        bytes_sent_delta = net_io.bytes_sent - self.net_io_start.bytes_sent
        bytes_recv_delta = net_io.bytes_recv - self.net_io_start.bytes_recv
        
        return {
            'bytes_sent_total': net_io.bytes_sent,
            'bytes_recv_total': net_io.bytes_recv,
            'bytes_sent_delta_mb': bytes_sent_delta / (1024 * 1024),
            'bytes_recv_delta_mb': bytes_recv_delta / (1024 * 1024),
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv
        }
    
    def get_disk_stats(self):
        """Get disk I/O statistics"""
        disk_io = psutil.disk_io_counters()
        disk_usage = psutil.disk_usage('/')
        
        return {
            'read_mb': disk_io.read_bytes / (1024 * 1024),
            'write_mb': disk_io.write_bytes / (1024 * 1024),
            'disk_usage_percent': disk_usage.percent,
            'disk_free_gb': disk_usage.free / (1024 * 1024 * 1024)
        }
    
    def get_process_stats(self):
        """Get GrowMate process-specific statistics"""
        if not self.growmate_process:
            return None
        
        try:
            # Refresh process info
            self.growmate_process = psutil.Process(self.growmate_process.pid)
            
            mem_info = self.growmate_process.memory_info()
            
            return {
                'pid': self.growmate_process.pid,
                'cpu_percent': self.growmate_process.cpu_percent(interval=0.1),
                'memory_mb': mem_info.rss / (1024 * 1024),
                'num_threads': self.growmate_process.num_threads(),
                'status': self.growmate_process.status()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
    
    def get_uptime(self):
        """Get system uptime"""
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        
        return {
            'uptime_seconds': uptime_seconds,
            'uptime_hours': uptime_seconds / 3600,
            'uptime_days': uptime_seconds / 86400
        }
    
    def get_temperature(self):
        """Get CPU temperature (Raspberry Pi specific)"""
        try:
            # Try Raspberry Pi thermal zone
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp_millidegrees = int(f.read().strip())
                return temp_millidegrees / 1000.0
        except (FileNotFoundError, PermissionError, ValueError):
            return None
    
    def collect_metrics(self):
        """Collect all performance metrics"""
        timestamp = datetime.now().isoformat()
        monitor_uptime = time.time() - self.start_time
        
        metrics = {
            'timestamp': timestamp,
            'monitor_uptime_seconds': monitor_uptime,
            'memory': self.get_memory_stats(),
            'cpu': self.get_cpu_stats(),
            'network': self.get_network_stats(),
            'disk': self.get_disk_stats(),
            'process': self.get_process_stats(),
            'system_uptime': self.get_uptime(),
            'temperature_celsius': self.get_temperature()
        }
        
        return metrics
    
    def format_metrics(self, metrics):
        """Format metrics for display"""
        lines = []
        lines.append(f"=== GrowMate Performance Metrics - {metrics['timestamp']} ===")
        lines.append(f"Monitor Uptime: {metrics['monitor_uptime_seconds']:.1f}s")
        lines.append("")
        
        # Memory
        mem = metrics['memory']
        lines.append(f"Memory: {mem['used_mb']:.1f}MB / {mem['total_mb']:.1f}MB ({mem['percent']:.1f}%)")
        lines.append(f"  Available: {mem['available_mb']:.1f}MB")
        lines.append("")
        
        # CPU
        cpu = metrics['cpu']
        lines.append(f"CPU: {cpu['overall_percent']:.1f}%")
        if cpu['load_avg']:
            lines.append(f"  Load Average: {cpu['load_avg'][0]:.2f}, {cpu['load_avg'][1]:.2f}, {cpu['load_avg'][2]:.2f}")
        if cpu['per_core']:
            core_str = ", ".join([f"{c:.1f}%" for c in cpu['per_core']])
            lines.append(f"  Per Core: {core_str}")
        lines.append("")
        
        # Temperature
        if metrics['temperature_celsius']:
            lines.append(f"Temperature: {metrics['temperature_celsius']:.1f}°C")
            lines.append("")
        
        # Network
        net = metrics['network']
        lines.append(f"Network (since start):")
        lines.append(f"  Sent: {net['bytes_sent_delta_mb']:.2f}MB ({net['packets_sent']} packets)")
        lines.append(f"  Received: {net['bytes_recv_delta_mb']:.2f}MB ({net['packets_recv']} packets)")
        lines.append("")
        
        # Disk
        disk = metrics['disk']
        lines.append(f"Disk:")
        lines.append(f"  Read: {disk['read_mb']:.1f}MB, Write: {disk['write_mb']:.1f}MB")
        lines.append(f"  Usage: {disk['disk_usage_percent']:.1f}% (Free: {disk['disk_free_gb']:.1f}GB)")
        lines.append("")
        
        # GrowMate Process
        proc = metrics['process']
        if proc:
            lines.append(f"GrowMate Process (PID {proc['pid']}):")
            lines.append(f"  CPU: {proc['cpu_percent']:.1f}%")
            lines.append(f"  Memory: {proc['memory_mb']:.1f}MB")
            lines.append(f"  Threads: {proc['num_threads']}")
            lines.append(f"  Status: {proc['status']}")
        else:
            lines.append("GrowMate Process: Not running")
        lines.append("")
        
        # System Uptime
        uptime = metrics['system_uptime']
        lines.append(f"System Uptime: {uptime['uptime_days']:.2f} days ({uptime['uptime_hours']:.1f} hours)")
        lines.append("")
        
        return "\n".join(lines)
    
    def log_metrics(self, metrics):
        """Log metrics to file"""
        if not self.output_file:
            return
        
        try:
            with open(self.output_file, 'a') as f:
                f.write(self.format_metrics(metrics))
                f.write("\n")
        except IOError as e:
            print(f"Error writing to log file: {e}")
    
    def run(self, duration=None, interval=5, continuous=False):
        """
        Run performance monitoring
        
        Args:
            duration: Total duration in seconds (None for continuous)
            interval: Sampling interval in seconds
            continuous: Run continuously until interrupted
        """
        print("Starting GrowMate Performance Monitor")
        print(f"Sampling interval: {interval}s")
        
        if continuous:
            print("Mode: Continuous (Ctrl+C to stop)")
        elif duration:
            print(f"Duration: {duration}s")
        
        if self.output_file:
            print(f"Logging to: {self.output_file}")
        
        print()
        
        start_time = time.time()
        sample_count = 0
        
        try:
            while self.running:
                # Collect and display metrics
                metrics = self.collect_metrics()
                output = self.format_metrics(metrics)
                
                # Clear screen and display
                os.system('clear' if os.name == 'posix' else 'cls')
                print(output)
                
                # Log to file if specified
                self.log_metrics(metrics)
                
                sample_count += 1
                
                # Check duration
                if duration and (time.time() - start_time) >= duration:
                    break
                
                # Wait for next sample
                time.sleep(interval)
        
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
        
        # Final summary
        elapsed = time.time() - start_time
        print()
        print("=" * 70)
        print("Monitoring Summary")
        print("=" * 70)
        print(f"Samples collected: {sample_count}")
        print(f"Total duration: {elapsed:.1f}s")
        print(f"Average interval: {elapsed/sample_count:.1f}s" if sample_count > 0 else "N/A")
        
        if self.output_file:
            print(f"Metrics logged to: {self.output_file}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Monitor GrowMate system performance',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor for 60 seconds with 5-second intervals
  %(prog)s --duration 60 --interval 5
  
  # Continuous monitoring (Ctrl+C to stop)
  %(prog)s --continuous
  
  # Monitor and log to file
  %(prog)s --output /var/log/growmate-perf.log --continuous
  
  # Quick 30-second test
  %(prog)s --duration 30 --interval 2
        """
    )
    
    parser.add_argument(
        '--duration',
        type=int,
        help='Monitoring duration in seconds (default: continuous)'
    )
    
    parser.add_argument(
        '--interval',
        type=int,
        default=5,
        help='Sampling interval in seconds (default: 5)'
    )
    
    parser.add_argument(
        '--continuous',
        action='store_true',
        help='Run continuously until interrupted'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        help='Log metrics to file'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.duration and args.continuous:
        print("Error: Cannot specify both --duration and --continuous")
        sys.exit(1)
    
    if not args.duration and not args.continuous:
        # Default to continuous
        args.continuous = True
    
    # Create monitor
    monitor = PerformanceMonitor(output_file=args.output)
    
    # Run monitoring
    monitor.run(
        duration=args.duration,
        interval=args.interval,
        continuous=args.continuous
    )


if __name__ == '__main__':
    main()
