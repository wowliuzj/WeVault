import asyncio
import contextlib

from app.core.config import settings
from app.services.task_worker import run_worker_loop


async def main() -> None:
    print(
        f"[worker] starting, poll_interval={settings.worker_poll_interval_seconds}s",
        flush=True,
    )
    await run_worker_loop(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
