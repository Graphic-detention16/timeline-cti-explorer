from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from .clickhouse import ClickHouseRepository
from .config import Settings
from .state import StateStore

logger = structlog.get_logger()


class ComplianceError(RuntimeError):
    pass


class ComplianceRunner:
    def __init__(self, settings: Settings, state_store: StateStore) -> None:
        self.settings = settings
        self.state_store = state_store
        self.repository = ClickHouseRepository(
            settings,
            role="ingest",
            session_secret=settings.SESSION_SECRET.get_secret_value(),
        )

    def is_due(self) -> bool:
        raw = self.state_store.get_value("last_compliance_success")
        if not raw:
            return True
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            return True
        return datetime.now(UTC) - last > timedelta(hours=23)

    async def run_once(self) -> dict[str, int]:
        bearer = self.settings.X_BEARER_TOKEN.get_secret_value()
        if not bearer:
            raise ComplianceError("X_BEARER_TOKEN is required for batch compliance")
        post_ids = self.repository.list_x_post_ids()
        if not post_ids:
            self._mark_success(0)
            return {"checked": 0, "deleted": 0}

        headers = {"Authorization": f"Bearer {bearer}"}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.settings.X_API_BASE_URL}/2/compliance/jobs",
                headers={**headers, "Content-Type": "application/json"},
                json={"type": "tweets", "name": f"timeline-cti-{datetime.now(UTC):%Y%m%d}"},
            )
            if response.status_code >= 400:
                raise ComplianceError(f"compliance job creation failed: {response.status_code}")
            job = self._job_data(response.json())
            upload = await client.put(
                str(job["upload_url"]),
                content="\n".join(post_ids) + "\n",
                headers={"Content-Type": "text/plain"},
            )
            if upload.status_code >= 400:
                raise ComplianceError(f"compliance ID upload failed: {upload.status_code}")

            download_url = await self._wait_for_job(client, headers, str(job["id"]))
            result = await client.get(download_url)
            if result.status_code >= 400:
                raise ComplianceError(f"compliance result download failed: {result.status_code}")

        deleted_ids: list[str] = []
        for line in result.text.splitlines():
            try:
                event: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("action") == "delete" and event.get("id"):
                deleted_ids.append(str(event["id"]))
        self.repository.delete_posts(deleted_ids)
        self._mark_success(len(post_ids))
        self.state_store.audit(
            "compliance_complete",
            {"checked": len(post_ids), "deleted": len(deleted_ids)},
        )
        logger.info("compliance_complete", checked=len(post_ids), deleted=len(deleted_ids))
        return {"checked": len(post_ids), "deleted": len(deleted_ids)}

    async def _wait_for_job(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        job_id: str,
    ) -> str:
        for _ in range(120):
            await asyncio.sleep(10)
            response = await client.get(
                f"{self.settings.X_API_BASE_URL}/2/compliance/jobs/{job_id}",
                headers=headers,
            )
            if response.status_code >= 400:
                raise ComplianceError(f"compliance status check failed: {response.status_code}")
            job = self._job_data(response.json())
            if job.get("status") == "complete" and job.get("download_url"):
                return str(job["download_url"])
            if job.get("status") in {"failed", "expired"}:
                raise ComplianceError(f"compliance job ended with status {job.get('status')}")
        raise ComplianceError("compliance job timed out")

    @staticmethod
    def _job_data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ComplianceError("compliance response is malformed")
        return data

    def _mark_success(self, checked: int) -> None:
        self.state_store.set_value("last_compliance_success", datetime.now(UTC).isoformat())
        self.state_store.audit("compliance_success", {"checked": checked})
