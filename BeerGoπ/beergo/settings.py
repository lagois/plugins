"""Validação e persistência das configurações operacionais."""

import json, os


class SettingsMixin:

    def validate_settings(self, data):
        if not isinstance(data, dict):
            raise ValueError("Configurações inválidas")
        result = {}
        for key, default in self.SETTINGS_DEFAULTS.items():
            v = data.get(key, default)
            if isinstance(default, bool):
                if type(v) is not bool:
                    raise ValueError("Valor booleano inválido: " + key)
            else:
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ValueError("Valor numérico inválido: " + key)
                lo, hi = self.SETTINGS_LIMITS[key]
                if not lo <= v <= hi:
                    raise ValueError("%s deve ficar entre %s e %s" % (key, lo, hi))
                if isinstance(default, int) and (not isinstance(default, bool)):
                    if int(v) != v:
                        raise ValueError("Informe um inteiro para " + key)
                    v = int(v)
            result[key] = v
        return result

    def save_settings(self, data):
        self.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.SETTINGS_FILE.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, self.SETTINGS_FILE)
