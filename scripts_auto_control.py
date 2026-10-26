"""Contrôle partagé et persistant des scripts automatiques de KataBump."""
import json
import os
import threading
from pathlib import Path

STATE_FILE = Path(os.environ.get("SCRIPTS_AUTO_STATE_FILE", "scripts_auto_state.json"))
_CONDITION = threading.Condition()
_ENABLED = True


def _read_state():
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("enabled", True))
    except (OSError, ValueError, TypeError):
        return True


def _save_state(enabled: bool) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({"enabled": bool(enabled)}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError as exc:
        print(f"[scripts_auto] Impossible de sauvegarder l'état : {exc}")


_ENABLED = _read_state()


def is_enabled() -> bool:
    with _CONDITION:
        return _ENABLED


def set_enabled(enabled: bool) -> bool:
    """Enregistre le nouvel état, réveille les boucles, retourne l'état final."""
    global _ENABLED
    with _CONDITION:
        _ENABLED = bool(enabled)
        _save_state(_ENABLED)
        _CONDITION.notify_all()
        return _ENABLED


def toggle() -> bool:
    global _ENABLED
    with _CONDITION:
        _ENABLED = not _ENABLED
        _save_state(_ENABLED)
        _CONDITION.notify_all()
        return _ENABLED


def wait_until_enabled() -> None:
    """Attend sans consommer de boucle tant que les scripts sont désactivés."""
    with _CONDITION:
        while not _ENABLED:
            _CONDITION.wait()


def wait_or_disabled(seconds: float) -> bool:
    """Attend une durée active. Retourne False dès que les scripts sont coupés.

    Si une pause est demandée, le temps restant est conservé et reprend à la
    réactivation. Cela permet notamment d'interrompre une très longue pause.
    """
    remaining = max(0.0, float(seconds))
    with _CONDITION:
        while remaining > 0:
            while not _ENABLED:
                _CONDITION.wait()
            # La Condition se réveille sur activation/désactivation ou délai.
            import time
            started = time.monotonic()
            _CONDITION.wait(timeout=remaining)
            elapsed = time.monotonic() - started
            if not _ENABLED:
                remaining = max(0.0, remaining - elapsed)
                return False
            remaining = max(0.0, remaining - elapsed)
        return _ENABLED
