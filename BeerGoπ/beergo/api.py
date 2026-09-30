"""Servidor HTTP e rotas compatíveis com a interface existente."""

import json, time, xml.etree.ElementTree as ET, os, uuid
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse


class Handler(BaseHTTPRequestHandler):

    def reply(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/api/mobile/state":
            with self.app.lock:
                steps = self.app.s["recipe"]["steps"]
                index = self.app.s["step_index"]
                step = steps[index] if 0 <= index < len(steps) else None
                following = steps[index + 1] if 0 <= index + 1 < len(steps) else None
                self.reply(
                    {
                        "version": "0.11Beta",
                        "recipe": self.app.s["recipe"]["name"],
                        "status": self.app.s["status"],
                        "phase": self.app.s["phase"],
                        "step": (
                            None
                            if step is None
                            else {
                                "name": step["name"],
                                "kind": step["kind"],
                                "target": step.get("target"),
                            }
                        ),
                        "next_step": (
                            None
                            if following is None
                            else {
                                "name": following["name"],
                                "target": following.get("target"),
                            }
                        ),
                        "temperature": (
                            self.app.s["temperature"]
                            if self.app.s["sensor_ok"]
                            else None
                        ),
                        "sensor_ok": self.app.s["sensor_ok"],
                        "target": (
                            self.app.settings["boil_reference_c"]
                            if step and step["kind"] == "boil"
                            else step.get("target") if step else None
                        ),
                        "remaining_s": self.app.s["remaining_s"],
                        "pump": bool(self.app.s["pump"]),
                        "heater": bool(self.app.s["heater"]),
                        "pid_enabled": self.app.settings["pid_enabled"],
                        "pid_power_pct": round(self.app.PID["power_pct"], 1),
                        "heater_power_pct": (
                            round(self.app.PID["power_pct"], 1)
                            if self.app.s["status"] == "RUNNING"
                            and step
                            and (step["kind"] == "mash")
                            and self.app.settings["pid_enabled"]
                            and self.app.s["heater_manual_enabled"]
                            and (not self.app.s["pending_events"])
                            else (
                                (
                                    100
                                    if self.app.s["status"] == "RUNNING"
                                    and step
                                    and (step["kind"] == "mash")
                                    and self.app.s["heater_requested"]
                                    and (not self.app.s["pending_events"])
                                    else 0
                                )
                                if step and step["kind"] == "mash"
                                else (
                                    (
                                        100
                                        if self.app.s["status"] == "RUNNING"
                                        and self.app.s["phase"] == "WAIT_BOIL_CONFIRM"
                                        and self.app.s["heater_manual_enabled"]
                                        and (not self.app.s["pending_events"])
                                        else (
                                            self.app.settings["boil_power_pct"]
                                            if self.app.s["status"] == "RUNNING"
                                            and self.app.s["phase"] == "COUNTDOWN"
                                            and self.app.s["boil_confirmed"]
                                            and (self.app.s["temperature"] is not None)
                                            and (
                                                self.app.s["temperature"]
                                                <= self.app.settings["boil_reference_c"]
                                            )
                                            and (not self.app.s["pending_events"])
                                            else 0
                                        )
                                    )
                                    if step and step["kind"] == "boil"
                                    else 0
                                )
                            )
                        ),
                        "pending_events": [
                            {
                                "id": e.get("id"),
                                "name": e.get("name"),
                                "amount": e.get("amount"),
                                "phase": e.get("phase"),
                            }
                            for e in self.app.s["pending_events"]
                        ],
                        "message": self.app.s.get("message", ""),
                        "samples": [
                            {
                                "ts": a.get("ts"),
                                "temperature": a.get("temperature"),
                                "target": a.get("target"),
                            }
                            for a in self.app.s["samples"][-240:]
                        ],
                    }
                )
                return
        if p == "/api/state":
            with self.app.lock:
                self.reply(
                    dict(
                        self.app.s,
                        pump_phase_allowed=self.app.pump_phase_allowed(),
                        pump_cycle_enabled=self.app.settings["pump_cycle_enabled"],
                        pump_on_s=self.app.settings["pump_on_s"],
                        pump_off_s=self.app.settings["pump_off_s"],
                        boil_power_pct=self.app.settings["boil_power_pct"],
                        boil_reference_c=self.app.settings["boil_reference_c"],
                        pid_enabled=self.app.settings["pid_enabled"],
                        pid_power_pct=round(self.app.PID["power_pct"], 1),
                        pid_kp=self.app.settings["pid_kp"],
                        pid_ki=self.app.settings["pid_ki"],
                        pid_kd=self.app.settings["pid_kd"],
                        pump_next_s=(
                            None
                            if not self.app.pump_phase_allowed()
                            or self.app.s["pump_manual"] is not None
                            or (not self.app.settings["pump_cycle_enabled"])
                            else max(
                                0,
                                (
                                    self.app.settings["pump_on_s"]
                                    if self.app.s["pump"]
                                    else self.app.settings["pump_on_s"]
                                    + self.app.settings["pump_off_s"]
                                )
                                - (time.monotonic() - self.app.s["pump_cycle_epoch"])
                                % (
                                    self.app.settings["pump_on_s"]
                                    + self.app.settings["pump_off_s"]
                                ),
                            )
                        ),
                        current_target_c=(
                            self.app.settings["boil_reference_c"]
                            if self.app.s["phase"] == "WASH_PENDING"
                            or self.app.s["recipe"]["steps"][self.app.s["step_index"]][
                                "kind"
                            ]
                            == "boil"
                            else self.app.s["recipe"]["steps"][
                                self.app.s["step_index"]
                            ]["target"]
                        ),
                        recipes=[
                            {"id": k, "name": v["name"]}
                            for k, v in self.app.recipes.items()
                        ],
                    )
                )
                return
        if p == "/api/diagnostics":
            with self.app.lock:
                self.reply(self.app.diagnostic_snapshot())
                return
        if p == "/api/settings":
            with self.app.lock:
                self.reply(
                    {
                        "values": self.app.settings,
                        "reserved": sorted(self.app.SETTINGS_RESERVED),
                        "hardware": {
                            "mode": self.app.cfg["mode"],
                            "sensor_gpio": self.app.cfg["sensor_gpio"],
                            "heater_gpio": self.app.cfg["heater_gpio"],
                            "pump_gpio": self.app.cfg["pump_gpio"],
                            "enable_heater_gpio_test": self.app.cfg[
                                "enable_heater_gpio_test"
                            ],
                            "enable_pump_test": self.app.cfg["enable_pump_test"],
                        },
                        "safety": {
                            "sensor_failure_heater_off": True,
                            "automatic_restart": False,
                            "recovery_confirmation": True,
                        },
                    }
                )
                return
        if p == "/api/recipe/detail":
            from urllib.parse import parse_qs

            key = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            with self.app.lock:
                if key not in self.app.recipes:
                    self.reply({"error": "Receita não encontrada"}, 404)
                    return
                self.reply(
                    {
                        "id": key,
                        "recipe": self.app.recipes[key],
                        "xml": (self.app.RECIPES / key).read_text(encoding="utf-8"),
                    }
                )
                return
        if p == "/api/history":
            self.reply(
                [
                    {
                        k: v
                        for k, v in r.items()
                        if k not in ("samples", "phase_log", "event_log")
                    }
                    for r in self.app.history_records()
                ]
            )
            return
        if p == "/api/history/detail":
            from urllib.parse import parse_qs

            key = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            record = next(
                (r for r in self.app.history_records() if r.get("id") == key), None
            )
            if record is None:
                self.reply({"error": "Registro não encontrado"}, 404)
                return
            self.reply(record)
            return
        if p in ("/mobile", "/mobile/", "/mobile.html", "/mobile.css", "/mobile.js"):
            name = "mobile.html" if p in ("/mobile", "/mobile/") else p.lstrip("/")
            file = self.app.BASE / "web" / name
            raw = file.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                {
                    "html": "text/html; charset=utf-8",
                    "js": "text/javascript; charset=utf-8",
                    "css": "text/css; charset=utf-8",
                }[file.suffix[1:]],
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if p in (
            "/",
            "/index.html",
            "/app.js",
            "/app.css",
            "/beergo-logo-color.png",
            "/beergo-logo-color.svg",
            "/beergo-pi-logo-lupulo.png",
            "/mobile-setup-aprovado.png",
        ):
            name = "index.html" if p == "/" else p.lstrip("/")
            file = self.app.BASE / "web" / name
            raw = file.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                {
                    "html": "text/html; charset=utf-8",
                    "js": "text/javascript; charset=utf-8",
                    "css": "text/css; charset=utf-8",
                    "png": "image/png",
                    "svg": "image/svg+xml",
                }[file.suffix[1:]],
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.reply({"error": "Não encontrado"}, 404)

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 300000:
                raise ValueError("Requisição muito grande")
            body = json.loads(self.rfile.read(n)) if n else {}
            with self.app.lock:
                if p == "/api/settings/save":
                    new = self.app.validate_settings(body.get("values"))
                    old_settings = self.app.settings.copy()
                    self.app.save_settings(new)
                    self.app.settings.update(new)
                    self.app.s["hysteresis_c"] = self.app.settings["hysteresis_c"]
                    if any(
                        (
                            old_settings[k] != new[k]
                            for k in ("pid_enabled", "pid_kp", "pid_ki", "pid_kd")
                        )
                    ):
                        self.app.pid_reset()
                    if (
                        old_settings["pump_cycle_enabled"] != new["pump_cycle_enabled"]
                        or old_settings["pump_on_s"] != new["pump_on_s"]
                        or old_settings["pump_off_s"] != new["pump_off_s"]
                    ):
                        self.app.s["pump_cycle_epoch"] = time.monotonic()
                    if old_settings["boil_power_pct"] != new["boil_power_pct"]:
                        self.app.s["boil_window_epoch"] = time.monotonic()
                    if self.app.s["run_id"] and self.app.s["status"] in (
                        "RUNNING",
                        "PAUSED",
                        "AWAIT_NEXT",
                    ):
                        for k in new:
                            if old_settings[k] != new[k]:
                                self.app.mark_event(
                                    "SETTING_CHANGED",
                                    json.dumps(
                                        {
                                            "key": k,
                                            "old": old_settings[k],
                                            "new": new[k],
                                        },
                                        ensure_ascii=False,
                                    ),
                                )
                    self.reply(
                        {
                            "ok": True,
                            "values": self.app.settings,
                            "reserved": sorted(self.app.SETTINGS_RESERVED),
                        }
                    )
                    return
                if p == "/api/history/delete":
                    key = str(body.get("id", ""))
                    records = self.app.history_records()
                    if not any((r.get("id") == key for r in records)):
                        raise ValueError(
                            "Registro não encontrado ou legado sem identificador"
                        )
                    temp = self.app.HISTORY.with_suffix(".tmp")
                    with temp.open("w", encoding="utf-8") as f:
                        for r in records:
                            if r.get("id") != key:
                                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(temp, self.app.HISTORY)
                elif p == "/api/recipe/select":
                    if self.app.s["status"] in (
                        "RUNNING",
                        "PAUSED",
                        "AWAIT_NEXT",
                        "RECOVERY_REQUIRED",
                    ):
                        raise ValueError("Encerre o processo antes de trocar receita")
                    key = body["id"]
                    self.app.s["recipe"] = self.app.recipes[key]
                    self.app.s["recipe_id"] = key
                    self.app.s["status"] = "IDLE"
                    self.app.s["step_index"] = 0
                    self.app.s["confirmed_events"] = []
                    self.app.s["history_written"] = False
                elif p == "/api/recipe/import":
                    if self.app.s["status"] in (
                        "RUNNING",
                        "PAUSED",
                        "AWAIT_NEXT",
                        "RECOVERY_REQUIRED",
                    ):
                        raise ValueError("Encerre o processo antes de importar")
                    name = str(body.get("filename", ""))
                    if (
                        not name.lower().endswith(".xml")
                        or "/" in name
                        or "\\" in name
                        or name.startswith(".")
                    ):
                        raise ValueError("Nome de arquivo BeerXML inválido")
                    xml = str(body.get("xml", ""))
                    if len(xml.encode("utf-8")) > 250000:
                        raise ValueError("BeerXML excede 250 kB")
                    import io

                    ET.parse(io.StringIO(xml))
                    tmp = self.app.RECIPES / (name + ".tmp")
                    tmp.write_text(xml, encoding="utf-8")
                    try:
                        recipe = self.app.recipe_load(tmp)
                    except Exception:
                        tmp.unlink(missing_ok=True)
                        raise
                    dest = self.app.RECIPES / name
                    if dest.exists():
                        tmp.unlink(missing_ok=True)
                        raise ValueError("Já existe receita com este nome")
                    tmp.replace(dest)
                    recipe["source"] = name
                    self.app.recipes[name] = recipe
                    self.app.s["message"] = "BeerXML importado: " + recipe["name"]
                elif p == "/api/recipe/update":
                    if self.app.s["status"] in (
                        "RUNNING",
                        "PAUSED",
                        "AWAIT_NEXT",
                        "RECOVERY_REQUIRED",
                    ):
                        raise ValueError("Encerre o processo antes de alterar receitas")
                    key = body.get("id", "")
                    xml = body.get("xml", "")
                    if key not in self.app.recipes:
                        raise ValueError("Receita não encontrada")
                    if not isinstance(xml, str) or len(xml.encode("utf-8")) > 250000:
                        raise ValueError("BeerXML inválido ou excede 250 kB")
                    ET.parse(io.StringIO(xml))
                    tmp = self.app.RECIPES / (key + ".tmp")
                    tmp.write_text(xml, encoding="utf-8")
                    try:
                        recipe = self.app.recipe_load(tmp)
                    except Exception:
                        tmp.unlink(missing_ok=True)
                        raise
                    dest = self.app.RECIPES / key
                    os.replace(tmp, dest)
                    recipe["source"] = key
                    self.app.recipes[key] = recipe
                    if self.app.s["recipe_id"] == key:
                        self.app.s["recipe"] = recipe
                        self.app.s["step_index"] = 0
                        self.app.s["remaining_s"] = 0
                        self.app.s["phase"] = ""
                        self.app.s["status"] = "IDLE"
                        self.app.s["confirmed_events"] = []
                        self.app.s["pending_events"] = []
                        self.app.s["history_written"] = False
                    self.app.s["message"] = "Receita alterada: " + recipe["name"]
                elif p == "/api/recipe/delete":
                    if self.app.s["status"] in (
                        "RUNNING",
                        "PAUSED",
                        "AWAIT_NEXT",
                        "RECOVERY_REQUIRED",
                    ):
                        raise ValueError("Encerre o processo antes de excluir receitas")
                    key = body.get("id", "")
                    if key not in self.app.recipes:
                        raise ValueError("Receita não encontrada")
                    if key == self.app.s["recipe_id"]:
                        raise ValueError(
                            "Selecione outra receita antes de excluir a receita atual"
                        )
                    if len(self.app.recipes) <= 1:
                        raise ValueError("É necessário manter ao menos uma receita")
                    (self.app.RECIPES / key).unlink()
                    del self.app.recipes[key]
                    self.app.s["message"] = "Receita excluída"
                elif p == "/api/process/recover":
                    if self.app.s["status"] != "RECOVERY_REQUIRED":
                        raise ValueError("Não há processo para recuperar")
                    if (
                        not self.app.s["sensor_ok"]
                        or self.app.s["virtual_temperature"] is not None
                    ):
                        raise ValueError("Recuperação requer sensor real válido")
                    self.app.s["status"] = "PAUSED"
                    self.app.s["phase"] = (
                        "WAIT_TARGET"
                        if self.app.s["recipe"]["steps"][self.app.s["step_index"]][
                            "kind"
                        ]
                        == "mash"
                        else "WAIT_BOIL_CONFIRM"
                    )
                    self.app.s["message"] = (
                        "Processo recuperado PAUSADO; confira avisos antes de retomar"
                    )
                    self.app.heat(False)
                    self.app.pump(False)
                elif p == "/api/test/virtual":
                    val = body.get("temperature")
                    if val is not None and (
                        isinstance(val, bool)
                        or not isinstance(val, (int, float))
                        or (not 10 <= val <= 100)
                    ):
                        raise ValueError("Temperatura virtual 10–100 °C")
                    self.app.heat(False)
                    self.app.s["virtual_temperature"] = val
                    self.app.s["message"] = (
                        "Temperatura virtual: saída SSR fisicamente bloqueada"
                        if val is not None
                        else "Leitura real restaurada"
                    )
                elif p == "/api/test/fault":
                    self.app.s["sensor_fault_test"] = bool(body["on"])
                    if self.app.s["sensor_fault_test"]:
                        self.app.s["sensor_ok"] = False
                        self.app.s["temperature"] = None
                        self.app.update(0)
                elif p == "/api/test/speed":
                    val = int(body["speed"])
                    if val not in (1, 10, 60):
                        raise ValueError("Velocidade deve ser 1, 10 ou 60")
                    self.app.s["test_speed"] = val
                elif p == "/api/process/start":
                    if self.app.s["status"] in (
                        "RUNNING",
                        "PAUSED",
                        "AWAIT_NEXT",
                        "RECOVERY_REQUIRED",
                    ):
                        raise ValueError("Processo em andamento")
                    if not self.app.s["sensor_ok"]:
                        raise ValueError("Sensor inválido")
                    self.app.s["step_index"] = 0
                    self.app.s["confirmed_events"] = []
                    self.app.s["history_written"] = False
                    self.app.s["run_id"] = uuid.uuid4().hex
                    self.app.s["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    self.app.s["samples"] = []
                    self.app.s["phase_log"] = []
                    self.app.s["event_log"] = []
                    self.app.step_start()
                elif p == "/api/process/confirm-event":
                    key = body["id"]
                    pending = next(
                        (e for e in self.app.s["pending_events"] if e["id"] == key),
                        None,
                    )
                    if pending is None:
                        raise ValueError("Aviso não está pendente")
                    self.app.mark_event("ADDITION_CONFIRMED", pending["name"])
                    self.app.s["confirmed_events"].append(key)
                    self.app.s["pending_events"] = [
                        e for e in self.app.s["pending_events"] if e["id"] != key
                    ]
                elif p == "/api/process/boil-confirm":
                    if self.app.s["phase"] != "WAIT_BOIL_CONFIRM":
                        raise ValueError("Fervura não aguarda confirmação")
                    raise ValueError(
                        "Confirmação manual desativada; a fervura inicia ao atingir a temperatura configurada"
                    )
                elif p == "/api/process/wash-confirm":
                    if (
                        self.app.s["phase"] != "WASH_PENDING"
                        or self.app.s["status"] != "RUNNING"
                    ):
                        raise ValueError("Não há confirmação de lavagem pendente")
                    if self.app.s["pending_events"]:
                        raise ValueError(
                            "Confirme as adições pendentes antes de concluir a lavagem"
                        )
                    self.app.s["wash_confirmed"] = True
                    self.app.mark_event(
                        "WASH_CONFIRMED", "Término de lavagem confirmado"
                    )
                    self.app.heat(False)
                    self.app.s["step_index"] += 1
                    self.app.step_start()
                elif p == "/api/process/next":
                    if self.app.s["status"] not in ("RUNNING", "PAUSED", "AWAIT_NEXT"):
                        raise ValueError("Não há fase ativa para avançar")
                    if self.app.s["pending_events"]:
                        raise ValueError(
                            "Confirme as adições pendentes antes de avançar"
                        )
                    if self.app.s["phase"] == "WASH_PENDING":
                        raise ValueError(
                            "Confirme o término da lavagem antes de avançar"
                        )
                    if (
                        self.app.s["step_index"]
                        >= len(self.app.s["recipe"]["steps"]) - 1
                    ):
                        raise ValueError("Esta é a última fase da receita")
                    if self.app.last_mash_step():
                        self.app.begin_wash()
                    else:
                        self.app.heat(False)
                        self.app.s["step_index"] += 1
                        self.app.step_start()
                elif p == "/api/process/pause":
                    if self.app.s["status"] != "RUNNING":
                        raise ValueError("Processo não está em execução")
                    self.app.mark_event("PAUSED")
                    self.app.s["status"] = "PAUSED"
                    self.app.heat(False)
                elif p == "/api/process/resume":
                    if (
                        self.app.s["status"] != "PAUSED"
                        or not self.app.s["sensor_ok"]
                        or (
                            self.app.cfg["mode"] == "bench"
                            and self.app.s["virtual_temperature"] is not None
                        )
                    ):
                        raise ValueError(
                            "Retomada requer sensor válido; em bancada, sensor real"
                        )
                    if self.app.s["pending_events"]:
                        raise ValueError(
                            "Confirme os avisos pendentes antes de retomar"
                        )
                    self.app.mark_event("RESUMED")
                    self.app.s["status"] = "RUNNING"
                elif p == "/api/process/finalize":
                    if self.app.s["status"] not in ("RUNNING", "PAUSED", "AWAIT_NEXT"):
                        raise ValueError("Não há brassagem ativa para finalizar")
                    if self.app.s["pending_events"]:
                        raise ValueError(
                            "Confirme as adições pendentes antes de finalizar"
                        )
                    self.app.mark_event("FINALIZED_BY_OPERATOR")
                    self.app.heat(False)
                    self.app.pump(False)
                    self.app.history("COMPLETE")
                    self.app.s["status"] = "COMPLETE"
                    self.app.s["phase"] = "COMPLETE"
                elif p == "/api/process/stop":
                    if self.app.s["status"] not in (
                        "RUNNING",
                        "PAUSED",
                        "AWAIT_NEXT",
                        "RECOVERY_REQUIRED",
                    ):
                        raise ValueError("Não há brassagem ativa para parar")
                    self.app.mark_event("STOPPED_BY_OPERATOR")
                    self.app.heat(False)
                    self.app.pump(False)
                    self.app.history("STOPPED")
                    self.app.s["status"] = "STOPPED"
                    self.app.s["phase"] = "STOPPED"
                    self.app.s["pending_events"] = []
                elif p == "/api/process/interrupt":
                    if self.app.s["status"] not in (
                        "RUNNING",
                        "PAUSED",
                        "AWAIT_NEXT",
                        "RECOVERY_REQUIRED",
                    ):
                        raise ValueError("Não há brassagem ativa para interromper")
                    self.app.mark_event("INTERRUPTED_BY_OPERATOR")
                    self.app.heat(False)
                    self.app.pump(False)
                    self.app.history("INTERRUPTED")
                    self.app.s["status"] = "INTERRUPTED"
                    self.app.s["phase"] = "INTERRUPTED"
                    self.app.s["pending_events"] = []
                    self.app.s["message"] = "Brassagem interrompida pelo operador"
                elif p == "/api/heater/enable":
                    enable = bool(body.get("on"))
                    if enable and (
                        not self.app.s["sensor_ok"]
                        or not self.app.cfg.get("enable_heater_gpio_test")
                        or self.app.s["status"]
                        not in ("RUNNING", "PAUSED", "AWAIT_NEXT")
                    ):
                        raise ValueError(
                            "Aquecimento indisponível: verifique sensor, habilitação e estado do processo"
                        )
                    self.app.s["heater_manual_enabled"] = enable
                    if not enable:
                        self.app.heat(False)
                    self.app.mark_event(
                        "HEATER_MANUAL_ENABLE" if enable else "HEATER_MANUAL_DISABLE"
                    )
                elif p == "/api/pump":
                    if body.get("on") and (not self.app.pump_phase_allowed()):
                        raise ValueError(
                            "Bomba permitida somente durante Mash-in e Mash-out com brassagem em execução"
                        )
                    if body.get("on") and (
                        not self.app.s["sensor_ok"]
                        or not self.app.cfg.get("enable_pump_test")
                    ):
                        raise ValueError("Bomba não habilitada ou sensor inválido")
                    self.app.s["pump_manual"] = bool(body["on"])
                    self.app.pump(self.app.s["pump_manual"])
                else:
                    self.reply({"error": "Não encontrado"}, 404)
                    return
                self.app.update(0)
                self.app.save_checkpoint()
                self.reply({"ok": True})
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            self.reply({"error": str(exc)}, 400)

    def log_message(self, fmt, *args):
        print(fmt % args)
