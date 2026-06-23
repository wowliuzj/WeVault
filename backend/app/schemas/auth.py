from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)
    invite_code: str = Field(min_length=1, max_length=80)
    turnstile_token: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    turnstile_token: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    display_name: str | None
    status: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
