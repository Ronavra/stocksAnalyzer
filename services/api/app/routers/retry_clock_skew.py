from asyncio import sleep
import logging

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute
from postgrest.exceptions import APIError


logger = logging.getLogger(__name__)


class RetryClockSkewRoute(APIRoute):
    """Retry read-only requests when PostgREST temporarily rejects a fresh JWT."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def retry_handler(request: Request) -> Response:
            delays = (0, 1, 2, 4)
            for attempt, delay in enumerate(delays):
                if delay:
                    await sleep(delay)
                try:
                    return await handler(request)
                except APIError as exc:
                    if (
                        request.method != "GET"
                        or exc.code != "PGRST303"
                        or exc.message != "JWT issued at future"
                    ):
                        raise
                    if attempt == len(delays) - 1:
                        logger.warning("Supabase clock-skew rejection persisted after %s attempts", len(delays))
                        raise HTTPException(
                            status_code=503,
                            detail="Data provider temporarily unavailable. Please try again shortly.",
                            headers={"Retry-After": "5"},
                        ) from exc
                    logger.warning("Supabase clock-skew rejection; retrying GET %s", request.url.path)

            raise AssertionError("Unreachable")

        return retry_handler
