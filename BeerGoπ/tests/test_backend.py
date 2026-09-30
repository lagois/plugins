"""Regressões funcionais sem GPIO ou dependências externas."""

import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from beergo import Application
from beergo.api import Handler

ROOT = Path(__file__).resolve().parents[1]


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        shutil.copytree(ROOT / "receitas", self.base / "receitas")
        shutil.copytree(ROOT / "web", self.base / "web")
        config = json.loads((ROOT / "config.example.json").read_text())
        config.update(
            mode="simulation", enable_heater_gpio_test=False, enable_pump_test=False
        )
        (self.base / "config.json").write_text(json.dumps(config))
        self.app = Application(self.base)
        self.app.s.update(sensor_ok=True, temperature=25)

    def start(self):
        self.app.step_start()
        self.app.s["pending_events"] = []

    def test_instances_do_not_share_state(self):
        other = Application(self.base)
        self.app.s["temperature"] = 75
        self.app.settings["pid_kp"] = 42
        self.assertIsNone(other.s["temperature"])
        self.assertEqual(other.settings["pid_kp"], 8)

    def test_sensor_failure_turns_outputs_off_and_records_fault(self):
        self.start()
        self.app.s.update(
            sensor_ok=False, heater=True, pump=True, heater_requested=True
        )
        self.app.update(1)
        self.assertEqual(self.app.s["status"], "FAULT")
        self.assertFalse(self.app.s["heater"])
        self.assertFalse(self.app.s["pump"])
        self.assertFalse(self.app.s["heater_requested"])
        self.assertEqual(self.app.history_records()[0]["result"], "FAULT")

    def test_pending_addition_and_pause_block_heating(self):
        self.start()
        self.app.s["pending_events"] = [{"id": "addition"}]
        self.app.update(1)
        self.assertFalse(self.app.s["heater_requested"])
        self.app.s.update(pending_events=[], status="PAUSED", heater_requested=True)
        self.app.update(1)
        self.assertFalse(self.app.s["heater_requested"])
        self.assertFalse(self.app.s["pump"])

    def test_mash_to_wash_then_boil_completion(self):
        self.start()
        self.app.s.update(
            step_index=len(self.app.s["recipe"]["steps"]) - 2,
            phase="COUNTDOWN",
            remaining_s=1,
            temperature=78,
        )
        self.app.update(2)
        self.assertEqual(self.app.s["phase"], "WASH_PENDING")
        self.assertFalse(self.app.pump_phase_allowed())
        self.app.s["step_index"] += 1
        self.app.step_start()
        self.app.s["temperature"] = self.app.settings["boil_reference_c"]
        self.app.update(0)
        self.assertEqual(self.app.s["phase"], "COUNTDOWN")
        self.assertTrue(self.app.s["boil_confirmed"])
        self.app.s["confirmed_events"] = [
            e["id"] for e in self.app.s["recipe"]["events"]
        ]
        self.app.s["remaining_s"] = 1
        self.app.update(2)
        self.assertEqual(self.app.s["status"], "COMPLETE")
        self.assertEqual(self.app.history_records()[0]["result"], "COMPLETE")

    def test_pid_overtemperature_requests_no_heat(self):
        self.start()
        self.app.s["temperature"] = self.app.s["recipe"]["steps"][0]["target"] + 2
        self.app.update(0)
        self.assertEqual(self.app.PID["power_pct"], 0)
        self.assertFalse(self.app.s["heater_requested"])

    def test_virtual_temperature_and_sensor_fault_block_gpio(self):
        self.app.cfg.update(
            mode="bench", enable_heater_gpio_test=True, enable_pump_test=True
        )
        gpio = self.app.GPIO = Mock(HIGH=1, LOW=0)
        for changes in (
            {"virtual_temperature": 65},
            {"virtual_temperature": None, "sensor_fault_test": True},
            {"sensor_fault_test": False, "sensor_ok": False},
        ):
            self.app.s.update(changes)
            self.app.heat(True)
            self.app.pump(True)
            self.assertFalse(self.app.s["heater"])
            self.assertFalse(self.app.s["pump"])
            gpio.output.assert_any_call(self.app.cfg["heater_gpio"], 0)
            gpio.output.assert_any_call(self.app.cfg["pump_gpio"], 1)

    def test_checkpoint_requires_manual_recovery(self):
        self.start()
        self.app.s.update(heater=True, pump=True)
        self.app.save_checkpoint()
        recovered = Application(self.base)
        self.assertEqual(recovered.s["status"], "RECOVERY_REQUIRED")
        self.assertFalse(recovered.s["heater"])
        self.assertFalse(recovered.s["pump"])

    def test_settings_roundtrip_and_validation(self):
        values = dict(self.app.settings, pid_kp=12, pump_on_s=240)
        self.app.save_settings(values)
        self.assertEqual(Application(self.base).settings, values)
        with self.assertRaises(ValueError):
            self.app.validate_settings(dict(values, pid_kp=-1))
        with self.assertRaises(ValueError):
            self.app.validate_settings(dict(values, pid_enabled=1))

    def test_http_routes_and_process_commands(self):
        handler = type(
            "TestHandler",
            (Handler,),
            {"app": self.app, "log_message": lambda *args: None},
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join()

        self.addCleanup(cleanup)

        def request(path, body=None):
            data = None if body is None else json.dumps(body).encode()
            req = Request(
                f"http://127.0.0.1:{server.server_port}" + path,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=5) as response:
                return response.read()

        for path in (
            "/",
            "/mobile",
            "/app.js",
            "/app.css",
            "/beergo-pi-logo-lupulo.png",
        ):
            self.assertTrue(request(path))
        for path in (
            "/api/state",
            "/api/mobile/state",
            "/api/diagnostics",
            "/api/settings",
            "/api/history",
        ):
            json.loads(request(path))
        request("/api/process/start", {})
        for event in list(self.app.s["pending_events"]):
            request("/api/process/confirm-event", {"id": event["id"]})
        request("/api/process/pause", {})
        self.assertEqual(self.app.s["status"], "PAUSED")
        self.assertFalse(self.app.s["heater_requested"])
        request("/api/process/resume", {})
        self.assertEqual(self.app.s["status"], "RUNNING")
        request("/api/process/stop", {})
        self.assertEqual(self.app.s["status"], "STOPPED")
        self.assertEqual(json.loads(request("/api/history"))[0]["result"], "STOPPED")
        with self.assertRaises(HTTPError) as caught:
            request("/api/process/resume", {})
        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
