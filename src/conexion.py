"""
Conexión centralizada a DuckDB y registro de los archivos sobre /data/raw.

Todos los notebooks deberían obtener su conexión a través de este módulo en vez
de repetir los `CREATE OR REPLACE VIEW ... FROM '<csv>'` en cada uno (como se
hacía en notebooks/01_exploracion_inicial.ipynb).


- `connect_processed()`: abre `/data/processed/civitatis.duckdb`, generado por
  `python -m src.limpieza`, que ya contiene las tablas limpias
  (`reservas_limpias`, `clientes_limpios`, `eventos_con_id`) además de las
  vistas originales sobre /data/raw. 
  Los notebooks posteriores al de exploración inicial
  deberían usar esta función y no volver a leer/limpiar los CSV de
  `/data/raw`.
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
    """
    Registra las vistas `CREATE OR REPLACE VIEW <nombre> AS SELECT * FROM <csv>`
    sobre la conexión dada, apuntando a los CSV de /data/raw.
    """
    for nombre, csv_file in RAW_TABLES.items():
        csv_path = (RAW_DIR / csv_file).resolve()
        con.execute(f"CREATE OR REPLACE VIEW {nombre} AS SELECT * FROM '{csv_path.as_posix()}'")


def connect_processed(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """
    Abre la base de datos ya limpia en /data/processed/civitatis.duckdb.

    Lanza FileNotFoundError con instrucciones si todavía no se ha generado.
    """
    if not PROCESSED_DB_PATH.exists():
        raise FileNotFoundError(
            f"No existe {PROCESSED_DB_PATH}. Genera la base ejecutando "
            "`python -m src.limpieza` desde la raíz del proyecto."
        )
    return duckdb.connect(str(PROCESSED_DB_PATH), read_only=read_only)
