"""Diagnóstico somente leitura do sistema e controlador."""

import time, os, socket, shutil
from pathlib import Path


class DiagnosticsMixin:

    def _read_system(self):
        data = {
            "uptime_s": round(time.monotonic() - self.BOOT_MONOTONIC),
            "cpu_percent": None,
            "cpu_temperature_c": None,
            "memory_available_mb": None,
            "disk_free_mb": None,
            "undervoltage": None,
            "ip": None,
            "hostname": socket.gethostname(),
            "web_port": self.cfg.get("port", 18765),
        }
        try:
            raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
            data["cpu_temperature_c"] = round(int(raw) / 1000, 1)
        except (OSError, ValueError):
            pass
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    data["memory_available_mb"] = round(int(line.split()[1]) / 1024)
                    break
        except (OSError, ValueError, IndexError):
            pass
        try:
            data["disk_free_mb"] = round(shutil.disk_usage(self.BASE).free / 1048576)
        except OSError:
            pass
        try:
            load = os.getloadavg()[0]
            data["cpu_load_1m"] = round(load, 2)
        except (OSError, AttributeError):
            data["cpu_load_1m"] = None
        try:
            import subprocess

            v = subprocess.run(
                ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1
            )
            if v.returncode == 0:
                code = int(v.stdout.strip().split("=")[-1], 16)
                data["undervoltage"] = {
                    "current": bool(code & 1),
                    "occurred": bool(code & 1 << 16),
                }
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            pass
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.2)
            sock.connect(("192.0.2.1", 9))
            data["ip"] = sock.getsockname()[0]
            sock.close()
        except OSError:
            pass
        return data

    def _diagnostic_reasons(self):
        reasons = []
        if self.s["status"] == "RECOVERY_REQUIRED":
            reasons.append("Recuperação manual pendente após reinicialização")
        if self.s["status"] == "PAUSED":
            reasons.append("Processo pausado")
        if self.s["status"] not in ("RUNNING", "PAUSED"):
            reasons.append("Processo não está em execução")
        if not self.s["sensor_ok"]:
            reasons.append("Sensor T1 sem leitura válida")
        if self.s["sensor_fault_test"]:
            reasons.append("Falha de sensor simulada")
        if self.s["virtual_temperature"] is not None:
            reasons.append("Temperatura virtual: saída física bloqueada")
        if not self.cfg.get("enable_heater_gpio_test"):
            reasons.append("Saída física da resistência desabilitada")
        if not self.s["heater_manual_enabled"]:
            reasons.append("Aquecimento bloqueado manualmente")
        if self.s["pending_events"]:
            reasons.append("Confirmação de adição pendente")
        if self.s["phase"] == "WASH_PENDING":
            reasons.append("Lavagem pendente: pré-aquecimento da fervura permitido")
        if self.s["phase"] == "WAIT_BOIL_CONFIRM":
            reasons.append(
                "Aquecendo até a temperatura configurada para início da fervura"
            )
        if self.s["heater_requested"] and (not self.s["heater"]) and (not reasons):
            reasons.append("Controle térmico: SSR no intervalo desligado")
        if not reasons:
            reasons.append("Sem bloqueios de segurança identificados")
        pump_reasons = []
        if not self.pump_phase_allowed():
            pump_reasons.append(
                "Bomba bloqueada fora da mostura ou com processo parado"
            )
        if not self.s["sensor_ok"]:
            pump_reasons.append("Sensor T1 inválido")
        if not self.cfg.get("enable_pump_test"):
            pump_reasons.append("Saída física da bomba desabilitada")
        if self.s["virtual_temperature"] is not None:
            pump_reasons.append("Temperatura virtual: saída física bloqueada")
        if not pump_reasons:
            pump_reasons.append(
                "Comando manual"
                if self.s["pump_manual"] is not None
                else "Controle cíclico / fase de aquecimento"
            )
        return (reasons, pump_reasons)

    def diagnostic_snapshot(self):
        hr, pr = self._diagnostic_reasons()
        return {
            "system": self._read_system(),
            "version": self.s["version"],
            "mode": self.cfg["mode"],
            "process": {
                "status": self.s["status"],
                "phase": self.s["phase"],
                "recipe": self.s["recipe"]["name"],
                "pending_count": len(self.s["pending_events"]),
                "recovery_required": self.s["status"] == "RECOVERY_REQUIRED",
            },
            "sensor": {
                "gpio": self.cfg["sensor_gpio"],
                "ok": self.s["sensor_ok"],
                "raw_c": self.SENSOR_STATS["last_raw"],
                "corrected_c": self.s["temperature"],
                "offset_c": self.settings["t1_offset_c"],
                "last_ok_age_s": (
                    None
                    if self.SENSOR_STATS["last_ok"] is None
                    else round(time.time() - self.SENSOR_STATS["last_ok"], 1)
                ),
                "errors": self.SENSOR_STATS["errors"],
                "last_error": self.SENSOR_STATS["last_error"],
                "virtual": self.s["virtual_temperature"] is not None,
            },
            "outputs": {
                "heater_gpio": self.cfg["heater_gpio"],
                "pump_gpio": self.cfg["pump_gpio"],
                "heater_enabled": self.s["heater_physical_enabled"],
                "pump_enabled": self.s["pump_physical_enabled"],
                "heater_command": self.s["heater_requested"],
                "heater_gpio_command": self.s["heater"],
                "pump_gpio_command": self.s["pump"],
                "pump_mode": (
                    "Manual"
                    if self.s["pump_manual"] is not None
                    else (
                        "Cíclico"
                        if self.settings["pump_cycle_enabled"]
                        else "Sem ciclo"
                    )
                ),
                "heater_reasons": hr,
                "pump_reasons": pr,
                "pid_enabled": self.settings["pid_enabled"],
                "pid_power_pct": round(self.PID["power_pct"], 1),
                "pid_kp": self.settings["pid_kp"],
                "pid_ki": self.settings["pid_ki"],
                "pid_kd": self.settings["pid_kd"],
            },
            "events": list(self.s["event_log"][-8:])[::-1],
        }
