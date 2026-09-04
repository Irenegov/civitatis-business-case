"""
Limpieza de datos sobre DuckDB.

Cada paso de limpieza es una única sentencia CREATE TABLE. Los pasos intermedios de la
resolución de identidad (`eventos_limpios`, `paso1`, `paso2`) se dejan como
VIEW en vez de TABLE para evitar aumentar el tamaño del archivo final. 
Solo `eventos_con_id`, el resultado final, se necesita como tabla. 
Todo se guarda en /data/processed/civitatis.duckdb. 
Para regenerarlo: `python -m src.limpieza`.
"""

from datetime import datetime

import duckdb

from src import conexion

REPORTS_DIR = conexion.ROOT_DIR / "reports"
REPORT_PATH = REPORTS_DIR / "data_quality_report.md"


def construir_base_procesada() -> dict:
    conexion.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(conexion.PROCESSED_DB_PATH))
    try:
        # tours se materializa como TABLE porque src/queries.py la consulta
        # directamente (ranking_destinos y demás); el resto queda como VIEW
        # sobre /data/raw, que solo hace falta al regenerar esta base.
        conexion.registrar_vistas_raw(con, materializar={"tours"})  # ga_eventos, reservas, clientes, tours, proveedores

        # Números "antes", para la comparación posterior en el informe
        reservas_antes_filas, reservas_antes_importe = con.execute(
            "SELECT count(*), sum(importe_eur) FROM reservas"
        ).fetchone()
        eventos_antes_filas = con.execute("SELECT count(*) FROM ga_eventos").fetchone()[0]
        clientes_antes_filas = con.execute("SELECT count(*) FROM clientes").fetchone()[0]

        # 1) reservas_limpias: normaliza 'estado' a minúsculas (confirmada/cancelada/pendiente) y elimina las 30 reservas con personas <= 0 (no existe una reserva de "0" o "-1" personas, es un error de captura)
        #
        # 'tour_gratuito': de las 1.297 reservas con importe_eur = 0€ en /data/raw (investigado
        # con SQL sobre los datos crudos; 1.295 de esas 1.297 siguen en reservas_limpias, ya que
        # 2 de ellas también tenían personas <= 0 y se eliminan en el filtro de más abajo), el
        # 100% corresponde a tours cuyo precio_por_persona_eur en el catálogo
        # también es 0€ — no hay ni un solo caso de tour de pago cobrado a 0€. No son errores de
        # cobro, así que no se excluyen de venta_bruta/venta_neta (tampoco cambiaría la cifra: son
        # 0€). Se deja esta columna para dejar constancia explícita de que se investigó y documentar
        # cuántas reservas "de importe 0" son en realidad tours gratuitos legítimos.
        con.execute("""
            CREATE OR REPLACE TABLE reservas_limpias AS
            SELECT
                r.reserva_id,
                r.user_id,
                r.tour_id,
                r.proveedor_id,
                r.fecha_reserva,
                r.fecha_actividad,
                CASE lower(r.estado) WHEN 'cancelled' THEN 'cancelada' ELSE lower(r.estado) END AS estado,
                r.personas,
                r.importe_eur,
                t.precio_por_persona_eur = 0 AS tour_gratuito,
                r.campana,
                r.canal
            FROM reservas r
            LEFT JOIN tours t ON r.tour_id = t.tour_id
            WHERE r.personas > 0
        """)

        # 2) eventos_limpios: elimina los 798 eventos duplicados exactos y normaliza 'device' (mobile/desktop/tablet, corrige el typo 'desktp')
        con.execute("""
            CREATE OR REPLACE VIEW eventos_limpios AS
            SELECT DISTINCT
                cookie_id,
                temp_client_id,
                user_id,
                session_id,
                event_date,
                event_name,
                url,
                ip,
                pais_ip,
                ciudad_ip,
                CASE lower(device) WHEN 'desktp' THEN 'desktop' ELSE lower(device) END AS device,
                reserva_id
            FROM ga_eventos
        """)

        # 3) clientes_limpios: sin cambios estructurales necesarios, solo se renombra la tabla para mantener el mismo criterio (*_limpios) que las demás
        con.execute("""
            CREATE OR REPLACE TABLE clientes_limpios AS
            SELECT * FROM clientes
        """)

        # 4) paso1: primer intento de identificar al visitante -> usa user_id cuando existe (visitante autenticado)
        con.execute("""
            CREATE OR REPLACE VIEW paso1 AS
            SELECT *, CAST(user_id AS VARCHAR) AS id
            FROM eventos_limpios
        """)

        # 5) paso2: si el paso1 se quedó sin id (visitante anónimo), usa cookie_id
        con.execute("""
            CREATE OR REPLACE VIEW paso2 AS
            SELECT * EXCLUDE (id), COALESCE(id, cookie_id) AS id
            FROM paso1
        """)

        # 6) eventos_con_id: si el paso2 sigue sin id, usa temp_client_id (último recurso)
        con.execute("""
            CREATE OR REPLACE TABLE eventos_con_id AS
            SELECT * EXCLUDE (id), COALESCE(id, temp_client_id) AS id
            FROM paso2
        """)

        metricas = calcular_impacto_limpieza(
            con,
            reservas_antes_filas=reservas_antes_filas,
            reservas_antes_importe=reservas_antes_importe,
            eventos_antes_filas=eventos_antes_filas,
            clientes_antes_filas=clientes_antes_filas,
        )
    finally:
        con.close()

    return metricas


