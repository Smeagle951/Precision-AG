# -*- coding: utf-8 -*-
"""Modelos estruturados para inspecao, validacao e importacao."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


VALID = "VALID"
VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
INVALID = "INVALID"


@dataclass
class ValidationMessage:
    severity: str
    code: str
    message: str
    feature_id: str | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class InputInspectionReport:
    source_path: str
    format: str | None = None
    driver: str | None = None
    layers: list[dict] = field(default_factory=list)
    crs_authid: str | None = None
    geometry_type: str | None = None
    feature_count: int | None = None
    fields: list[str] = field(default_factory=list)
    extent: dict = field(default_factory=dict)
    encoding: str | None = None
    components: list[str] = field(default_factory=list)
    checksum_sha256: str | None = None
    file_size_bytes: int | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class InputValidationReport:
    status: str
    inspection: InputInspectionReport
    messages: list[ValidationMessage] = field(default_factory=list)

    @property
    def errors(self):
        return [msg for msg in self.messages if msg.severity == "error"]

    @property
    def warnings(self):
        return [msg for msg in self.messages if msg.severity == "warning"]

    def to_dict(self):
        return {
            "status": self.status,
            "inspection": self.inspection.to_dict(),
            "messages": [msg.to_dict() for msg in self.messages],
            "errors": [msg.to_dict() for msg in self.errors],
            "warnings": [msg.to_dict() for msg in self.warnings],
        }


@dataclass
class ImportResult:
    status: str
    source_id: str | None
    operation_id: str | None
    output_layer: str | None
    report: dict
    validation: InputValidationReport

    def to_dict(self):
        return {
            "status": self.status,
            "source_id": self.source_id,
            "operation_id": self.operation_id,
            "output_layer": self.output_layer,
            "report": self.report,
            "validation": self.validation.to_dict(),
        }

