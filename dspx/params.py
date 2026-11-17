"""Parameter declarations independent of the engine's registration table."""


def _f(pid, unit, lo, hi, default, desc):
    return {"id": pid, "type": "float", "unit": unit, "min": lo, "max": hi,
            "default": default, "description": desc}


def _i(pid, unit, lo, hi, default, desc):
    return {"id": pid, "type": "int", "unit": unit, "min": lo, "max": hi,
            "default": default, "description": desc}


def _e(pid, choices, default, desc, unit=None):
    return {"id": pid, "type": "enum", "unit": unit, "choices": list(choices),
            "default": default, "description": desc}


def _b(pid, default, desc):
    return {"id": pid, "type": "bool", "unit": None, "default": default, "description": desc}


def _a(pid, unit, lo, hi, max_len, default, desc):
    return {"id": pid, "type": "float_array", "unit": unit, "min": lo, "max": hi,
            "max_len": max_len, "default": list(default), "description": desc}
