"""Auth router: POST /auth/token (login)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..schemas.auth import TokenRequest, TokenResponse
from ..services.auth_service import authenticate_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(
    body: TokenRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Authenticate user and return JWT access token."""
    result = await authenticate_user(session, body.username, body.password)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    user, token = result
    return TokenResponse(
        access_token=token,
        user_id=str(user.user_id),
        role=user.role,
    )
