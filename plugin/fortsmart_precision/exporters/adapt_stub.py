# -*- coding: utf-8 -*-
"""Stub ADAPT — fora do nucleo geometrico; sem compatibilidade declarada com monitor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class AdaptExportError(NotImplementedError):
    """Exportacao ADAPT ainda nao implementada."""


@dataclass(frozen=True)
class AdaptExportRequest:
    project_dir: Path
    target: str = "john_deere"

    def validate(self) -> None:
        if not self.project_dir.exists():
            raise AdaptExportError("Diretorio do projeto inexistente.")


def export_to_adapt(request: AdaptExportRequest) -> None:
    """Placeholder: transformacao geometria agronomica -> prescricao ADAPT.

    Nao declarar compatibilidade com monitor sem evidencia de teste em campo.
    """
    request.validate()
    raise AdaptExportError(
        "Exportacao ADAPT nao disponivel nesta versao. "
        "Use GeoJSON/GeoPackage e valide manualmente no equipamento alvo."
    )
