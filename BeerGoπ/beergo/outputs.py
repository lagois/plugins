"""Comandos GPIO e bloqueios das saídas físicas."""


class OutputsMixin:

    def heat(self, on):
        # Temperatura virtual e falha bloqueiam sempre a saída física.
        allowed = (
            self.cfg["mode"] == "bench"
            and self.cfg.get("enable_heater_gpio_test", False)
            and self.s["sensor_ok"]
            and (not self.s["sensor_fault_test"])
            and (self.s["virtual_temperature"] is None)
        )
        physical = bool(on and allowed and self.s["heater_manual_enabled"])
        if self.GPIO is not None:
            self.GPIO.output(
                int(self.cfg["heater_gpio"]),
                self.GPIO.HIGH if physical else self.GPIO.LOW,
            )
        self.s["heater"] = physical
        self.s["heater_requested"] = bool(on and self.s["heater_manual_enabled"])

    def pump(self, on):
        # Bomba ativa em nível baixo; em simulação nunca aciona GPIO.
        actual = bool(
            on
            and self.cfg["mode"] == "bench"
            and self.cfg.get("enable_pump_test", False)
            and self.s["sensor_ok"]
            and (not self.s["sensor_fault_test"])
            and (self.s["virtual_temperature"] is None)
        )
        if self.GPIO is not None:
            self.GPIO.output(
                int(self.cfg["pump_gpio"]), self.GPIO.LOW if actual else self.GPIO.HIGH
            )
        self.s["pump"] = actual
