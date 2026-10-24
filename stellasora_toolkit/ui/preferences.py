"""Local appearance preferences, separate from per-account gacha archives."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .beta_styles import VARIANTS

SETTINGS_FILENAME = 'ui_settings.json'
DEFAULT_THEME = 'sky'
AUTOMATION_DEFAULTS = {'auto_upload': False, 'auto_update': True}


def _read_settings(output: Path) -> dict:
    try:
        settings = json.loads((Path(output)/SETTINGS_FILENAME).read_text(encoding='utf-8'))
        return settings if isinstance(settings,dict) else {}
    except (OSError,ValueError):
        return {}


def load_theme(output: Path) -> str:
    theme = _read_settings(output).get('theme')
    return theme if isinstance(theme,str) and theme in VARIANTS else DEFAULT_THEME


def save_theme(output: Path,theme: str) -> bool:
    if not isinstance(theme,str) or theme not in VARIANTS:
        raise ValueError(f'Unknown theme: {theme}')
    return _save_settings(output, {'theme': theme})


def load_automation(output: Path) -> dict[str, bool]:
    settings = _read_settings(output)
    return {key: settings[key] if type(settings.get(key)) is bool else default
            for key, default in AUTOMATION_DEFAULTS.items()}


def save_automation(output: Path, key: str, enabled: bool) -> bool:
    if key not in AUTOMATION_DEFAULTS or type(enabled) is not bool:
        raise ValueError('Invalid automation preference')
    return _save_settings(output, {key: enabled})


def load_pool_columns(output: Path) -> int | None:
    value = _read_settings(output).get('pool_columns')
    return value if type(value) is int and value in (1, 2) else None


def save_pool_columns(output: Path, value: int | None) -> bool:
    if value is not None and (type(value) is not int or value not in (1, 2)):
        raise ValueError('卡池列数只能为自动、一列或两列')
    return _save_settings(output, {'pool_columns': value})


def _save_settings(output: Path, changes: dict) -> bool:
    output = Path(output)
    temporary = None
    try:
        settings = _read_settings(output)
        settings.update(changes)
        output.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output,
                                         prefix='.ui-settings-',suffix='.tmp',delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(settings,handle,ensure_ascii=False,indent=2)
            handle.write('\n')
        temporary.replace(output/SETTINGS_FILENAME)
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
