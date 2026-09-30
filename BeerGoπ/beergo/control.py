"""Máquina de estados, PID, fervura e recirculação."""

import time


class ControlMixin:

    def step_start(self):
        self.s["pump_manual"] = None
        self.s["heater_manual_enabled"] = True
        self.s["pump_cycle_epoch"] = time.monotonic()
        self.s["boil_window_epoch"] = time.monotonic()
        self.s["boil_confirmed"] = False
        step = self.s["recipe"]["steps"][self.s["step_index"]]
        self.s["phase_log"].append(
            {
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "step_index": self.s["step_index"],
                "name": step["name"],
            }
        )
        self.mark_event("PHASE_START", step["name"])
        self.s["remaining_s"] = step["minutes"] * 60
        self.s["phase"] = (
            "WAIT_TARGET" if step["kind"] == "mash" else "WAIT_BOIL_CONFIRM"
        )
        self.s["status"] = "RUNNING"
        self.s["pending_events"] = []
        if self.s["step_index"] == 0:
            for e in self.s["recipe"]["events"]:
                if (
                    e["phase"].lower() == "mash"
                    and e["id"] not in self.s["confirmed_events"]
                ):
                    self.s["pending_events"].append(e)

    def last_mash_step(self):
        steps = self.s["recipe"]["steps"]
        return (
            self.s["step_index"] < len(steps) - 1
            and steps[self.s["step_index"]]["kind"] == "mash"
            and (steps[self.s["step_index"] + 1]["kind"] == "boil")
        )

    def begin_wash(self):
        # Lavagem exige confirmação; pré-aquecimento permite apenas resistência.
        self.s["phase"] = "WASH_PENDING"
        self.s["status"] = "RUNNING"
        self.s["wash_confirmed"] = False
        self.s["remaining_s"] = 0
        self.s["pump_manual"] = None
        self.pump(False)
        self.mark_event(
            "WASH_STARTED",
            "Aguardando confirmação do término da lavagem; pré-aquecimento da fervura iniciado",
        )

    def pump_phase_allowed(self):
        step = self.s["recipe"]["steps"][self.s["step_index"]]
        return (
            step["kind"] == "mash"
            and self.s["status"] == "RUNNING"
            and (self.s["phase"] in ("WAIT_TARGET", "COUNTDOWN"))
        )

    def pid_reset(self):
        self.PID.update(
            integral=0.0,
            last_temp=None,
            last_time=None,
            target=None,
            power_pct=0.0,
            window_epoch=time.monotonic(),
        )

    def pid_heat(self, target):
        now = time.monotonic()
        temp = self.s["temperature"]
        if self.PID["target"] != target or self.PID["last_time"] is None:
            self.pid_reset()
            self.PID["target"] = target
            self.PID["last_time"] = now
            self.PID["last_temp"] = temp
        # Janela temporal, sem PWM de alta frequência no SSR.
        dt = min(5.0, max(0.0, now - self.PID["last_time"]))
        error = target - temp
        # Corte independente do PID em sobretemperatura.
        if temp >= target + 1.5:
            self.PID["integral"] = min(0.0, self.PID["integral"])
            self.PID["power_pct"] = 0.0
        else:
            derivative = 0.0 if not dt else -(temp - self.PID["last_temp"]) / dt
            candidate = self.PID["integral"] + error * dt
            raw = (
                self.settings["pid_kp"] * error
                + self.settings["pid_ki"] * candidate
                + self.settings["pid_kd"] * derivative
            )
            if not (raw > 100 and error > 0 or (raw < 0 and error < 0)):
                self.PID["integral"] = max(-10000.0, min(10000.0, candidate))
            raw = (
                self.settings["pid_kp"] * error
                + self.settings["pid_ki"] * self.PID["integral"]
                + self.settings["pid_kd"] * derivative
            )
            self.PID["power_pct"] = max(0.0, min(100.0, raw))
        self.PID["last_time"] = now
        self.PID["last_temp"] = temp
        duty = self.PID["power_pct"] / 100.0
        self.heat(
            duty > 0
            and (now - self.PID["window_epoch"]) % self.BOIL_WINDOW_S
            < self.BOIL_WINDOW_S * duty
        )

    def update(self, dt):
        if not self.s["sensor_ok"] or self.s["temperature"] is None:
            self.pid_reset()
            self.heat(False)
            self.pump(False)
            if self.s["status"] == "RUNNING":
                self.s["status"] = "FAULT"
                self.s["phase"] = "FAULT"
                self.history("FAULT")
            return
        if self.s["status"] != "RUNNING":
            self.pid_reset()
            self.heat(False)
            self.pump(False)
            return
        step = self.s["recipe"]["steps"][self.s["step_index"]]
        if self.s["phase"] == "WASH_PENDING":
            self.pid_reset()
            self.pump(False)
            if self.s["pending_events"]:
                self.heat(False)
                return
            target = self.settings["boil_reference_c"]
            if self.s["temperature"] >= target:
                self.s["heater_requested"] = False
            elif self.s["temperature"] <= target - self.s["hysteresis_c"]:
                self.s["heater_requested"] = True
            self.heat(self.s["heater_requested"])
            return
        if self.s["pending_events"]:
            self.pid_reset()
            self.heat(False)
            self.pump(False)
            return
        if step["kind"] == "boil" and self.s["phase"] == "WAIT_BOIL_CONFIRM":
            if self.s["temperature"] >= self.settings["boil_reference_c"]:
                self.s["phase"] = "COUNTDOWN"
                self.s["boil_confirmed"] = True
                self.s["boil_window_epoch"] = time.monotonic()
                self.mark_event(
                    "BOIL_STARTED",
                    "Temperatura configurada atingida; cronômetro iniciado",
                )
        if self.s["phase"] == "WAIT_TARGET":
            if self.s["temperature"] >= step["target"]:
                self.s["phase"] = "COUNTDOWN"
        elif self.s["phase"] == "COUNTDOWN":
            previous = self.s["remaining_s"]
            self.s["remaining_s"] = max(0, previous - dt * self.s["test_speed"])
            if step["kind"] == "boil":
                for e in self.s["recipe"]["events"]:
                    if (
                        e["phase"].lower() == "boil"
                        and e["id"] not in self.s["confirmed_events"]
                        and (previous > e["at_remaining"] * 60 >= self.s["remaining_s"])
                    ):
                        self.s["pending_events"].append(e)
            if self.s["remaining_s"] == 0:
                if self.last_mash_step():
                    self.begin_wash()
                    return
                following = self.s["step_index"] + 1
                if (
                    step["kind"] == "mash"
                    and following < len(self.s["recipe"]["steps"])
                    and (self.s["recipe"]["steps"][following]["kind"] == "mash")
                ):
                    self.heat(False)
                    self.pump(False)
                    self.s["step_index"] = following
                    self.step_start()
                    return
                self.s["phase"] = (
                    "AWAIT_NEXT"
                    if self.s["step_index"] < len(self.s["recipe"]["steps"]) - 1
                    else "COMPLETE"
                )
                self.s["status"] = (
                    "AWAIT_NEXT" if self.s["phase"] == "AWAIT_NEXT" else "COMPLETE"
                )
                self.heat(False)
                self.pump(False)
                if self.s["status"] == "COMPLETE":
                    self.history("COMPLETE")
                return
        if self.s["pending_events"]:
            self.pid_reset()
            self.heat(False)
            self.pump(False)
            return
        if step["kind"] == "mash" and self.s["phase"] in ("WAIT_TARGET", "COUNTDOWN"):
            if self.settings["pid_enabled"] and self.s["heater_manual_enabled"]:
                self.pid_heat(step["target"])
            else:
                self.pid_reset()
                if self.s["temperature"] >= step["target"]:
                    self.s["heater_requested"] = False
                elif self.s["temperature"] <= step["target"] - self.s["hysteresis_c"]:
                    self.s["heater_requested"] = True
                self.heat(self.s["heater_requested"])
        elif step["kind"] == "boil" and self.s["phase"] == "WAIT_BOIL_CONFIRM":
            self.pid_reset()
            self.s["heater_requested"] = self.s["heater_manual_enabled"]
            self.heat(self.s["heater_manual_enabled"])
        elif (
            step["kind"] == "boil"
            and self.s["phase"] == "COUNTDOWN"
            and self.s["boil_confirmed"]
        ):
            self.pid_reset()
            power = (
                self.settings["boil_power_pct"]
                if self.s["temperature"] <= self.settings["boil_reference_c"]
                else 0
            )
            self.heat(
                power > 0
                and (time.monotonic() - self.s["boil_window_epoch"])
                % self.BOIL_WINDOW_S
                < self.BOIL_WINDOW_S * power / 100
            )
        else:
            self.pid_reset()
            self.heat(False)
        if not self.pump_phase_allowed():
            self.pump(False)
            return
        if self.s["pump_manual"] is not None:
            self.pump(self.s["pump_manual"])
            return
        allowed_phase = self.pump_phase_allowed() and (
            self.s["phase"] == "COUNTDOWN"
            or (self.s["phase"] == "WAIT_TARGET" and self.settings["pump_during_heat"])
        )
        if allowed_phase and self.settings["pump_cycle_enabled"]:
            period = self.settings["pump_on_s"] + self.settings["pump_off_s"]
            self.pump(
                (time.monotonic() - self.s["pump_cycle_epoch"]) % period
                < self.settings["pump_on_s"]
            )
        else:
            self.pump(False)
