"""Leitura do DS18B20 e modos de teste e simulação."""

import time
from pathlib import Path


class SensorsMixin:

    def sensor_loop(self):
        while True:
            with self.lock:
                if self.s["sensor_fault_test"]:
                    self.s["temperature"] = None
                    self.s["sensor_ok"] = False
                elif self.s["virtual_temperature"] is not None:
                    self.s["temperature"] = self.s["virtual_temperature"]
                    self.s["sensor_ok"] = True
                elif self.cfg["mode"] == "simulation":
                    self.s["temperature"] = round(
                        24 + 2 * (time.monotonic() / 30 % 1), 2
                    )
                    self.s["sensor_ok"] = True
                else:
                    try:
                        files = list(Path("/sys/bus/w1/devices").glob("28-*/w1_slave"))
                        if len(files) != 1:
                            raise ValueError("Esperado exatamente um DS18B20")
                        raw = files[0].read_text()
                        lines = raw.splitlines()
                        if not lines or not lines[0].endswith("YES"):
                            raise ValueError("CRC inválido")
                        value = float(lines[-1].split("t=")[-1]) / 1000
                        if not -10 <= value <= 110:
                            raise ValueError("Leitura fora da faixa")
                        self.s["temperature"] = round(
                            value + self.settings["t1_offset_c"], 2
                        )
                        self.s["sensor_ok"] = True
                        self.SENSOR_STATS.update(
                            last_ok=time.time(), last_raw=value, last_error=None
                        )
                    except Exception as exc:
                        self.s["temperature"] = None
                        self.s["sensor_ok"] = False
                        self.s["message"] = str(exc)
                        self.SENSOR_STATS["errors"] += 1
                        self.SENSOR_STATS["last_error"] = str(exc)
                now = time.monotonic()
                old = (self.s["status"], self.s["phase"], int(self.s["remaining_s"]))
                self.update(min(now - self.last_tick, 3))
                self.last_tick = now
                self.sample()
                if old != (
                    self.s["status"],
                    self.s["phase"],
                    int(self.s["remaining_s"]),
                ):
                    self.save_checkpoint()
            time.sleep(self.settings["sensor_interval_s"])
