# -*- coding: utf-8 -*-
"""Transpasse do pulverizador: regra unica (nenhum / metros / numero de bicos).

O transpasse posiciona as passadas (passo centro a centro menor que a barra).
Nao encolhe a barra fisica e nao desliga bicos de forma permanente.
"""

from __future__ import annotations

from collections.abc import Iterable

OVERLAP_MODE_NONE = "none"
OVERLAP_MODE_METERS = "meters"
OVERLAP_MODE_NOZZLES = "nozzles"
OVERLAP_MODES = (OVERLAP_MODE_NONE, OVERLAP_MODE_METERS, OVERLAP_MODE_NOZZLES)

OVERLAP_SIDE_NONE = "none"
OVERLAP_SIDE_LEFT = "left"
OVERLAP_SIDE_RIGHT = "right"

_LEGACY_AUTO_TOLERANCE_M = 0.001


class SprayerOverlapError(ValueError):
    """Configuracao de transpasse invalida."""


def resolve_sprayer_overlap_m(
    mode: str,
    *,
    nozzle_count: int,
    nozzle_spacing_m: float,
    boom_width_m: float,
    overlap_m: float = 0.0,
    overlap_nozzle_count: int = 0,
    legacy_auto_from_boom: bool = False,
) -> float:
    """Transpasse em metros a partir do modo escolhido.

    - none: 0
    - meters: `overlap_m`; com `legacy_auto_from_boom` e valor 0, mantem a regra
      antiga da GUI (barra informada menor que bicos x espacamento -> diferenca)
    - nozzles: `overlap_nozzle_count` x `nozzle_spacing_m`
    """
    if mode not in OVERLAP_MODES:
        raise SprayerOverlapError(f"Modo de transpasse desconhecido: {mode!r}.")
    if mode == OVERLAP_MODE_NONE:
        return 0.0
    if mode == OVERLAP_MODE_NOZZLES:
        if overlap_nozzle_count < 0:
            raise SprayerOverlapError("Bicos de transpasse nao pode ser negativo.")
        if overlap_nozzle_count >= nozzle_count:
            raise SprayerOverlapError(
                "Bicos de transpasse deve ser menor que o numero de bicos da barra."
            )
        return round(overlap_nozzle_count * nozzle_spacing_m, 6)
    if overlap_m < 0:
        raise SprayerOverlapError("Transpasse nao pode ser negativo.")
    if overlap_m > 0 or not legacy_auto_from_boom:
        return overlap_m
    calculated = nozzle_count * nozzle_spacing_m
    if boom_width_m < calculated - _LEGACY_AUTO_TOLERANCE_M:
        return round(calculated - boom_width_m, 3)
    return 0.0


def effective_pass_spacing_m(boom_width_m: float, overlap_m: float) -> float:
    """Distancia centro a centro entre passadas = barra fisica - transpasse."""
    spacing = boom_width_m - overlap_m
    if spacing <= 0:
        raise SprayerOverlapError("Transpasse deve ser menor que a largura da barra.")
    return spacing


def overlap_side_for_pass(
    *, previous_offset_m: float | None, offset_m: float, direction: str
) -> str:
    """Lado da barra que sobrepoe a passada anterior, no sentido de deslocamento.

    `offset_m` positivo = direita da A-B (convencao do motor de passadas). A
    passada anterior fica sempre no mesmo lado geografico; como o sentido
    alterna (ida/volta), o lado em relacao ao operador alterna esquerda/direita.
    """
    if previous_offset_m is None or abs(previous_offset_m - offset_m) <= 1e-9:
        return OVERLAP_SIDE_NONE
    previous_is_right_of_ab = previous_offset_m > offset_m
    forward = direction != "reverse"
    return OVERLAP_SIDE_RIGHT if previous_is_right_of_ab == forward else OVERLAP_SIDE_LEFT


def pass_overlap_attributes(
    passes: Iterable[tuple[int, float, str]],
    *,
    overlap_m: float,
    overlap_nozzles: int | None,
) -> dict[int, dict[str, object]]:
    """Atributos de transpasse por passada: (pass_no, offset_m, direction) -> attrs.

    A primeira passada (menor pass_no) nao sobrepoe nada. Partes da mesma
    passada compartilham pass_no e recebem os mesmos atributos.
    """
    first_by_pass: dict[int, tuple[float, str]] = {}
    for pass_no, offset, direction in passes:
        first_by_pass.setdefault(int(pass_no), (float(offset), str(direction)))
    attributes: dict[int, dict[str, object]] = {}
    previous_offset: float | None = None
    for pass_no in sorted(first_by_pass):
        offset, direction = first_by_pass[pass_no]
        side = (
            overlap_side_for_pass(
                previous_offset_m=previous_offset, offset_m=offset, direction=direction
            )
            if overlap_m > 0
            else OVERLAP_SIDE_NONE
        )
        overlapping = side != OVERLAP_SIDE_NONE
        attributes[pass_no] = {
            "direction": direction,
            "overlap_side": side,
            "overlap_nozzles": overlap_nozzles if overlapping else 0,
            "overlap_m": overlap_m if overlapping else 0.0,
        }
        previous_offset = offset
    return attributes


def overlap_nozzle_equivalent(overlap_m: float, nozzle_spacing_m: float) -> int | None:
    """Transpasse em bicos inteiros; None quando nao e multiplo do espacamento."""
    if nozzle_spacing_m <= 0:
        return None
    ratio = overlap_m / nozzle_spacing_m
    nearest = round(ratio)
    return int(nearest) if abs(ratio - nearest) <= 1e-6 else None


def machine_pass_overlap_attributes(passes: Iterable, machine) -> dict[int, dict[str, object]]:
    """Atributos de transpasse das passadas de um SprayerMachine (vazio sem maquina)."""
    if machine is None or not hasattr(machine, "resolved_overlap_m"):
        return {}
    overlap = machine.resolved_overlap_m
    if machine.overlap_mode == OVERLAP_MODE_NOZZLES:
        nozzles: int | None = machine.overlap_nozzle_count
    else:
        nozzles = overlap_nozzle_equivalent(overlap, machine.nozzle_spacing_m)
    return pass_overlap_attributes(
        ((item.pass_no, item.offset_m, item.direction) for item in passes),
        overlap_m=overlap,
        overlap_nozzles=nozzles,
    )
