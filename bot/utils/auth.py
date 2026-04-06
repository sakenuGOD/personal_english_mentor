from __future__ import annotations


async def get_user_api_key(user_id: int) -> str | None:
    """Kept for backward compatibility. Global key is used now."""
    return "global"


NO_KEY_TEXT = ""
