"""Incoming payload models.

Deliberately flexible while the collector schema is still changing:
- only a few fields are required (machine id or hostname, software/process/service name, port number)
- any unknown field is accepted and stored in the row's `extra` JSONB column
"""
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Flexible(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    def known(self) -> dict:
        return self.model_dump(exclude=set(self.model_extra or {}))

    def extra_fields(self) -> dict | None:
        return dict(self.model_extra) if self.model_extra else None


class MachineIn(_Flexible):
    id: uuid.UUID | None = None
    hostname: str | None = None
    os: str | None = None

    @model_validator(mode="after")
    def _id_or_hostname(self):
        if self.id is None and not self.hostname:
            raise ValueError("machine needs an 'id' or a 'hostname'")
        return self


class SoftwareIn(_Flexible):
    name: str = Field(min_length=1)
    version: str | None = None
    publisher: str | None = None


class PortIn(_Flexible):
    protocol: str | None = None
    local_address: str | None = None
    port: int = Field(ge=0, le=65535)
    pid: int | None = None
    process_name: str | None = None
    path: str | None = None
    version: str | None = None


class ProcessIn(_Flexible):
    name: str = Field(min_length=1)
    pid: int | None = None
    path: str | None = None
    version: str | None = None


class ServiceIn(_Flexible):
    name: str = Field(min_length=1)
    display_name: str | None = None
    status: str | None = None
    start_type: str | None = None


class InventoryIn(_Flexible):
    """One delivery for one machine. Every section is optional; a missing section is left untouched."""

    collected_at: datetime | None = None
    machine: MachineIn
    installed_software: list[SoftwareIn] | None = None
    listening_ports: list[PortIn] | None = None
    processes: list[ProcessIn] | None = None
    services: list[ServiceIn] | None = None

    @field_validator("collected_at")
    @classmethod
    def _assume_utc(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
