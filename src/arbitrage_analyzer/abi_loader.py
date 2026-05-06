from dotenv import load_dotenv
import os
import json
from pathlib import Path
from functools import lru_cache


load_dotenv()
ABI_DIR = os.getenv("ABI_DIR")


def _get_abi_dir() -> Path:
    path = Path(ABI_DIR)

    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.exists():
        raise FileNotFoundError(f"ABI directory not found: {path}")

    return path


@lru_cache(maxsize=128)
def load_abi(name: str) -> list[dict]:
    abi_dir = _get_abi_dir()
    path = abi_dir / f"{name}.json"

    if not path.exists():
        raise FileNotFoundError(f"ABI not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)