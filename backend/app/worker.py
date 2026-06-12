import argparse
import asyncio
import contextlib

from app.core.config import settings
from app.services.task_worker import run_worker_loop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WeVault background worker.")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=settings.worker_poll_interval_seconds,
        help="Seconds to wait between empty queue polls.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=settings.worker_concurrency,
        help="Number of concurrent worker slots in this process.",
    )
    parser.add_argument(
        "--queue",
        default=settings.worker_queue,
        choices=("all", "fetch", "export"),
        help="Task queue to consume.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    print(
        "[worker] boot "
        f"queue={args.queue} concurrency={max(1, args.concurrency)} "
        f"poll_interval={args.poll_interval}s",
        flush=True,
    )
    await run_worker_loop(
        args.poll_interval,
        concurrency=args.concurrency,
        queue=args.queue,
    )


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
