"""Leitura e validação de receitas BeerXML."""

import xml.etree.ElementTree as ET


class RecipesMixin:

    def text(self, node, key, default=""):
        el = node.find(key)
        return (el.text or "").strip() if el is not None else default

    def recipe_load(self, path):
        root = ET.parse(path).getroot()
        r = root.find("RECIPE") if root.tag == "RECIPES" else root
        if r is None or r.tag != "RECIPE":
            raise ValueError("BeerXML sem RECIPE")
        steps = []
        for x in r.findall("./MASH/MASH_STEPS/MASH_STEP"):
            target = float(self.text(x, "STEP_TEMP"))
            minutes = float(self.text(x, "STEP_TIME"))
            if not 10 <= target <= 95 or not 0 < minutes <= 240:
                raise ValueError("Etapa inválida no BeerXML")
            steps.append(
                {
                    "name": self.text(x, "NAME", "Mostura"),
                    "kind": "mash",
                    "target": target,
                    "minutes": minutes,
                }
            )
        boil = float(self.text(r, "BOIL_TIME", "60"))
        if not 0 < boil <= 240:
            raise ValueError("Fervura inválida")
        steps.append(
            {"name": "Fervura", "kind": "boil", "target": None, "minutes": boil}
        )
        events = []
        for x in r.findall("./MISCS/MISC"):
            if self.text(x, "TYPE").lower() == "water agent":
                events.append(
                    {
                        "id": "salt-" + str(len(events)),
                        "name": self.text(x, "NAME"),
                        "amount": self.text(x, "DISPLAY_AMOUNT")
                        or str(float(self.text(x, "AMOUNT", "0")) * 1000) + " g",
                        "phase": self.text(x, "USE"),
                        "at_remaining": None,
                    }
                )
        for x in r.findall("./HOPS/HOP"):
            if self.text(x, "USE").lower() == "boil":
                events.append(
                    {
                        "id": "boil-" + str(len(events)),
                        "name": self.text(x, "NAME"),
                        "amount": str(
                            round(float(self.text(x, "AMOUNT", "0")) * 1000, 2)
                        )
                        + " g",
                        "phase": "Boil",
                        "at_remaining": float(self.text(x, "TIME", "0")),
                    }
                )
        if not self.text(r, "NAME"):
            raise ValueError("Receita sem nome")
        return {
            "name": self.text(r, "NAME"),
            "batch_l": float(self.text(r, "BATCH_SIZE", "0")),
            "steps": steps,
            "events": events,
            "source": path.name,
        }
