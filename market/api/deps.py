"""
deps.py — FastAPI shared dependencies.

Authentication strategy (v1 — simple):
  The caller passes their user ID in the `X-User-Id` request header.
  The server looks it up in the DB and returns the User object.

  This is intentionally simple for now — no passwords, no JWT, no OAuth.
  The pattern is easy to swap out: replace `get_current_user` with a
  proper JWT decoder later and nothing else in the codebase changes.

Usage in a route:
    async def buy(current_user: User = Depends(get_current_user), ...):
        ...  current_user is a fully loaded User ORM object
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from market.db.models import User
from market.db.session import get_db


async def get_current_user(
    x_user_id: str = Header(
        ...,
        alias="X-User-Id",
        description="Your user ID (UUID). Create one at  POST /users.",
    ),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Resolve the `X-User-Id` header to a User row.
    Raises 401 if the header is missing or the ID doesn't exist.
    """
    result = await db.execute(select(User).where(User.id == x_user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=401,
            detail=(
                f"User '{x_user_id}' not found. "
                "Create an account first at  POST /users."
            ),
        )
    return user
