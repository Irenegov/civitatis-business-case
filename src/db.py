"""Conexión centralizada a DuckDB y registro de las 5 vistas sobre /data/raw.

Todos los notebooks deberían obtener su conexión a través de este módulo en vez
de repetir los `CREATE OR REPLACE VIEW ... FROM '<csv>'` en cada uno (como se
hacía en notebooks/01_exploracion_inicial.ipynb).

Dos formas de conectar:

- `connect_raw()`: conexión en memoria con las 5 vistas registradas sobre los
  CSV originales. Pensada para exploración y como entrada del pipeline de
  limpieza (`src.identity`, `src.cleaning`).
- `connect_processed()`: abre `/data/processed/civitatis.duckdb`, generado por
  `python -m src.cleaning`, que ya contiene las tablas limpias
  (`ga_eventos_limpios`, `reservas_limpias`, `clientes_limpios`,
  `tours_limpios`, `eventos_con_cliente`) además de las 5 tablas originales.
  Los notebooks posteriores al de exploración inicial deberían usar esta
  función y no volver a leer/limpiar los CSV de `/data/raw`.
"""

from pathlib import Path

import duckdb

ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
PROCESSED_DB_PATH = PROCESSED_DIR / "civitatis.duckdb"

# nombre de vista/tabla -> fichero csv en /data/raw
RAW_TABLES = {
    "ga_eventos": "ga_eventos.csv",
    "reservas": "reservas.csv",
    "clientes": "clientes.csv",
    "tours": "tours.csv",
    "proveedores": "proveedores.csv",
}


def registrar_vistas_raw(con: duckdb.DuckDBPyConnection) -> None:
    """Registra las 5 vistas `CREATE OR REPLACE VIEW <nombre> AS SELECT * FROM <csv>`
    sobre la conexión dada, apuntando a los CSV de /data/raw."""
    for nombre, csv_file in RAW_TABLES.items():
        csv_path = (RAW_DIR / csv_file).resolve()
        con.execute(f"CREATE OR REPLACE VIEW {nombre} AS SELECT * FROM '{csv_path.as_posix()}'")


def connect_raw() -> duckdb.DuckDBPyConnection:
    """Abre una conexión DuckDB en memoria con las 5 vistas de /data/raw registradas."""
    con = duckdb.connect()
    registrar_vistas_raw(con)
    return con


def connect_processed(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Abre la base de datos ya limpia en /data/processed/civitatis.duckdb.

    Lanza FileNotFoundError con instrucciones si todavía no se ha generado.
    """
    if not PROCESSED_DB_PATH.exists():
        raise FileNotFoundError(
            f"No existe {PROCESSED_DB_PATH}. Genera la base ejecutando "
            "`python -m src.cleaning` desde la raíz del proyecto."
        )
    return duckdb.connect(str(PROCESSED_DB_PATH), read_only=read_only)