def calcular_impacto_limpieza(con: duckdb.DuckDBPyConnection, *, reservas_antes_filas, reservas_antes_importe,
                       eventos_antes_filas, clientes_antes_filas) -> dict:
    """
    Consulta las tablas ya creadas para poder explicar, con números reales, qué cambió en cada paso.
    """
    m: dict = {}

    # --- reservas_limpias ---
    m["reservas_antes_filas"] = reservas_antes_filas
    m["reservas_antes_importe"] = round(reservas_antes_importe, 2)

    m["reservas_estado_filas_cambiadas"] = con.execute("""
        SELECT count(*) FROM reservas
        WHERE estado != CASE lower(estado) WHEN 'cancelled' THEN 'cancelada' ELSE lower(estado) END
    """).fetchone()[0]

    filas_eliminadas, importe_eliminado = con.execute(
        "SELECT count(*), coalesce(sum(importe_eur), 0) FROM reservas WHERE personas <= 0"
    ).fetchone()
    m["reservas_personas_invalidas_filas"] = filas_eliminadas
    m["reservas_personas_invalidas_importe"] = round(importe_eliminado, 2)

    reservas_despues_filas, reservas_despues_importe = con.execute(
        "SELECT count(*), sum(importe_eur) FROM reservas_limpias"
    ).fetchone()
    m["reservas_despues_filas"] = reservas_despues_filas
    m["reservas_despues_importe"] = round(reservas_despues_importe, 2)

    m["reservas_importe_cero_filas"] = con.execute(
        "SELECT count(*) FROM reservas_limpias WHERE importe_eur = 0"
    ).fetchone()[0]
    m["reservas_importe_cero_tour_gratuito_filas"] = con.execute(
        "SELECT count(*) FROM reservas_limpias WHERE importe_eur = 0 AND tour_gratuito"
    ).fetchone()[0]
    m["reservas_importe_cero_sospechosas_filas"] = con.execute(
        "SELECT count(*) FROM reservas_limpias WHERE importe_eur = 0 AND NOT tour_gratuito"
    ).fetchone()[0]
    m["reservas_importe_cero_por_estado"] = con.execute("""
        SELECT estado, count(*) FROM reservas_limpias
        WHERE importe_eur = 0
        GROUP BY estado
        ORDER BY count(*) DESC
    """).fetchall()

    # --- eventos_limpios ---
    m["eventos_antes_filas"] = eventos_antes_filas
    eventos_despues_filas = con.execute("SELECT count(*) FROM eventos_limpios").fetchone()[0]
    m["eventos_despues_filas"] = eventos_despues_filas
    m["eventos_duplicados_eliminados"] = eventos_antes_filas - eventos_despues_filas

    m["eventos_device_filas_cambiadas"] = con.execute("""
        SELECT count(*) FROM ga_eventos
        WHERE device != CASE lower(device) WHEN 'desktp' THEN 'desktop' ELSE lower(device) END
    """).fetchone()[0]

    # --- clientes_limpios ---
    m["clientes_filas"] = clientes_antes_filas

    # --- resolución de identidad, paso a paso ---
    m["identidad_total_eventos"] = con.execute("SELECT count(*) FROM eventos_con_id").fetchone()[0]
    m["identidad_paso1_resueltos"] = con.execute("SELECT count(*) FROM paso1 WHERE id IS NOT NULL").fetchone()[0]
    m["identidad_paso2_resueltos"] = con.execute("SELECT count(*) FROM paso2 WHERE id IS NOT NULL").fetchone()[0]
    m["identidad_final_resueltos"] = con.execute("SELECT count(*) FROM eventos_con_id WHERE id IS NOT NULL").fetchone()[0]
    m["identidad_resueltos_por_cookie"] = m["identidad_paso2_resueltos"] - m["identidad_paso1_resueltos"]
    m["identidad_resueltos_por_temp_client_id"] = m["identidad_final_resueltos"] - m["identidad_paso2_resueltos"]
    m["identidad_sin_resolver"] = m["identidad_total_eventos"] - m["identidad_final_resueltos"]

    return m


