from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

router = APIRouter()


class CurrentUserResponse(BaseModel):
    id: str
    email: EmailStr
    display_name: str


@router.get("/me", response_model=CurrentUserResponse)
async def get_current_user() -> CurrentUserResponse:
    return CurrentUserResponse(
        id="demo-user",
        email="lin@example.com",
        display_name="Lin",
    )


@router.post("/logout")
async def logout() -> dict[str, bool]:
    return {"ok": True}

