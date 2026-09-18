from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TEMPLATE_PATH = (
    PROJECT_ROOT
    / "templates"
    / "Investment_Analysis_Automated_Template.xlsx"
)


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str
    twelve_data_api_key: str
    default_quarters: int = 20

    @property
    def is_ready(self) -> bool:
        return (
            "@" in self.sec_user_agent
            and bool(self.twelve_data_api_key)
            and self.twelve_data_api_key != "replace_with_your_key"
        )


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    try:
        default_quarters = int(
            os.getenv("DEFAULT_QUARTERS", "20")
        )
    except ValueError:
        default_quarters = 20

    return Settings(
        sec_user_agent=os.getenv(
            "SEC_USER_AGENT",
            "",
        ).strip(),
        twelve_data_api_key=os.getenv(
            "TWELVE_DATA_API_KEY",
            "",
        ).strip(),
        default_quarters=max(
            4,
            min(default_quarters, 40),
        ),
    )