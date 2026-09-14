from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.ai import AvalAIClient
from app.bale import BaleClient
from app.config import Settings
from app.db import init_db, make_engine
from app.web import register_routes
from app.worker import scheduler_loop


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings
    configuration_error = None
    if settings is not None:
        resolved_settings = settings
    else:
        try:
            resolved_settings = Settings.from_env()
        except Exception as exc:
            configuration_error = exc

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        error = getattr(app.state, "configuration_error", None)
        if error is not None:
            raise error
        worker = asyncio.create_task(scheduler_loop(app))
        try:
            yield
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            for client_name in ("bale", "ai"):
                client = getattr(app.state, client_name, None)
                if client is not None and hasattr(client, "close"):
                    await client.close()

    app = FastAPI(title="Self Assistant", lifespan=lifespan)
    if resolved_settings is not None:
        app.state.settings = resolved_settings
        app.state.engine = make_engine(resolved_settings.database_path)
        init_db(app.state.engine)
        app.state.bale = BaleClient(resolved_settings.bale_bot_token)
        app.state.ai = AvalAIClient(
            resolved_settings.avalai_api_key,
            resolved_settings.avalai_transcribe_model,
            resolved_settings.avalai_text_model,
        )
    else:
        app.state.configuration_error = configuration_error

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    register_routes(app)
    return app


app = create_app()