def generar_informe_calidad(m: dict) -> str:
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""# Informe de calidad de datos — Civitatis

_Generado automáticamente por `python -m src.limpieza`. Fecha: {fecha}._

Este informe explica qué se ha limpiado en cada tabla
y cuánto cambian los números por ello.

## 1. Reservas (`reservas` → `reservas_limpias`)

- **Estados escritos de formas distintas**: `estado` venía con mayúsculas y
  hasta un valor en inglés (`CONFIRMADA`, `Confirmada`, `confirmada`,
  `CANCELLED`, `Cancelada`, `cancelada`...) para referirse a solo 3
  situaciones reales. Se ha dejado todo en minúsculas y en español
  (`confirmada` / `cancelada` / `pendiente`). Esto afectó a
  **{m['reservas_estado_filas_cambiadas']:,} reservas** — no cambia ningún
  importe, solo cómo se escribe el estado.

- **Reservas con 0 o menos personas**: no tiene sentido reservar un tour para
  "0" o "-1" personas, así que se han eliminado directamente. Eran
  **{m['reservas_personas_invalidas_filas']} reservas**, que sumaban
  **{m['reservas_personas_invalidas_importe']:,.2f} €**.

- **Reservas con importe 0€ (decisión pendiente del análisis exploratorio,
  ahora resuelta)**: había **{m['reservas_importe_cero_filas']:,} reservas**
  con `importe_eur = 0€`, y quedaba por confirmar si eran tours realmente
  gratuitos o cancelaciones/errores sin cobro. Cruzando cada una con el
  precio de catálogo de su tour (`tours.precio_por_persona_eur`):
  **{m['reservas_importe_cero_tour_gratuito_filas']:,} de
  {m['reservas_importe_cero_filas']:,} ({100 * m['reservas_importe_cero_tour_gratuito_filas'] / m['reservas_importe_cero_filas']:.2f}%)**
  corresponden a un tour cuyo precio de catálogo también es 0€ — son tours
  gratuitos legítimos — y **{m['reservas_importe_cero_sospechosas_filas']:,}**
  corresponden a un tour de pago cobrado a 0€ (caso sospechoso de error).
  Desglose por estado de las {m['reservas_importe_cero_filas']:,} reservas
  con importe 0€: {', '.join(f"{n:,} {estado}" for estado, n in m['reservas_importe_cero_por_estado'])}.
  No se han excluido de `venta_bruta`/`venta_neta` ni de ningún conteo:
  al sumar 0€, no alteran ninguna cifra, y se ha añadido la columna
  `tour_gratuito` a `reservas_limpias` para dejar constancia explícita de
  que se investigó y documentar qué reservas son gratuitas por diseño.

