"""System monitoring service."""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import psutil

from app.core.config import get_settings
from app.models.schemas import ServiceInfo, SystemStatus, TailscaleInfo


class SystemMonitor:
    """Monitor system health and metrics."""

    def __init__(self):
        self.settings = get_settings()

    def get_cpu_temp(self) -> float | None:
        """Get CPU temperature (Raspberry Pi specific with fallback)."""
        try:
            # Try vcgencmd for Raspberry Pi
            result = subprocess.run(
                ["vcgencmd", "measure_temp"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Output: temp=45.2'C
                temp_str = result.stdout.strip().replace("temp=", "").replace("'C", "")
                return float(temp_str)
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass

        # Fallback: try thermal zones
        try:
            thermal_zones = list(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
            if thermal_zones:
                temps = []
                for zone in thermal_zones:
                    try:
                        temp_millidegrees = int(zone.read_text().strip())
                        temps.append(temp_millidegrees / 1000.0)
                    except (ValueError, IOError):
                        continue
                if temps:
                    return sum(temps) / len(temps)
        except Exception:
            pass

        return None

    def get_service_status(self, name: str, port: int | None = None) -> ServiceInfo:
        """Get service status."""
        pid = None
        status = "stopped"

        try:
            # Check if process is running
            if name == "gateway":
                # Look for gateway process
                for proc in psutil.process_iter(["pid", "cmdline"]):
                    try:
                        cmdline = " ".join(proc.info.get("cmdline") or [])
                        if "gateway" in cmdline and "python" in cmdline:
                            pid = proc.info["pid"]
                            status = "running"
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            elif name == "matrixbridge":
                # Check port 8765
                for conn in psutil.net_connections():
                    if conn.laddr.port == 8765 and conn.status == "LISTEN":
                        pid = conn.pid
                        status = "running"
                        break
            else:
                # Generic check
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        if name.lower() in proc.info.get("name", "").lower():
                            pid = proc.info["pid"]
                            status = "running"
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
        except Exception:
            pass

        return ServiceInfo(name=name, status=status, port=port, pid=pid)

    def get_tailscale_status(self) -> TailscaleInfo:
        """Get Tailscale status."""
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return TailscaleInfo(
                    funnel=data.get("Self", {}).get("Capabilities", [])
                    and "funnel" in str(data.get("Self", {}).get("Capabilities", [])),
                    hostname=data.get("Self", {}).get("HostName", ""),
                    ip=data.get("Self", {}).get("TailAddrs", [None])[0],
                )
        except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError):
            pass

        # Fallback: check if tailscaled is running
        try:
            for proc in psutil.process_iter(["name"]):
                if proc.info.get("name") == "tailscaled":
                    return TailscaleInfo(funnel=False, hostname="hermes", ip=None)
        except Exception:
            pass

        return TailscaleInfo(funnel=False, hostname="", ip=None)

    def _collect_local_system_status(self, requested_instance: str = "pc") -> SystemStatus:
        """Collect system status from the local Mission Control host."""
        # CPU
        cpu_usage = psutil.cpu_percent(interval=0.5)

        # Memory
        memory = psutil.virtual_memory()

        # Disk
        disk = psutil.disk_usage("/")

        # Services
        services = [
            self.get_service_status("gateway", 8766),
            self.get_service_status("matrixbridge", 8765),
        ]

        return SystemStatus(
            requested_instance=requested_instance if requested_instance in {"all", "pc", "pi"} else "pc",
            resolved_instance="pc",
            source_label="PC local host",
            cpu_temp=self.get_cpu_temp(),
            cpu_usage=cpu_usage,
            memory_used=memory.used,
            memory_total=memory.total,
            disk_used=disk.used,
            disk_total=disk.total,
            services=services,
            tailscale=self.get_tailscale_status(),
        )

    def _resolve_pi_status_url(self) -> str | None:
        """Resolve PI status URL from explicit config or webhook origin."""
        explicit = (self.settings.pi_status_url or "").strip()
        if explicit:
            return explicit.rstrip("/")

        webhook_url = (self.settings.linear_webhook_url or "").strip()
        if not webhook_url:
            return None

        parsed = urlparse(webhook_url)
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}/api/status"

    def _collect_remote_pi_status(self) -> SystemStatus:
        """Fetch PI telemetry from the remote Mission Control status endpoint."""
        pi_status_url = self._resolve_pi_status_url()
        if not pi_status_url:
            raise RuntimeError("PI telemetry endpoint is not configured")

        bearer_token = (self.settings.pi_bearer_token or self.settings.bearer_token or "").strip()
        headers = {"Accept": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        request = Request(pi_status_url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"PI telemetry request failed with HTTP {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"PI telemetry request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("PI telemetry response was not valid JSON") from exc

        status = SystemStatus.model_validate(payload)
        status.requested_instance = "pi"
        status.resolved_instance = "pi"
        status.source_label = status.source_label or "PI remote host"
        return status

    def get_system_status(self, instance: str = "all") -> SystemStatus:
        """Get system status for the requested instance."""
        normalized = (instance or "all").strip().lower()
        if normalized not in {"all", "pc", "pi"}:
            normalized = "all"
        if normalized == "pi":
            return self._collect_remote_pi_status()
        return self._collect_local_system_status(requested_instance=normalized)


# Singleton instance
system_monitor = SystemMonitor()
