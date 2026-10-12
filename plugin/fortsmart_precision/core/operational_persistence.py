# -*- coding: utf-8 -*-
"""Persistencia transacional das geracoes operacionais no GeoPackage."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from ..domain.operational_contract import (
    CrossSourceMode,
    GenerationStatus,
    OperationalGeneration,
    OperationalReason,
    OperationalSegment,
    OperationalState,
    OperationManifest,
    OperationRelation,
    OverrideStatus,
    PlantingRowRecord,
    SprayPassRecord,
    TireTrackRecord,
)


class OperationalPersistenceError(RuntimeError):
    pass


def _points_json(points) -> str:
    return json.dumps([[float(x), float(y)] for x, y in points], separators=(",", ":"))


def _points(value: str):
    return tuple((float(item[0]), float(item[1])) for item in json.loads(value))


class OperationalPersistenceStore:
    """Historico por geracao; somente uma ACTIVE por talhao e tipo de operacao."""

    def __init__(self, geopackage_path: str | Path):
        self.path = Path(geopackage_path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS fortsmart_operation_manifest (
                generation_id TEXT PRIMARY KEY,
                field_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                algorithm_version TEXT NOT NULL,
                status TEXT NOT NULL,
                source_mode TEXT NOT NULL,
                source_crs TEXT NOT NULL,
                working_crs TEXT NOT NULL,
                sprayer_name TEXT NOT NULL,
                planting_layer TEXT NOT NULL,
                spray_layer TEXT NOT NULL,
                selected_spray_count INTEGER NOT NULL,
                analyzed_planting_rows INTEGER NOT NULL,
                affected_rows_count INTEGER NOT NULL,
                intersection_count INTEGER NOT NULL,
                excluded_length_m REAL NOT NULL,
                sprayer_snapshot_json TEXT NOT NULL,
                cross_snapshot_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fs_manifest_scope
                ON fortsmart_operation_manifest(field_id, operation_type, status);

            CREATE TABLE IF NOT EXISTS fortsmart_operation_planting_rows (
                generation_id TEXT NOT NULL,
                source_row_id TEXT NOT NULL,
                source_feature_id TEXT NOT NULL,
                pass_id INTEGER NOT NULL,
                row_id INTEGER NOT NULL,
                geometry_json TEXT NOT NULL,
                length_m REAL NOT NULL,
                PRIMARY KEY (generation_id, source_row_id),
                FOREIGN KEY (generation_id) REFERENCES fortsmart_operation_manifest(generation_id)
                    ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS fortsmart_operation_spray_passes (
                generation_id TEXT NOT NULL,
                spray_pass_id TEXT NOT NULL,
                source_feature_id TEXT NOT NULL,
                source_layer_id TEXT NOT NULL,
                source_geometry_type TEXT NOT NULL,
                source_mode TEXT NOT NULL,
                geometry_json TEXT NOT NULL,
                PRIMARY KEY (generation_id, spray_pass_id),
                FOREIGN KEY (generation_id) REFERENCES fortsmart_operation_manifest(generation_id)
                    ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS fortsmart_operation_tire_tracks (
                generation_id TEXT NOT NULL,
                track_id TEXT NOT NULL,
                spray_pass_id TEXT NOT NULL,
                source_feature_id TEXT NOT NULL,
                side TEXT NOT NULL,
                center_offset_m REAL NOT NULL,
                track_width_m REAL NOT NULL,
                physical_tire_width_m REAL NOT NULL,
                safety_margin_m REAL NOT NULL,
                effective_exclusion_width_m REAL NOT NULL,
                geometry_json TEXT NOT NULL,
                PRIMARY KEY (generation_id, track_id),
                FOREIGN KEY (generation_id) REFERENCES fortsmart_operation_manifest(generation_id)
                    ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS fortsmart_operation_segments (
                generation_id TEXT NOT NULL,
                segment_id TEXT NOT NULL,
                field_id TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                source_layer_role TEXT NOT NULL,
                source_feature_id TEXT NOT NULL,
                source_row_id TEXT NOT NULL,
                source_mode TEXT NOT NULL,
                geometry_json TEXT NOT NULL,
                station_start_m REAL NOT NULL,
                station_end_m REAL NOT NULL,
                length_m REAL NOT NULL,
                state TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                algorithm_version TEXT NOT NULL,
                spray_pass_id TEXT NOT NULL,
                spray_source_feature_id TEXT NOT NULL,
                tire_track_id TEXT NOT NULL,
                tire_side TEXT NOT NULL,
                physical_tire_width_m REAL NOT NULL,
                safety_margin_m REAL NOT NULL,
                effective_exclusion_width_m REAL NOT NULL,
                override_status TEXT NOT NULL,
                user_override INTEGER NOT NULL,
                PRIMARY KEY (generation_id, segment_id),
                FOREIGN KEY (generation_id) REFERENCES fortsmart_operation_manifest(generation_id)
                    ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS fortsmart_operation_relations (
                generation_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                parent_role TEXT NOT NULL,
                parent_feature_id TEXT NOT NULL,
                child_role TEXT NOT NULL,
                child_feature_id TEXT NOT NULL,
                FOREIGN KEY (generation_id) REFERENCES fortsmart_operation_manifest(generation_id)
                    ON DELETE CASCADE
            );
            """
        )

    def save_generation(self, generation: OperationalGeneration) -> OperationalGeneration:
        """Valida, grava e troca ACTIVE somente no final da mesma transacao."""
        generation.validate()
        draft = replace(generation, manifest=replace(generation.manifest, status=GenerationStatus.DRAFT))
        try:
            with self._connect() as connection:
                self.ensure_schema(connection)
                self._insert_generation(connection, draft)
                self._validate_written_counts(connection, draft)
                connection.execute(
                    """UPDATE fortsmart_operation_manifest
                       SET status = ?
                       WHERE field_id = ? AND operation_type = ? AND status = ?
                         AND generation_id <> ?""",
                    (
                        GenerationStatus.SUPERSEDED.value,
                        draft.manifest.field_id,
                        draft.manifest.operation_type,
                        GenerationStatus.ACTIVE.value,
                        draft.manifest.generation_id,
                    ),
                )
                connection.execute(
                    "UPDATE fortsmart_operation_manifest SET status = ? WHERE generation_id = ?",
                    (GenerationStatus.ACTIVE.value, draft.manifest.generation_id),
                )
        except (sqlite3.Error, ValueError) as exc:
            raise OperationalPersistenceError(str(exc)) from exc
        return replace(draft, manifest=replace(draft.manifest, status=GenerationStatus.ACTIVE))

    @staticmethod
    def _insert_generation(connection, generation: OperationalGeneration) -> None:
        manifest = generation.manifest
        connection.execute(
            """INSERT INTO fortsmart_operation_manifest VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                manifest.generation_id, manifest.field_id, manifest.field_name,
                manifest.operation_type, manifest.operation_id, manifest.created_at,
                manifest.algorithm_version, manifest.status.value, manifest.source_mode.value,
                manifest.source_crs, manifest.working_crs, manifest.sprayer_name,
                manifest.planting_layer, manifest.spray_layer, manifest.selected_spray_count,
                manifest.analyzed_planting_rows, manifest.affected_rows_count,
                manifest.intersection_count, manifest.excluded_length_m,
                json.dumps(manifest.sprayer_snapshot, ensure_ascii=True, sort_keys=True),
                json.dumps(manifest.cross_snapshot, ensure_ascii=True, sort_keys=True),
            ),
        )
        connection.executemany(
            "INSERT INTO fortsmart_operation_planting_rows VALUES (?,?,?,?,?,?,?)",
            [
                (manifest.generation_id, item.source_row_id, item.source_feature_id,
                 item.pass_id, item.row_id, _points_json(item.geometry), item.length_m)
                for item in generation.planting_rows
            ],
        )
        connection.executemany(
            "INSERT INTO fortsmart_operation_spray_passes VALUES (?,?,?,?,?,?,?)",
            [
                (manifest.generation_id, item.spray_pass_id, item.source_feature_id,
                 item.source_layer_id, item.source_geometry_type, item.source_mode.value,
                 _points_json(item.geometry))
                for item in generation.spray_passes
            ],
        )
        connection.executemany(
            "INSERT INTO fortsmart_operation_tire_tracks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (manifest.generation_id, item.track_id, item.spray_pass_id,
                 item.source_feature_id, item.side, item.center_offset_m,
                 item.track_width_m, item.physical_tire_width_m, item.safety_margin_m,
                 item.effective_exclusion_width_m, _points_json(item.geometry))
                for item in generation.tire_tracks
            ],
        )
        connection.executemany(
            """INSERT INTO fortsmart_operation_segments VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (manifest.generation_id, item.segment_id, item.field_id, item.operation_id,
                 item.operation_type, item.source_layer_role, item.source_feature_id,
                 item.source_row_id, item.source_mode.value, _points_json(item.geometry),
                 item.station_start_m, item.station_end_m, item.length_m, item.state.value,
                 item.reason.value, item.created_at, item.algorithm_version,
                 item.spray_pass_id, item.spray_source_feature_id, item.tire_track_id,
                 item.tire_side, item.physical_tire_width_m, item.safety_margin_m,
                 item.effective_exclusion_width_m, item.override_status.value,
                 int(item.user_override),)
                for item in generation.segments
            ],
        )
        connection.executemany(
            "INSERT INTO fortsmart_operation_relations VALUES (?,?,?,?,?,?)",
            [
                (item.generation_id, item.relation_type, item.parent_role,
                 item.parent_feature_id, item.child_role, item.child_feature_id)
                for item in generation.relations
            ],
        )

    def _validate_written_counts(self, connection, generation: OperationalGeneration) -> None:
        generation_id = generation.manifest.generation_id
        expected = {
            "fortsmart_operation_planting_rows": len(generation.planting_rows),
            "fortsmart_operation_spray_passes": len(generation.spray_passes),
            "fortsmart_operation_tire_tracks": len(generation.tire_tracks),
            "fortsmart_operation_segments": len(generation.segments),
            "fortsmart_operation_relations": len(generation.relations),
        }
        for table, count in expected.items():
            stored = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE generation_id = ?", (generation_id,)
            ).fetchone()[0]
            if stored != count:
                raise OperationalPersistenceError(
                    f"Contagem divergente em {table}: esperado {count}, gravado {stored}."
                )

    def load_active(self, field_id: str, operation_type: str = "PLANTING_SHUTOFF"):
        if not self.path.exists():
            return None
        with self._connect() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                """SELECT generation_id FROM fortsmart_operation_manifest
                   WHERE field_id = ? AND operation_type = ? AND status = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (field_id, operation_type, GenerationStatus.ACTIVE.value),
            ).fetchone()
            return self.load_generation(row[0], connection=connection) if row else None

    def load_generation(self, generation_id: str, *, connection=None):
        owned = connection is None
        connection = connection or self._connect()
        try:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM fortsmart_operation_manifest WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            if row is None:
                return None
            manifest = OperationManifest(
                generation_id=row["generation_id"], field_id=row["field_id"],
                field_name=row["field_name"], operation_type=row["operation_type"],
                operation_id=row["operation_id"], created_at=row["created_at"],
                algorithm_version=row["algorithm_version"],
                status=GenerationStatus(row["status"]), source_mode=CrossSourceMode(row["source_mode"]),
                source_crs=row["source_crs"], working_crs=row["working_crs"],
                sprayer_name=row["sprayer_name"], planting_layer=row["planting_layer"],
                spray_layer=row["spray_layer"], selected_spray_count=row["selected_spray_count"],
                analyzed_planting_rows=row["analyzed_planting_rows"],
                affected_rows_count=row["affected_rows_count"],
                intersection_count=row["intersection_count"],
                excluded_length_m=row["excluded_length_m"],
                sprayer_snapshot=json.loads(row["sprayer_snapshot_json"]),
                cross_snapshot=json.loads(row["cross_snapshot_json"]),
            )
            rows = tuple(PlantingRowRecord(
                item["source_row_id"], item["source_feature_id"], item["pass_id"],
                item["row_id"], _points(item["geometry_json"]), item["length_m"])
                for item in connection.execute(
                    "SELECT * FROM fortsmart_operation_planting_rows WHERE generation_id = ?",
                    (generation_id,),
                ))
            passes = tuple(SprayPassRecord(
                item["spray_pass_id"], item["source_feature_id"], item["source_layer_id"],
                item["source_geometry_type"], CrossSourceMode(item["source_mode"]),
                _points(item["geometry_json"]),
            ) for item in connection.execute(
                "SELECT * FROM fortsmart_operation_spray_passes WHERE generation_id = ?",
                (generation_id,),
            ))
            tracks = tuple(TireTrackRecord(
                item["track_id"], generation_id, item["spray_pass_id"],
                item["source_feature_id"], item["side"], item["center_offset_m"],
                item["track_width_m"], item["physical_tire_width_m"],
                item["safety_margin_m"], item["effective_exclusion_width_m"],
                _points(item["geometry_json"]),
            ) for item in connection.execute(
                "SELECT * FROM fortsmart_operation_tire_tracks WHERE generation_id = ?",
                (generation_id,),
            ))
            segments = tuple(self._segment_from_row(item) for item in connection.execute(
                "SELECT * FROM fortsmart_operation_segments WHERE generation_id = ?",
                (generation_id,),
            ))
            relations = tuple(OperationRelation(
                item["generation_id"], item["relation_type"], item["parent_role"],
                item["parent_feature_id"], item["child_role"], item["child_feature_id"],
            ) for item in connection.execute(
                "SELECT * FROM fortsmart_operation_relations WHERE generation_id = ?",
                (generation_id,),
            ))
            result = OperationalGeneration(manifest, rows, passes, tracks, segments, relations)
            result.validate()
            return result
        finally:
            if owned:
                connection.close()

    @staticmethod
    def _segment_from_row(item):
        return OperationalSegment(
            segment_id=item["segment_id"], field_id=item["field_id"],
            operation_id=item["operation_id"], operation_type=item["operation_type"],
            source_layer_role=item["source_layer_role"],
            source_feature_id=item["source_feature_id"], source_row_id=item["source_row_id"],
            source_mode=CrossSourceMode(item["source_mode"]), geometry=_points(item["geometry_json"]),
            station_start_m=item["station_start_m"], station_end_m=item["station_end_m"],
            length_m=item["length_m"], state=OperationalState(item["state"]),
            reason=OperationalReason(item["reason"]), created_at=item["created_at"],
            generation_id=item["generation_id"], algorithm_version=item["algorithm_version"],
            spray_pass_id=item["spray_pass_id"],
            spray_source_feature_id=item["spray_source_feature_id"],
            tire_track_id=item["tire_track_id"], tire_side=item["tire_side"],
            physical_tire_width_m=item["physical_tire_width_m"],
            safety_margin_m=item["safety_margin_m"],
            effective_exclusion_width_m=item["effective_exclusion_width_m"],
            override_status=OverrideStatus(item["override_status"]),
            user_override=bool(item["user_override"]),
        )

    def mark_active_stale(self, field_id: str, operation_type: str = "PLANTING_SHUTOFF") -> int:
        if not self.path.exists():
            return 0
        with self._connect() as connection:
            self.ensure_schema(connection)
            cursor = connection.execute(
                """UPDATE fortsmart_operation_manifest SET status = ?
                   WHERE field_id = ? AND operation_type = ? AND status = ?""",
                (GenerationStatus.STALE.value, field_id, operation_type, GenerationStatus.ACTIVE.value),
            )
            return cursor.rowcount
