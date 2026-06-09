import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logger import bind_request_context, get_logger, log_event


logger = get_logger(service="http").bind(log_sink="access")


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        bind_request_context(request_id=request_id)

        try:
            response = await call_next(request)
        except Exception as e:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            log_event(
                logger,
                "ERROR",
                "http_request_error",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                elapsed_ms=elapsed_ms,
                reason=str(e),
            )
            raise
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        client = f"{request.client.host}:{request.client.port}" if request.client else "-"
        response.headers["X-Request-ID"] = request_id

        log_event(
            logger,
            "INFO",
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            client=client,
        )

        return response
