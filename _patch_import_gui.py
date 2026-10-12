# -*- coding: utf-8 -*-
from pathlib import Path

path = Path(r"C:\Users\fortu\Desktop\PYTHON\plugin\fortsmart_precision\gui\fortsmart_workspace_dialog.py")
text = path.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
start = next(i for i, l in enumerate(lines) if l.startswith("    def _import_adaptive_curve"))
end = next(i for i, l in enumerate(lines) if i > start and l.startswith("    def _apply_obstacle_avoidance"))

new = '''    def _import_adaptive_curve(self) -> None:
        """Botao 1: AdaptiveCurve -> cortar U -> preservar miolo -> last_result.spraying_passes.

        Nao aplica obstaculos aqui. O botao Aplicar desvio usa exatamente
        last_result.spraying_passes (sem regenerar por A-B).
        """
        try:
            if self.isMinimized():
                self.showNormal()
            self.setEnabled(False)
            try:
                from qgis.PyQt.QtCore import Qt
                from qgis.PyQt.QtWidgets import QApplication

                QApplication.setOverrideCursor(Qt.WaitCursor)
            except Exception:
                pass

            self._ensure_workspace_layers_metric(silent=True)
            field_layer = self.field_combo.currentLayer()
            curve_layer = getattr(self, "adaptive_curve_combo", None)
            curve_layer = curve_layer.currentLayer() if curve_layer is not None else None
            if field_layer is None:
                raise ValueError("Selecione o talhao (Boundary) na aba 1.")
            if curve_layer is None or not is_line_like_vector_layer(curve_layer):
                raise ValueError(
                    "Selecione a camada AdaptiveCurve / plano completo na aba 1 "
                    "(grupo AdaptiveCurve pronta)."
                )

            crs_authid, target_crs, _was_geo = resolve_metric_target_crs(field_layer)
            self.work_crs_authid = crs_authid
            field_mp = multipolygon_from_polygon_layer(field_layer, target_crs)
            if not field_mp:
                raise ValueError("Talhao sem poligono util no CRS de trabalho.")

            # TODAS as partes — nunca descartar feicoes mais curtas.
            polylines = all_polylines_from_line_layer(curve_layer, target_crs)
            if not polylines:
                raise ValueError("Camada AdaptiveCurve sem linhas validas.")

            sprayer = self.sprayer_widget.build_machine()
            planter = self.planter_widget.build_machine()
            spray_w = sprayer.operational_width_m
            plant_w = planter.operational_width_m
            spray_h = self.sprayer_widget.headland_pass_count()
            plant_h = self.planter_widget.headland_pass_count()

            plan = build_plan_from_adaptive_curve(
                polylines,
                field_mp,
                sprayer=sprayer,
                planter=planter,
                spray_headland=HeadlandLayout(
                    pass_count=spray_h,
                    width_m=spray_w if spray_h > 0 else 0.0,
                    effective_spacing_m=spray_w if spray_h > 0 else None,
                    mode="follow_boundary" if spray_h > 0 else "none",
                ),
                plant_headland=HeadlandLayout(
                    pass_count=plant_h,
                    width_m=plant_w if plant_h > 0 else 0.0,
                    effective_spacing_m=plant_w if plant_h > 0 else None,
                    mode="follow_boundary" if plant_h > 0 else "none",
                ),
                spray_extension_m=self.sprayer_widget.extension_m(),
                plant_extension_m=self.planter_widget.extension_m(),
            )
            spraying_passes = list(plan.spraying_passes)
            planting_passes = list(plan.planting_passes)
            planting_rows = list(plan.planting_rows)

            if len(plan.master_path) >= 2:
                self.ab_start = plan.master_path[0]
                self.ab_end = plan.master_path[-1]
                self.ab_path_points = tuple(plan.master_path)
                self.ab_source_crs = target_crs

            project = self._build_cross_stub_project(
                crs_authid=crs_authid,
                target_crs=target_crs,
                planting_rows=planting_rows,
                spraying_passes=spraying_passes,
            )
            try:
                from dataclasses import replace

                project = replace(project, ab_line=plan.ab_line)
            except Exception:
                pass

            result = PrecisionLinesResult(
                project=project,
                boundary=plan.planting_boundary,
                planting_passes=planting_passes,
                planting_rows=planting_rows,
                spraying_passes=spraying_passes,
                tramline_zones=[],
                shutoff_segments=[],
                shutoff_table=[],
                avoided_paths=[],
                obstacle_envelopes=[],
                avoidance_table=[],
                spraying_boundary=plan.spraying_boundary,
                tire_tracks=[],
            )
            # Ponto critico do modelo: resultado real, nao so preview visual.
            self.last_result = result
            self._show_result(
                result,
                step=(
                    f"AdaptiveCurve: {len(spraying_passes)} spray / "
                    f"{len(planting_passes)} plantio | "
                    f"{plan.stripped_uturn_count} U cortado(s)"
                ),
            )
            self._select_preview_layers_in_cross_combos()
            QMessageBox.information(
                self,
                "FortSmart",
                f"Importacao / corte de retornos concluido.\\n\\n"
                f"Passadas pulverizacao: {len(spraying_passes)}\\n"
                f"Passadas plantio: {len(planting_passes)}\\n"
                f"Retornos (U) cortados: {plan.stripped_uturn_count}\\n"
                f"Contornos removidos: {plan.removed_contour_count}\\n"
                f"Partes de origem: {plan.source_polyline_count}\\n\\n"
                "Desvios do miolo preservados (path_points).\\n"
                "Proximo: aba 4 -> obstaculos -> Aplicar desvio "
                "(usa last_result.spraying_passes, sem regenerar A-B).",
            )
        except Exception as exc:
            if self.isMinimized():
                self.showNormal()
            self._warn_crs_error(exc)
        finally:
            self.setEnabled(True)
            try:
                from qgis.PyQt.QtWidgets import QApplication

                QApplication.restoreOverrideCursor()
            except Exception:
                pass

'''.replace("\\\\n", "\\n")

path.write_text("".join(lines[:start]) + new + "".join(lines[end:]), encoding="utf-8")
print("ok", start + 1, "->", end)
