import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .live import LiveService
from .logging import configure
from .service import ResearchService, feature_contracts


def create_app(*, data_dir: Path | None = None, bootstrap_steps=150, stream=True, live_factory=LiveService):
    @asynccontextmanager
    async def lifespan(app):
        mode = os.getenv("VN30_MODE", "MOCK").upper()
        if mode not in {"MOCK", "LIVE"}:
            raise RuntimeError("VN30_MODE must be MOCK or LIVE")
        configure()
        app.state.runtime_mode = mode
        if mode == "LIVE":
            service = live_factory()
            app.state.research = service
            task = asyncio.create_task(service.start()) if stream else None
        else:
            service = ResearchService(data_dir or Path(os.getenv("VN30_DATA_DIR", ".data")))
            app.state.research = service
            service.bootstrap(bootstrap_steps)
            interval = float(os.getenv("VN30_REPLAY_INTERVAL", "0.8"))
            if interval <= 0:
                raise ValueError("positive replay interval required")
            task = asyncio.create_task(service.run(interval)) if stream else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if mode == "MOCK":
                try:
                    service.journal.export()
                finally:
                    service.journal.close()

    app = FastAPI(title="VN30 Research Observatory", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "mode": app.state.runtime_mode}

    @app.get("/api/health")
    def health():
        return app.state.research.feed_quality()

    @app.get("/api/state")
    def state():
        return app.state.research.state()

    @app.get("/api/instruments")
    def instruments():
        service = app.state.research
        return (
            service.instruments if isinstance(service, ResearchService) else [service.state()["instrument"]]
        )

    @app.get("/api/features/definitions")
    def definitions():
        return feature_contracts()

    @app.get("/api/events")
    def events():
        service = app.state.research
        return service.manager.events if isinstance(service, ResearchService) else []

    @app.websocket("/api/stream")
    async def market_stream(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                await ws.send_json(app.state.research.state())
                await asyncio.sleep(0.8)
        except (WebSocketDisconnect, RuntimeError, OSError):
            return

    return app


app = create_app()
