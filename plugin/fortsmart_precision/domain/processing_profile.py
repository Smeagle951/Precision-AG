# -*- coding: utf-8 -*-
"""Perfil de processamento: Rapido (preview) x Precisao (final).

A otimizacao aqui e ALGORITMICA, nunca agronomica. Os dois modos usam:

- o mesmo limite real do talhao (nunca bounding box);
- o mesmo offset de bordadura (W/2);
- o mesmo raio operacional de desvio (raio_obstaculo + W/2 + margem);
- a mesma margem de seguranca e o mesmo raio minimo de giro.

O que muda entre eles e apenas a **resolucao da amostragem** e **quanto
trabalho derivado e materializado**:

    Rapido   -> arcos com menos vertices, validacao amostrada, sem
                materializar as N linhas virtuais da plantadeira.
    Precisao -> arcos refinados, validacao completa, linhas virtuais,
                cruzamento linha x pneu e todos os segmentos ON/OFF.

Nenhum modo remove obstaculos, reduz margem, encurta o raio de desvio ou
descarta passadas. Um obstaculo detectado no modo Rapido continua sendo
detectado no modo Precisao — a diferenca esta no numero de pontos usados
para desenhar a trajetoria, nao na decisao de desviar.
"""

from __future__ import annotations

from dataclasses import dataclass

PREVIEW = "preview"
FINAL = "final"


class ProcessingProfileError(ValueError):
    """Erro na configuracao do perfil de processamento."""


@dataclass(frozen=True)
class ProcessingProfile:
    """Resolucao e escopo de calculo de uma geracao."""

    mode: str = FINAL
    arc_segments: int = 48
    max_pass_points: int = 480
    boundary_max_vertices: int = 720
    validation_sample: int = 0  # 0 = valida tudo
    materialize_virtual_rows: bool = True
    compute_shutoff: bool = True

    def validate(self) -> None:
        if self.mode not in {PREVIEW, FINAL}:
            raise ProcessingProfileError("Modo deve ser 'preview' ou 'final'.")
        if self.arc_segments < 12:
            raise ProcessingProfileError(
                "Arco com menos de 12 segmentos deformaria o contorno do obstaculo."
            )
        if self.max_pass_points < 64:
            raise ProcessingProfileError("max_pass_points muito baixo para uma passada.")
        if self.boundary_max_vertices < 120:
            raise ProcessingProfileError(
                "boundary_max_vertices muito baixo: o limite perderia a forma."
            )

    @property
    def is_preview(self) -> bool:
        return self.mode == PREVIEW

    def label(self) -> str:
        return "Rapido — Preview" if self.is_preview else "Precisao — Final"

    def report(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "arc_segments": self.arc_segments,
            "max_pass_points": self.max_pass_points,
            "boundary_max_vertices": self.boundary_max_vertices,
            "validation_sample": self.validation_sample,
            "materialize_virtual_rows": self.materialize_virtual_rows,
            "compute_shutoff": self.compute_shutoff,
        }


def preview_profile() -> ProcessingProfile:
    """Rapido: geometria suficiente para conferir o traçado no mapa.

    Mantem toda a logica de deteccao e desvio; corta apenas resolucao de
    desenho e o que so serve para exportacao/relatorio.
    """
    return ProcessingProfile(
        mode=PREVIEW,
        arc_segments=24,
        max_pass_points=240,
        boundary_max_vertices=360,
        validation_sample=40,
        materialize_virtual_rows=False,
        compute_shutoff=False,
    )


def final_profile() -> ProcessingProfile:
    """Precisao: geometria completa para exportar ao monitor."""
    return ProcessingProfile(
        mode=FINAL,
        arc_segments=48,
        max_pass_points=480,
        boundary_max_vertices=720,
        validation_sample=0,
        materialize_virtual_rows=True,
        compute_shutoff=True,
    )


def profile_from_mode(mode: str) -> ProcessingProfile:
    normalized = (mode or FINAL).strip().lower()
    if normalized in {PREVIEW, "rapido", "rápido", "fast", "quick"}:
        return preview_profile()
    if normalized in {FINAL, "precisao", "precisão", "precision"}:
        return final_profile()
    raise ProcessingProfileError(f"Modo de processamento desconhecido: {mode!r}")
