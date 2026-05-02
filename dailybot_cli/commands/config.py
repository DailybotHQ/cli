"""Configuration command for Dailybot CLI."""

import click

from dailybot_cli.config import load_config, save_config
from dailybot_cli.display import print_error, print_info, print_success

KNOWN_SETTINGS: dict[str, str] = {
    "key": "api_key",
}


def _mask(value: str) -> str:
    """Mask all but the first 4 characters."""
    if len(value) <= 4:
        return value[0] + "****" if value else "****"
    return value[:4] + "****"


@click.command(name="config")
@click.argument("setting")
def config(setting: str) -> None:
    """Get, set, or remove a stored setting.

    \b
      dailybot config key=abc123   # Save API key
      dailybot config key          # Show current API key (masked)
      dailybot config key=         # Remove stored API key
    """
    if "=" in setting:
        name, value = setting.split("=", 1)
    else:
        name = setting
        value = None

    if name not in KNOWN_SETTINGS:
        print_error(f"Unknown setting '{name}'. Available: {', '.join(KNOWN_SETTINGS)}")
        raise SystemExit(1)

    config_key: str = KNOWN_SETTINGS[name]

    # Show current value
    if value is None:
        current: str | None = load_config().get(config_key)
        if current:
            print_info(f"{name}: {_mask(current)}")
        else:
            print_info(f"{name}: not set")
        return

    # Remove value
    if value == "":
        save_config({config_key: None})
        print_success("API key removed.")
        return

    # Save value
    save_config({config_key: value})
    print_success(f"API key saved ({_mask(value)})")
