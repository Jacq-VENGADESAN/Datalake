from __future__ import annotations

import json
from typing import Annotated

from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from src import __version__
from src.config import get_settings
from src.dependencies import get_service
from src.logging_config import configure_logging
from src.models import AlertLevel, IngestRequest, IngestResponse, PaginatedResponse
from src.services import DataLakeService

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="VelibPulse API Gateway",
    description=(
        "Interface des zones raw, staging et curated du data lake de mobilite de "
        "Jacq VENGADESAN (BDML2)."
    ),
    version=__version__,
)

Service = Annotated[DataLakeService, Depends(get_service)]


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {
        "project": settings.project_name,
        "author": "Jacq VENGADESAN",
        "class": "BDML2",
        "documentation": "/docs",
    }


@app.get("/health", tags=["monitoring"])
def health(service: Service) -> JSONResponse:
    result = service.health()
    code = (
        status.HTTP_200_OK
        if result["status"] == "healthy"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(result, status_code=code)


@app.get("/stats", tags=["monitoring"])
def stats(service: Service) -> dict:
    return service.stats()


@app.get("/raw", tags=["data"])
def raw(
    service: Service,
    prefix: str = Query(default="", max_length=255),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    try:
        objects = service.store.list_objects(prefix=prefix, limit=limit)
    except ClientError as exc:
        raise HTTPException(status_code=503, detail=f"Zone raw indisponible: {exc}") from exc
    return {
        "items": [
            {
                "key": item.key,
                "size": item.size,
                "last_modified": item.last_modified.isoformat() if item.last_modified else None,
                "etag": item.etag,
            }
            for item in objects
        ],
        "returned": len(objects),
    }


@app.get("/raw/{key:path}", tags=["data"])
def raw_object(key: str, service: Service) -> Response:
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise HTTPException(status_code=400, detail="Cle raw invalide")
    try:
        content = service.store.get_bytes(key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        code = 404 if error_code in {"NoSuchKey", "404"} else 503
        raise HTTPException(status_code=code, detail="Objet raw introuvable") from exc
    if key.endswith(".json"):
        try:
            return JSONResponse(json.loads(content))
        except json.JSONDecodeError:
            pass
    media_type = "text/csv; charset=utf-8" if key.endswith(".csv") else "application/octet-stream"
    return Response(content=content, media_type=media_type)


@app.get("/staging", response_model=PaginatedResponse, tags=["data"])
def staging(
    service: Service,
    station_code: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    items = service.database.get_staging(limit, offset, station_code)
    return PaginatedResponse(items=items, limit=limit, offset=offset, returned=len(items))


@app.get("/curated", response_model=PaginatedResponse, tags=["data"])
def curated(
    service: Service,
    station_code: str | None = Query(default=None, max_length=32),
    alert_level: AlertLevel | None = None,
    limit: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    items = service.database.get_curated(
        limit, offset, station_code, alert_level.value if alert_level else None
    )
    return PaginatedResponse(items=items, limit=limit, offset=offset, returned=len(items))


@app.post("/ingest", response_model=IngestResponse, status_code=201, tags=["advanced"])
def ingest(request: IngestRequest, service: Service) -> IngestResponse:
    """Pipeline pedagogique ligne par ligne, utilise comme baseline de performance."""
    return service.ingest_gateway(request.data, fast=False)


@app.post("/ingest_fast", response_model=IngestResponse, status_code=201, tags=["advanced"])
@app.post(
    "/ingest/fast",
    response_model=IngestResponse,
    status_code=201,
    include_in_schema=False,
)
def ingest_fast(request: IngestRequest, service: Service) -> IngestResponse:
    """Pipeline vectorise avec ecritures batch, optimise pour les lots."""
    return service.ingest_gateway(request.data, fast=True)
