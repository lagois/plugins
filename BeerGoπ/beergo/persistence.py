"""Checkpoint, recuperação, histórico e amostras."""

import json, time, os, uuid


class PersistenceMixin:

    def save_checkpoint(self):
        snapshot = {
            k: self.s[k]
            for k in (
                "recipe_id",
                "status",
                "step_index",
                "remaining_s",
                "phase",
                "confirmed_events",
                "pending_events",
                "test_speed",
                "history_written",
                "run_id",
                "started_at",
                "samples",
                "phase_log",
                "event_log",
                "boil_confirmed",
                "wash_confirmed",
            )
        }
        temp = self.CHECKPOINT.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, self.CHECKPOINT)

    def restore_checkpoint(self):
        if not self.CHECKPOINT.exists():
            return
        try:
            old = json.loads(self.CHECKPOINT.read_text(encoding="utf-8"))
            if old.get("recipe_id") not in self.recipes:
                return
            self.s["recipe_id"] = old["recipe_id"]
            self.s["recipe"] = self.recipes[old["recipe_id"]]
            self.s["step_index"] = max(
                0, min(int(old["step_index"]), len(self.s["recipe"]["steps"]) - 1)
            )
            self.s["remaining_s"] = max(0, float(old["remaining_s"]))
            self.s["confirmed_events"] = [
                e for e in old.get("confirmed_events", []) if isinstance(e, str)
            ]
            self.s["test_speed"] = 1
            self.s["history_written"] = bool(old.get("history_written", False))
            for k in ("run_id", "started_at", "samples", "phase_log", "event_log"):
                self.s[k] = old.get(
                    k, [] if k.endswith("log") or k == "samples" else None
                )
            self.s["boil_confirmed"] = bool(old.get("boil_confirmed", False))
            self.s["wash_confirmed"] = bool(old.get("wash_confirmed", False))
            self.s["samples"] = self.s["samples"][-30000:]
            self.s["status"] = (
                "RECOVERY_REQUIRED"
                if old.get("status") in ("RUNNING", "PAUSED", "AWAIT_NEXT")
                else old.get("status", "IDLE")
            )
            self.s["phase"] = (
                "RECOVERY_REQUIRED"
                if self.s["status"] == "RECOVERY_REQUIRED"
                else old.get("phase", "")
            )
            valid = {e["id"]: e for e in self.s["recipe"]["events"]}
            pending_ids = old.get("pending_events", [])
            self.s["pending_events"] = [
                valid[e["id"]]
                for e in pending_ids
                if isinstance(e, dict)
                and e.get("id") in valid
                and (e["id"] not in self.s["confirmed_events"])
            ]
            self.s["message"] = (
                "Processo interrompido: saídas desligadas. Revise os avisos pendentes antes de retomar."
                if self.s["status"] == "RECOVERY_REQUIRED"
                else self.s["message"]
            )
        except (ValueError, KeyError, TypeError, OSError) as exc:
            print("Checkpoint inválido:", exc)

    def history(self, reason):
        if self.s["history_written"]:
            return
        record = {
            "id": self.s["run_id"] or uuid.uuid4().hex,
            "timestamp": self.s["started_at"] or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "recipe": self.s["recipe"]["name"],
            "recipe_id": self.s["recipe_id"],
            "result": reason,
            "confirmed_events": list(self.s["confirmed_events"]),
            "test_speed": self.s["test_speed"],
            "samples": list(self.s["samples"]),
            "phase_log": list(self.s["phase_log"]),
            "event_log": list(self.s["event_log"]),
        }
        with self.HISTORY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.s["history_written"] = True

    def mark_event(self, kind, detail=""):
        self.s["event_log"].append(
            {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "type": kind, "detail": detail}
        )

    def history_records(self):
        if not self.HISTORY.exists():
            return []
        result = []
        for line in self.HISTORY.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if isinstance(r, dict):
                    result.append(r)
            except ValueError:
                pass
        return result

    def sample(self):
        if (
            not self.s["run_id"]
            or self.s["history_written"]
            or self.s["status"]
            not in ("RUNNING", "PAUSED", "AWAIT_NEXT", "RECOVERY_REQUIRED")
        ):
            return
        now = time.time()
        if (
            self.s["samples"]
            and now - self.s["samples"][-1]["ts"] < self.settings["history_interval_s"]
        ):
            return
        step = self.s["recipe"]["steps"][self.s["step_index"]]
        self.s["samples"].append(
            {
                "ts": round(now, 1),
                "phase": step["name"],
                "step_index": self.s["step_index"],
                "temperature": self.s["temperature"],
                "target": (
                    self.settings["boil_reference_c"]
                    if step["kind"] == "boil"
                    else step["target"]
                ),
                "sensor_ok": self.s["sensor_ok"],
                "heater": self.s["heater"],
                "heater_requested": self.s["heater_requested"],
                "pump": self.s["pump"],
                "status": self.s["status"],
            }
        )
        self.s["samples"] = self.s["samples"][-30000:]
        self.save_checkpoint()
