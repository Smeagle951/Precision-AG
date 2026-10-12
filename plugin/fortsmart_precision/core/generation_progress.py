# -*- coding: utf-8 -*-
"""Callbacks de progresso para geracao Precision Lines."""

from __future__ import annotations

from collections.abc import Callable

ProgressCallback = Callable[[int, str], None]


def report_progress(
    callback: ProgressCallback | None,
    percent: int,
    message: str,
) -> None:
    if callback is None:
        return
    callback(max(0, min(100, int(percent))), message)


def scaled_progress(
    callback: ProgressCallback | None,
    start: int,
    end: int,
) -> ProgressCallback | None:
    """Mapeia 0-100 local para o intervalo [start, end] do pipeline."""
    if callback is None:
        return None
    span = max(1, end - start)

    def _inner(local_pct: int, message: str) -> None:
        local = max(0, min(100, int(local_pct)))
        report_progress(callback, start + int(span * local / 100), message)

    return _inner
