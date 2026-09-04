"""
Métricas de negocio, cada una su propia CREATE TABLE, sobre la base ya
limpia (`reservas_limpias`, `eventos_con_id`). 
Para regenerarlas: `python -m src.metricas` (requiere haber ejecutado antes `python -m src.limpieza`).
"""

import duckdb

from src import conexion


def construir_metricas() -> None:
    con = conexion.connect_processed(read_only=False)
    try:
        # 1) ventas: por día de fecha_reserva (día en que se confirma/genera la
        # reserva, no fecha_actividad, que es cuándo se disfruta el tour y puede
        # ser meses después). Contamos la venta cuando se reconoce el ingreso,
        # no cuando se presta el servicio. venta_bruta = todas las reservas;
        # venta_neta = excluyendo las canceladas.
        con.execute("""
            CREATE OR REPLACE TABLE ventas AS
            SELECT
                CAST(fecha_reserva AS DATE) AS fecha_reserva,
                sum(importe_eur) AS venta_bruta,
                sum(importe_eur) FILTER (WHERE estado != 'cancelada') AS venta_neta
            FROM reservas_limpias
            GROUP BY CAST(fecha_reserva AS DATE)
        """)

        # 2) clientes_recurrentes: a nivel user_id, cuenta reservas no
        # canceladas (una reserva cancelada no es una compra real). 
        # Cliente recurrente = 2 o más reservas no canceladas.
        con.execute("""
            CREATE OR REPLACE TABLE clientes_recurrentes AS
            SELECT
                user_id,
                count(*) AS reservas_no_canceladas,
                count(*) >= 2 AS es_recurrente
            FROM reservas_limpias
            WHERE estado != 'cancelada'
            GROUP BY user_id
        """)

        # 3) sesiones_con_conversion: a nivel session_id, marca si en algún
        # momento de esa sesión hubo un evento 'purchase'.
        con.execute("""
            CREATE OR REPLACE TABLE sesiones_con_conversion AS
            SELECT
                session_id,
                bool_or(event_name = 'purchase') AS convirtio
            FROM eventos_con_id
            GROUP BY session_id
        """)
    finally:
        con.close()


def main() -> None:
    construir_metricas()
    print(f"Tablas de métricas (ventas, clientes_recurrentes, sesiones_con_conversion) generadas en {conexion.PROCESSED_DB_PATH}")


if __name__ == "__main__":
    main()
