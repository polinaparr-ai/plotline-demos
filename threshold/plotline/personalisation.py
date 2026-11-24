"""Personalisation: how answers are shaped for each organisation and each user.

Two layers, deliberately kept apart:
  - Organisation house style (personalisation/house_style.yml) is operator-authored, so it goes
    into the cached system prompt.
  - A user's preset and own instructions are user-authored, so they travel in the user's turn
    inside <user_preferences>. They can change format, length and use of charts. They cannot
    override the data rules or the permission policy, which live above them in the system prompt
    and in plotline/policy.py.
"""
from __future__ import annotations

import pathlib

import yaml

from plotline import store

from plotline.paths import HOUSE_STYLE as STYLE
MAX_CUSTOM = 800


def config() -> dict:
    return yaml.safe_load(STYLE.read_text())


def house_style_prompt() -> str:
    c = config()
    rules = "\n".join(f"- {r}" for r in c["house_style"])
    return f"House style for {c['organisation']} (applies to every answer):\n{rules}"


def presets() -> dict:
    return config()["presets"]


def resolve(user: str) -> dict:
    c = config()
    saved = store.get_preferences(user) or {}
    key = saved.get("preset") if saved.get("preset") in c["presets"] else c["default_preset"]
    p = c["presets"][key]
    return {"preset": key, "label": p["label"], "instructions": p["instructions"],
            "custom": (saved.get("custom") or "").strip()[:MAX_CUSTOM]}


def save(user: str, preset: str, custom: str) -> dict:
    if preset not in presets():
        raise ValueError(f"Unknown preset {preset!r}")
    store.set_preferences(user, preset, (custom or "").strip()[:MAX_CUSTOM])
    return resolve(user)


def prompt_block(prefs: dict | None) -> str:
    if not prefs:
        return ""
    lines = [f"Preset: {prefs['label']}. {prefs['instructions']}"]
    if prefs.get("custom"):
        lines.append(f"My own instructions: {prefs['custom']}")
    return "<user_preferences>\n" + "\n".join(lines) + "\n</user_preferences>\n"
