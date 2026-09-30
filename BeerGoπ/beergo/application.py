"""Inicialização explícita e composição dos módulos do BeerGoπ."""

import json, time, threading
from pathlib import Path
from http.server import ThreadingHTTPServer

from .settings import SettingsMixin
from .recipes import RecipesMixin
from .outputs import OutputsMixin
from .persistence import PersistenceMixin
from .control import ControlMixin
from .sensors import SensorsMixin
from .diagnostics import DiagnosticsMixin
from .api import Handler


class Application(
    SettingsMixin,
    RecipesMixin,
    OutputsMixin,
    PersistenceMixin,
    ControlMixin,
    SensorsMixin,
    DiagnosticsMixin,
):

    def __init__(self, base):
        self.BASE = Path(base).resolve()
        self.CFG = self.BASE / "config.json"
        if not self.CFG.exists():
            raise SystemExit(
                "config.json ausente; reinstale o pacote preservando a configuração da bancada."
            )
        self.cfg = json.loads(self.CFG.read_text(encoding="utf-8"))
        if int(self.cfg["heater_gpio"]) == int(self.cfg["pump_gpio"]):
            raise SystemExit("GPIOs da bomba e SSR não podem coincidir")
        self.SETTINGS_FILE = self.BASE / "dados" / "configuracoes.json"
        self.SETTINGS_DEFAULTS = {
            "t1_offset_c": 0.0,
            "hysteresis_c": self.cfg.get("temperature_hysteresis_c", 0.5),
            "history_interval_s": 5,
            "boil_reference_c": 100.0,
            "boil_power_pct": 70,
            "pump_cycle_enabled": True,
            "pump_on_s": 180,
            "pump_off_s": 60,
            "pump_during_heat": True,
            "sensor_interval_s": 1,
            "pid_enabled": True,
            "pid_kp": 8.0,
            "pid_ki": 0.03,
            "pid_kd": 0.0,
        }
        self.SETTINGS_LIMITS = {
            "t1_offset_c": (-10, 10),
            "hysteresis_c": (0.1, 5),
            "history_interval_s": (1, 60),
            "boil_reference_c": (85, 105),
            "boil_power_pct": (0, 100),
            "pump_on_s": (60, 86400),
            "pump_off_s": (60, 86400),
            "sensor_interval_s": (1, 10),
            "pid_kp": (0, 100),
            "pid_ki": (0, 5),
            "pid_kd": (0, 500),
        }
        self.SETTINGS_RESERVED = set()
        self.settings = (
            self.validate_settings(
                json.loads(self.SETTINGS_FILE.read_text(encoding="utf-8"))
            )
            if self.SETTINGS_FILE.exists()
            else self.SETTINGS_DEFAULTS.copy()
        )
        if self.SETTINGS_FILE.exists() and (
            all(
                (
                    self.settings[k] == v
                    for k, v in {
                        "pump_cycle_enabled": False,
                        "pump_on_s": 60,
                        "pump_off_s": 30,
                        "pump_during_heat": False,
                    }.items()
                )
            )
            or all(
                (
                    self.settings[k] == v
                    for k, v in {
                        "pump_cycle_enabled": True,
                        "pump_on_s": 10800,
                        "pump_off_s": 3600,
                        "pump_during_heat": True,
                    }.items()
                )
            )
        ):
            self.settings.update(
                {
                    "pump_cycle_enabled": True,
                    "pump_on_s": 180,
                    "pump_off_s": 60,
                    "pump_during_heat": True,
                }
            )
            self.save_settings(self.settings)
        self.BOOT_MONOTONIC = time.monotonic()
        self.SENSOR_STATS = {
            "last_ok": None,
            "errors": 0,
            "last_raw": None,
            "last_error": None,
        }
        self.lock = threading.RLock()
        self.GPIO = None
        if self.cfg["mode"] == "bench":
            try:
                import RPi.GPIO as GPIO

                self.GPIO = GPIO
                self.GPIO.setwarnings(False)
                self.GPIO.setmode(self.GPIO.BCM)
                self.GPIO.setup(
                    int(self.cfg["pump_gpio"]), self.GPIO.OUT, initial=self.GPIO.HIGH
                )
                self.GPIO.setup(
                    int(self.cfg["heater_gpio"]), self.GPIO.OUT, initial=self.GPIO.LOW
                )
            except Exception as exc:
                raise SystemExit("Falha na configuração dos GPIOs: " + str(exc))
        self.RECIPES = self.BASE / "receitas"
        self.RECIPES.mkdir(exist_ok=True)
        self.HISTORY = self.BASE / "dados" / "historico.jsonl"
        self.HISTORY.parent.mkdir(exist_ok=True)
        self.recipes = {}
        for p in self.RECIPES.glob("*.xml"):
            try:
                self.recipes[p.name] = self.recipe_load(p)
            except Exception as exc:
                print("Receita ignorada", p.name, exc)
        if not self.recipes:
            raise SystemExit("Nenhum BeerXML válido em receitas/")
        self.first = next(iter(self.recipes))
        self.s = {
            "version": "0.11Beta CONTROLE DINÂMICO",
            "mode": self.cfg["mode"],
            "temperature": None,
            "sensor_ok": False,
            "sensor_fault_test": False,
            "virtual_temperature": None,
            "pump": False,
            "heater": False,
            "heater_requested": False,
            "heater_physical_enabled": bool(
                self.cfg["mode"] == "bench" and self.cfg.get("enable_heater_gpio_test")
            ),
            "pump_physical_enabled": bool(
                self.cfg["mode"] == "bench" and self.cfg.get("enable_pump_test")
            ),
            "heater_gpio": int(self.cfg["heater_gpio"]),
            "pump_gpio": int(self.cfg["pump_gpio"]),
            "hysteresis_c": self.settings["hysteresis_c"],
            "recipe_id": self.first,
            "recipe": self.recipes[self.first],
            "status": "IDLE",
            "step_index": 0,
            "remaining_s": 0,
            "phase": "",
            "pending_events": [],
            "confirmed_events": [],
            "test_speed": 1,
            "message": "Pronto para teste de bancada",
            "history_written": False,
            "run_id": None,
            "started_at": None,
            "samples": [],
            "phase_log": [],
            "event_log": [],
            "pump_manual": None,
            "pump_cycle_epoch": time.monotonic(),
            "boil_window_epoch": time.monotonic(),
            "boil_confirmed": False,
            "heater_manual_enabled": True,
            "wash_confirmed": False,
        }
        self.last_tick = time.monotonic()
        self.CHECKPOINT = self.BASE / "dados" / "processo.json"
        self.restore_checkpoint()
        self.BOIL_WINDOW_S = 10.0
        self.PID = {
            "integral": 0.0,
            "last_temp": None,
            "last_time": None,
            "target": None,
            "power_pct": 0.0,
            "window_epoch": time.monotonic(),
        }

    def run(self):
        handler = type("ApplicationHandler", (Handler,), {"app": self})
        print(
            "BeerGoPi 0.11Beta CONTROLE DINÂMICO | SSR GPIO%d | bomba GPIO%d"
            % (self.cfg["heater_gpio"], self.cfg["pump_gpio"])
        )
        threading.Thread(target=self.sensor_loop, daemon=True).start()
        try:
            ThreadingHTTPServer(
                (self.cfg["host"], int(self.cfg["port"])), handler
            ).serve_forever()
        finally:
            self.heat(False)
            self.pump(False)
            self.save_checkpoint()
            if self.GPIO is not None:
                self.GPIO.cleanup()
