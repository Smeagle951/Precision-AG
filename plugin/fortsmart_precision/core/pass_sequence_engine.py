# -*- coding: utf-8 -*-
"""Sequencia de passadas centrais para conexao de voltas."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.turn_configuration import SUPPORTED_SEQUENCE_MODES, PassSequenceMode
from .parallel_pass_engine import ParallelPass


class PassSequenceError(ValueError):
    """Erro ao montar a sequencia de passadas."""


@dataclass(frozen=True)
class PassConnection:
    """Par de passadas consecutivas na ordem de trabalho."""

    sequence_no: int
    from_pass: ParallelPass
    to_pass: ParallelPass
    from_exit: tuple[float, float]
    to_entry: tuple[float, float]
    travel_reversed_on_from: bool
    travel_reversed_on_to: bool
    block_no: int = 1


def _endpoint(pass_line: ParallelPass, use_end: bool) -> tuple[float, float]:
    segment = pass_line.clipped_segment
    return segment.end if use_end else segment.start


def order_passes_for_mode(
    passes: list[ParallelPass],
    mode: PassSequenceMode,
    *,
    skip_passes: int = 0,
    block_size: int = 4,
    custom_order: tuple[int, ...] = (),
) -> list[ParallelPass]:
    """Ordena passadas centrais conforme o modo de sequencia."""
    ordered = sorted(passes, key=lambda item: item.pass_no)
    if not ordered:
        return []
    if mode == PassSequenceMode.SEQUENTIAL:
        return ordered
    if mode in {PassSequenceMode.ALTERNATING, PassSequenceMode.SKIP_ONE}:
        step = max(2, skip_passes + 1) if mode == PassSequenceMode.SKIP_ONE and skip_passes > 0 else 2
        groups: list[ParallelPass] = []
        for start in range(step):
            groups.extend(ordered[start::step])
        return groups
    if mode == PassSequenceMode.SKIP_TWO:
        step = max(3, skip_passes + 1) if skip_passes >= 2 else 3
        groups = []
        for start in range(step):
            groups.extend(ordered[start::step])
        return groups
    if mode == PassSequenceMode.BLOCKS:
        size = max(1, block_size)
        blocks: list[ParallelPass] = []
        for start in range(0, len(ordered), size):
            blocks.extend(ordered[start : start + size])
        return blocks
    if mode == PassSequenceMode.CUSTOM:
        if not custom_order:
            raise PassSequenceError("Sequencia personalizada exige custom_order.")
        by_no = {item.pass_no: item for item in ordered}
        missing = [no for no in custom_order if no not in by_no]
        if missing:
            raise PassSequenceError(f"Passadas inexistentes na sequencia personalizada: {missing}.")
        return [by_no[no] for no in custom_order]
    raise PassSequenceError(f"Modo de sequencia '{mode.value}' nao suportado.")


def build_pass_sequence(
    passes: list[ParallelPass],
    mode: PassSequenceMode = PassSequenceMode.SEQUENTIAL,
    custom_order: tuple[int, ...] = (),
    skip_passes: int = 0,
    block_size: int = 4,
) -> list[PassConnection]:
    """Monta conexoes entre passadas centrais (nao linhas fisicas).

    O sentido de percurso alterna na ordem de trabalho (serpentina):
    indice 0: start -> end; indice 1: end -> start; etc.
    """
    if mode not in SUPPORTED_SEQUENCE_MODES:
        raise PassSequenceError(
            f"Modo de sequencia '{mode.value}' nao disponivel nesta etapa."
        )
    if not passes:
        return []

    ordered = order_passes_for_mode(
        passes,
        mode,
        skip_passes=skip_passes,
        block_size=block_size,
        custom_order=custom_order,
    )
    connections: list[PassConnection] = []
    for index in range(len(ordered) - 1):
        from_pass = ordered[index]
        to_pass = ordered[index + 1]
        from_reversed = index % 2 == 1
        to_reversed = (index + 1) % 2 == 1
        from_exit = _endpoint(from_pass, use_end=not from_reversed)
        to_entry = _endpoint(to_pass, use_end=to_reversed)
        block_no = (index // max(1, block_size)) + 1 if mode == PassSequenceMode.BLOCKS else 1
        connections.append(
            PassConnection(
                sequence_no=index + 1,
                from_pass=from_pass,
                to_pass=to_pass,
                from_exit=from_exit,
                to_entry=to_entry,
                travel_reversed_on_from=from_reversed,
                travel_reversed_on_to=to_reversed,
                block_no=block_no,
            )
        )
    return connections
