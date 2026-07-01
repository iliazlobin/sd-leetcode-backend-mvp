"""Authentication service: login, password verification, token creation."""

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_access_token
from ..models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


async def authenticate_user(
    session: AsyncSession, username: str, password: str
) -> tuple[User, str] | None:
    """Authenticate a user by username and password.

    Returns (user, access_token) on success, None on failure.
    """
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(password, user.password_hash):
        return None

    token = create_access_token(
        user_id=str(user.user_id),
        username=user.username,
        role=user.role,
    )
    return user, token
