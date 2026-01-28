"""
Location: /mnt/f/Code/discordbot/health_check.py
Summary: Lightweight HTTP health check server for Docker/Railway deployment monitoring.
         Exposes a GET /health endpoint that reports Discord bot connection status,
         allowing orchestration platforms to detect hung or disconnected processes.

Used by: main.py (started during bot on_ready, stopped during bot close).
Uses: aiohttp.web for the HTTP server, the bot instance for connection status.
"""

import logging
import os
from aiohttp import web

logger = logging.getLogger(__name__)

# Default port for the health check server, configurable via environment variable.
DEFAULT_HEALTH_CHECK_PORT = 8080


class HealthCheckServer:
    """Minimal HTTP server that exposes a /health endpoint for container health checks.

    The server runs as a background task on the bot's event loop and reports whether
    the Discord bot is connected and responsive. It is designed to be non-intrusive:
    it binds only to localhost by default and serves a single endpoint.

    Args:
        bot: The Discord bot instance. Must support ``is_ready()`` and ``latency``
             attributes (standard for discord.py ``commands.Bot``).
        host: The address to bind the HTTP server to. Defaults to "0.0.0.0" so
              Docker HEALTHCHECK instructions and external probes can reach it.
        port: The port to listen on. Defaults to the ``HEALTH_CHECK_PORT``
              environment variable, or 8080 if not set.
    """

    def __init__(self, bot, host: str = "0.0.0.0", port: int = None):
        self.bot = bot
        self.host = host
        self.port = port or int(
            os.environ.get("HEALTH_CHECK_PORT", DEFAULT_HEALTH_CHECK_PORT)
        )
        self._runner = None
        self._site = None

    async def _health_handler(self, request: web.Request) -> web.Response:
        """Handle GET /health requests.

        Returns:
            200 with status payload when the bot is connected to Discord.
            503 with unhealthy payload when the bot is not ready.
        """
        is_connected = self.bot.is_ready()

        if is_connected:
            latency_ms = round(self.bot.latency * 1000, 2)
            payload = {
                "status": "healthy",
                "discord_connected": True,
                "latency_ms": latency_ms,
            }
            return web.json_response(payload, status=200)

        payload = {
            "status": "unhealthy",
            "discord_connected": False,
        }
        return web.json_response(payload, status=503)

    async def start(self) -> None:
        """Create and start the aiohttp web server as a background service.

        This method sets up the application, adds the /health route, and starts
        the server without blocking the caller. It is safe to call from within
        an already-running asyncio event loop (e.g., the bot's on_ready hook).
        """
        app = web.Application()
        app.router.add_get("/health", self._health_handler)

        self._runner = web.AppRunner(app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        logger.info("Health check server started on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Gracefully shut down the health check server.

        Cleans up the aiohttp AppRunner and associated resources. Safe to call
        even if the server was never started (e.g., during error recovery).
        """
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.info("Health check server stopped")
