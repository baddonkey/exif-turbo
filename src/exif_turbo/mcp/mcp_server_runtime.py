from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from mcp.server import MCPServer

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpListenEndpoint:
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"


class McpServerRuntime:
    """Run an MCP Streamable HTTP server on a background thread."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._endpoint: McpListenEndpoint | None = None
        self._error: str = ""
        self._uvicorn_server: Any | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def endpoint(self) -> McpListenEndpoint | None:
        return self._endpoint

    @property
    def error(self) -> str:
        return self._error

    def start(self, server: MCPServer[Any], host: str, port: int) -> None:
        with self._lock:
            self.stop()
            self._stop_event.clear()
            self._ready_event.clear()
            self._error = ""
            self._endpoint = McpListenEndpoint(host=host, port=port)
            thread = threading.Thread(
                target=self._run,
                name="exif-turbo-mcp-server",
                args=(server, host, port),
                daemon=True,
            )
            self._thread = thread
            thread.start()
            # Wait briefly for bind success/failure so settings UI can show status.
            self._ready_event.wait(timeout=5.0)

    def stop(self) -> None:
        thread = self._thread
        uvicorn_server = self._uvicorn_server
        self._stop_event.set()
        if uvicorn_server is not None:
            uvicorn_server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._thread = None
        self._uvicorn_server = None
        self._endpoint = None

    def _run(self, server: MCPServer[Any], host: str, port: int) -> None:
        import anyio
        import uvicorn

        try:
            starlette_app = server.streamable_http_app(
                streamable_http_path="/mcp",
                host=host,
            )
            config = uvicorn.Config(
                starlette_app,
                host=host,
                port=port,
                log_level="warning",
            )
            uvicorn_server = uvicorn.Server(config)
            self._uvicorn_server = uvicorn_server

            async def _serve() -> None:
                self._ready_event.set()
                await uvicorn_server.serve()

            anyio.run(_serve)
        except Exception as exc:  # noqa: BLE001
            _log.exception("MCP server failed on %s:%s", host, port)
            self._error = str(exc)
            self._ready_event.set()
        finally:
            self._uvicorn_server = None
