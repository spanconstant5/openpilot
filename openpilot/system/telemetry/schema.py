from __future__ import annotations

import sqlite3


SCHEMA_VERSION = 2


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS segment_metadata (
  schema_version INTEGER NOT NULL,
  drive_id TEXT NOT NULL,
  segment_index INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active', 'complete', 'corrupt')),
  start_mono_ns INTEGER NOT NULL,
  start_wall_ms INTEGER NOT NULL,
  end_mono_ns INTEGER,
  end_wall_ms INTEGER,
  close_reason TEXT
);

CREATE TABLE IF NOT EXISTS samples (
  mono_time_ns INTEGER PRIMARY KEY,
  wall_time_ms INTEGER NOT NULL,
  v_ego_mps REAL,
  a_ego_mps2 REAL,
  steering_angle_deg REAL,
  steering_torque REAL,
  steering_pressed INTEGER,
  gas REAL,
  gas_pressed INTEGER,
  brake REAL,
  brake_pressed INTEGER,
  engine_rpm REAL,
  engine_running INTEGER,
  hybrid_battery_percent REAL,
  ev_mode INTEGER,
  power_flow_kw REAL,
  power_flow_source TEXT,
  hybrid_drive_force_n REAL,
  stock_aeb INTEGER,
  cruise_available INTEGER,
  cruise_enabled INTEGER,
  lta_active INTEGER,
  tss_status TEXT,
  selfdrive_state TEXT,
  engaged INTEGER,
  active INTEGER,
  engageable INTEGER,
  alert_type TEXT,
  alert_status TEXT,
  alert_text_1 TEXT,
  alert_text_2 TEXT,
  gps_latitude REAL,
  gps_longitude REAL,
  gps_altitude_m REAL,
  gps_speed_mps REAL,
  gps_bearing_deg REAL,
  gps_accuracy_m REAL,
  gps_speed_accuracy_mps REAL,
  gps_has_fix INTEGER,
  gps_unix_time_ms INTEGER,
  driver_face_detected INTEGER,
  driver_distracted INTEGER,
  driver_awareness REAL,
  driver_face_probability REAL,
  driver_face_pitch REAL,
  driver_face_yaw REAL,
  driver_face_roll REAL,
  road_segment_num INTEGER,
  road_encode_id INTEGER
);

CREATE INDEX IF NOT EXISTS samples_wall_time_idx ON samples(wall_time_ms);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mono_time_ns INTEGER NOT NULL,
  wall_time_ms INTEGER NOT NULL,
  kind TEXT NOT NULL,
  value TEXT,
  severity TEXT,
  details_json TEXT
);

CREATE INDEX IF NOT EXISTS events_mono_time_idx ON events(mono_time_ns);

CREATE TABLE IF NOT EXISTS model_paths (
  mono_time_ns INTEGER PRIMARY KEY,
  frame_id INTEGER,
  x_json TEXT NOT NULL,
  y_json TEXT NOT NULL,
  z_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  route TEXT NOT NULL,
  segment_num INTEGER NOT NULL,
  relative_path TEXT NOT NULL,
  first_mono_ns INTEGER NOT NULL,
  last_mono_ns INTEGER NOT NULL,
  first_encode_time_ns INTEGER,
  last_encode_time_ns INTEGER,
  UNIQUE(route, segment_num)
);
"""


SAMPLE_COLUMNS = (
  "mono_time_ns", "wall_time_ms", "v_ego_mps", "a_ego_mps2",
  "steering_angle_deg", "steering_torque", "steering_pressed", "gas",
  "gas_pressed", "brake", "brake_pressed", "engine_rpm", "engine_running",
  "hybrid_battery_percent", "ev_mode", "power_flow_kw", "power_flow_source",
  "hybrid_drive_force_n", "stock_aeb", "cruise_available", "cruise_enabled",
  "lta_active", "tss_status", "selfdrive_state",
  "engaged", "active", "engageable", "alert_type", "alert_status",
  "alert_text_1", "alert_text_2", "gps_latitude", "gps_longitude",
  "gps_altitude_m", "gps_speed_mps", "gps_bearing_deg", "gps_accuracy_m",
  "gps_speed_accuracy_mps", "gps_has_fix", "gps_unix_time_ms",
  "driver_face_detected", "driver_distracted", "driver_awareness",
  "driver_face_probability", "driver_face_pitch", "driver_face_yaw",
  "driver_face_roll", "road_segment_num", "road_encode_id",
)

INSERT_SAMPLE_SQL = (
  f"INSERT OR REPLACE INTO samples ({', '.join(SAMPLE_COLUMNS)}) " +
  f"VALUES ({', '.join('?' for _ in SAMPLE_COLUMNS)})"
)


def create_schema(connection: sqlite3.Connection, drive_id: str, segment_index: int,
                  start_mono_ns: int, start_wall_ms: int) -> None:
  connection.executescript(SCHEMA_SQL)
  connection.execute("DELETE FROM segment_metadata")
  connection.execute(
    """INSERT INTO segment_metadata
       (schema_version, drive_id, segment_index, status, start_mono_ns, start_wall_ms)
       VALUES (?, ?, ?, 'active', ?, ?)""",
    (SCHEMA_VERSION, drive_id, segment_index, start_mono_ns, start_wall_ms),
  )
  connection.commit()


def schema_version(connection: sqlite3.Connection) -> int:
  row = connection.execute("SELECT schema_version FROM segment_metadata LIMIT 1").fetchone()
  if row is None:
    raise ValueError("database has no segment metadata")
  return int(row[0])