**Resultado**: las reservas pasan de {m['reservas_antes_filas']:,} a
{m['reservas_despues_filas']:,} filas, y el importe total pasa de
{m['reservas_antes_importe']:,.2f} € a {m['reservas_despues_importe']:,.2f} €
(una bajada de {m['reservas_antes_importe'] - m['reservas_despues_importe']:,.2f} €,
un {100 * (m['reservas_antes_importe'] - m['reservas_despues_importe']) / m['reservas_antes_importe']:.2f}% del total).


## 2. Eventos web (`ga_eventos` → `eventos_limpios`)

- **Eventos duplicados**: había eventos guardados dos veces de forma
  idéntica. Se han eliminado **{m['eventos_duplicados_eliminados']:,} filas**
  duplicadas.

- **Dispositivo escrito de formas distintas**: `device` venía como
  `Mobile`/`mobile`, `Desktop`/`desktop`, `tablet`, y con un error de
  escritura (`desktp`). Se ha dejado todo en minúsculas y corregido el error,
  afectando a **{m['eventos_device_filas_cambiadas']:,} filas**.

**Resultado**: los eventos pasan de {m['eventos_antes_filas']:,} a
{m['eventos_despues_filas']:,} filas.


## 3. Clientes (`clientes` → `clientes_limpios`)

No se ha encontrado ningún problema que corregir en esta tabla (según lo
visto en el análisis exploratorio). Se copia tal cual, solo con el nombre
`clientes_limpios` para seguir el mismo criterio que el resto de tablas.
Sigue teniendo **{m['clientes_filas']:,} clientes**.


## 4. Identificar al visitante detrás de cada evento (`paso1` → `paso2` → `eventos_con_id`)

Cada evento de `eventos_limpios` trae tres posibles identificadores del
visitante (`user_id`, `cookie_id`, `temp_client_id`), y no siempre vienen
todos rellenos. Se resuelve en 3 pasos, cada uno en su propia consulta para
poder revisarlo por separado (`paso1` y `paso2` son VIEW, no TABLE: solo
`eventos_con_id`, el resultado final, se guarda como tabla):

1. **`paso1`** — usa `user_id` cuando el visitante ha iniciado sesión. Así se
   identifican **{m['identidad_paso1_resueltos']:,}** de {m['identidad_total_eventos']:,}
   eventos ({100 * m['identidad_paso1_resueltos'] / m['identidad_total_eventos']:.2f}%).

2. **`paso2`** — para los eventos que siguen sin id, usa `cookie_id` (el
   identificador anónimo del navegador). Con esto se identifican
   **{m['identidad_resueltos_por_cookie']:,} eventos** más, llegando a
   **{m['identidad_paso2_resueltos']:,}** en total
   ({100 * m['identidad_paso2_resueltos'] / m['identidad_total_eventos']:.2f}%).

3. **`eventos_con_id`** — para los que aún faltan, usa `temp_client_id` como
   último recurso. Esto resuelve **{m['identidad_resueltos_por_temp_client_id']:,}
   eventos** adicionales.


**Resultado final**: de {m['identidad_total_eventos']:,} eventos,
**{m['identidad_final_resueltos']:,}** quedan con un id de visitante asignado
({100 * m['identidad_final_resueltos'] / m['identidad_total_eventos']:.2f}%), y
**{m['identidad_sin_resolver']:,}** se quedan sin ninguno de los tres
identificadores.
"""


def main() -> None:
    metricas = construir_base_procesada()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(generar_informe_calidad(metricas), encoding="utf-8")

    print(f"Base procesada generada en {conexion.PROCESSED_DB_PATH}")
    print(f"Informe de calidad generado en {REPORT_PATH}")


if __name__ == "__main__":
    main()
