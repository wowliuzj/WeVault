from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.admin import Admin
from app.models.enums import UserStatus


async def ensure_configured_admin(db: AsyncSession) -> None:
    if not settings.admin_email or not settings.admin_password:
        return

    email = settings.admin_email.strip().lower()
    if not email:
        return

    result = await db.execute(select(Admin).where(Admin.email == email))
    admin = result.scalar_one_or_none()
    if admin is None:
        admin = Admin(
            email=email,
            password_hash=hash_password(settings.admin_password),
            display_name=settings.admin_display_name or email.split("@")[0],
            status=UserStatus.ACTIVE,
        )
    else:
        admin.password_hash = hash_password(settings.admin_password)
        admin.display_name = settings.admin_display_name or admin.display_name
        if admin.status == UserStatus.DISABLED:
            admin.status = UserStatus.ACTIVE

    db.add(admin)
    await db.commit()
