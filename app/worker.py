from __future__ import annotations

import asyncio
import logging

from app.db import session_scope
from app.jobs import run_digest_once
from app.scheduler import run_scheduler_once

logger = logging.getLogger(__name__)


async def scheduler_loop(app, interval_seconds: int = 60) -> None:
    """Small single-process worker suitable for one Coolify replica."""
    while True:
        try:
            with session_scope(app.state.engine) as session:
                await run_scheduler_once(session, app.state.bale)
                await run_digest_once(session, app.state.bale)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduled assistant work failed")
        await asyncio.sleep(interval_seconds)
