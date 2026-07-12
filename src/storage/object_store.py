from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.config import Config

from src.config import Settings


@dataclass(frozen=True)
class RawObject:
    key: str
    size: int
    last_modified: datetime | None
    etag: str | None


class ObjectStore:
    """Acces minimal a la zone raw S3/MinIO."""

    def __init__(self, settings: Settings, client: BaseClient | None = None) -> None:
        self.settings = settings
        self.bucket = settings.s3_raw_bucket
        self.client = client or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def ensure_bucket(self) -> None:
        existing = {bucket["Name"] for bucket in self.client.list_buckets().get("Buckets", [])}
        if self.bucket not in existing:
            self.client.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, content: bytes, content_type: str) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
            Metadata={"ingested-at": datetime.now(UTC).isoformat()},
        )
        return key

    def put_json(self, key: str, payload: Any) -> str:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        return self.put_bytes(key, body, "application/json")

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def list_objects(
        self, prefix: str = "", limit: int = 100, offset: int = 0
    ) -> list[RawObject]:
        """Liste les objets raw avec une pagination limit/offset stable cote API."""
        result: list[RawObject] = []
        skipped = 0
        paginator = self.client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                if skipped < offset:
                    skipped += 1
                    continue

                result.append(
                    RawObject(
                        key=item["Key"],
                        size=item["Size"],
                        last_modified=item.get("LastModified"),
                        etag=item.get("ETag", "").strip('"') or None,
                    )
                )
                if len(result) >= limit:
                    return result

        return result

    def stats(self) -> dict[str, int]:
        count = size = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            for item in page.get("Contents", []):
                count += 1
                size += int(item["Size"])
        return {"objects": count, "bytes": size}

    def ping(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)
