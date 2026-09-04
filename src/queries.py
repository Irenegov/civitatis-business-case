"""
Consultas SQL de la app de Streamlit (`/app/main.py`), una función por
gráfico. Son las mismas consultas de los notebooks 02 y 03, adaptadas para
aceptar los filtros de fecha y canal del sidebar (`canal`, `fecha_desde`,
`fecha_hasta` como parámetros con nombre `$...`, `None` = sin filtrar).
"""

import duckdb


# === Estado del negocio (notebooks/02_negocio_y_destinos.ipynb, sección A) ===

def venta_bruta_vs_neta(con: duckdb.DuckDBPyConnection, canal=None, fecha_desde=None, fecha_hasta=None):
    return con.execute('''
        SELECT
            sum(importe_eur) AS venta_bruta,
            sum(importe_eur) FILTER (WHERE estado != 'cancelada') AS venta_neta
        FROM reservas_limpias
        WHERE ($canal IS NULL OR canal = $canal)
          AND ($fecha_desde IS NULL OR CAST(fecha_reserva AS DATE) >= $fecha_desde)
          AND ($fecha_hasta IS NULL OR CAST(fecha_reserva AS DATE) <= $fecha_hasta)
    ''', {'canal': canal, 'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta}).df()


def evolucion_mensual_venta_neta(con: duckdb.DuckDBPyConnection, canal=None, fecha_desde=None, fecha_hasta=None):
    # Envuelve la agregación mensual con generate_series + LEFT JOIN para que los meses
    # sin ninguna reserva aparezcan con venta_neta = 0 en vez de faltar en el resultado.
    return con.execute('''
        WITH rango AS (
            SELECT
                date_trunc('month', coalesce($fecha_desde::DATE, (SELECT min(fecha_reserva) FROM reservas_limpias))) AS mes_min,
                date_trunc('month', coalesce($fecha_hasta::DATE, (SELECT max(fecha_reserva) FROM reservas_limpias))) AS mes_max
        ),
        meses AS (
            SELECT unnest(generate_series(mes_min, mes_max, INTERVAL 1 MONTH)) AS mes
            FROM rango
        ),
        ventas AS (
            SELECT
                date_trunc('month', fecha_reserva) AS mes,
                sum(importe_eur) FILTER (WHERE estado != 'cancelada') AS venta_neta
            FROM reservas_limpias
            WHERE ($canal IS NULL OR canal = $canal)
              AND ($fecha_desde IS NULL OR CAST(fecha_reserva AS DATE) >= $fecha_desde)
              AND ($fecha_hasta IS NULL OR CAST(fecha_reserva AS DATE) <= $fecha_hasta)
            GROUP BY mes
        )
        SELECT
            m.mes,
            coalesce(v.venta_neta, 0) AS venta_neta
        FROM meses m
        LEFT JOIN ventas v ON m.mes = v.mes
        ORDER BY m.mes
    ''', {'canal': canal, 'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta}).df()


def tasa_cancelacion(con: duckdb.DuckDBPyConnection, canal=None, fecha_desde=None, fecha_hasta=None):
    return con.execute('''
        SELECT
            round(100.0 * sum(CASE WHEN estado = 'cancelada' THEN 1 ELSE 0 END) / count(*), 2) AS tasa_cancelacion_pct,
            count(*) AS total_reservas
        FROM reservas_limpias
        WHERE ($canal IS NULL OR canal = $canal)
          AND ($fecha_desde IS NULL OR CAST(fecha_reserva AS DATE) >= $fecha_desde)
          AND ($fecha_hasta IS NULL OR CAST(fecha_reserva AS DATE) <= $fecha_hasta)
    ''', {'canal': canal, 'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta}).df()


# === Destinos (notebooks/02_negocio_y_destinos.ipynb, sección B) ===

def ranking_destinos(con: duckdb.DuckDBPyConnection, canal=None, fecha_desde=None, fecha_hasta=None, limit=10):
    return con.execute('''
        WITH tours_destino AS (
            SELECT tour_id, regexp_extract(url, 'civitatis\\.com/es/([^/]+)/', 1) AS destino
            FROM tours
        )
        SELECT
            td.destino,
            sum(r.importe_eur) AS venta_neta
        FROM reservas_limpias r
        JOIN tours_destino td ON r.tour_id = td.tour_id
        WHERE r.estado != 'cancelada'
          AND ($canal IS NULL OR r.canal = $canal)
          AND ($fecha_desde IS NULL OR CAST(r.fecha_reserva AS DATE) >= $fecha_desde)
          AND ($fecha_hasta IS NULL OR CAST(r.fecha_reserva AS DATE) <= $fecha_hasta)
        GROUP BY td.destino
        ORDER BY venta_neta DESC
        LIMIT $limit
    ''', {'canal': canal, 'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta, 'limit': limit}).df()


def recurrencia_destinos(con: duckdb.DuckDBPyConnection, destinos, canal=None, fecha_desde=None, fecha_hasta=None):
    return con.execute('''
        WITH tours_destino AS (
            SELECT tour_id, regexp_extract(url, 'civitatis\\.com/es/([^/]+)/', 1) AS destino
            FROM tours
        ),
        clientes_destino AS (
            SELECT DISTINCT td.destino, r.user_id
            FROM reservas_limpias r
            JOIN tours_destino td ON r.tour_id = td.tour_id
            WHERE r.estado != 'cancelada' AND td.destino IN $destinos
              AND ($canal IS NULL OR r.canal = $canal)
              AND ($fecha_desde IS NULL OR CAST(r.fecha_reserva AS DATE) >= $fecha_desde)
              AND ($fecha_hasta IS NULL OR CAST(r.fecha_reserva AS DATE) <= $fecha_hasta)
        )
        SELECT
            cd.destino,
            count(*) AS total_clientes,
            round(100.0 * sum(CASE WHEN cr.es_recurrente THEN 1 ELSE 0 END) / count(*), 2) AS pct_recurrencia
        FROM clientes_destino cd
        JOIN clientes_recurrentes cr ON cd.user_id = cr.user_id
        GROUP BY cd.destino
        ORDER BY pct_recurrencia DESC
    ''', {'destinos': tuple(destinos), 'canal': canal, 'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta}).df()


# === Repetición (notebooks/03_repeticion.ipynb) ===

def recurrencia_por_canal(con: duckdb.DuckDBPyConnection, fecha_desde=None, fecha_hasta=None):
    return con.execute('''
        WITH clientes_canal AS (
            SELECT DISTINCT canal, user_id
            FROM reservas_limpias
            WHERE estado != 'cancelada'
              AND ($fecha_desde IS NULL OR CAST(fecha_reserva AS DATE) >= $fecha_desde)
              AND ($fecha_hasta IS NULL OR CAST(fecha_reserva AS DATE) <= $fecha_hasta)
        )
        SELECT
            cc.canal,
            count(*) AS total_clientes,
            round(100.0 * sum(CASE WHEN cr.es_recurrente THEN 1 ELSE 0 END) / count(*), 2) AS pct_recurrencia
        FROM clientes_canal cc
        JOIN clientes_recurrentes cr ON cc.user_id = cr.user_id
        GROUP BY cc.canal
        ORDER BY pct_recurrencia DESC
    ''', {'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta}).df()


def recurrencia_por_dispositivo(con: duckdb.DuckDBPyConnection):
    return con.execute('''
        WITH eventos_dispositivo AS (
            SELECT user_id, device, count(*) AS n_eventos
            FROM eventos_con_id
            WHERE user_id IS NOT NULL
            GROUP BY user_id, device
        ),
        dispositivo_dominante AS (
            SELECT user_id, device AS dispositivo_dominante
            FROM (
                SELECT user_id, device, n_eventos,
                       row_number() OVER (PARTITION BY user_id ORDER BY n_eventos DESC, device) AS rn
                FROM eventos_dispositivo
            )
            WHERE rn = 1
        )
        SELECT
            dd.dispositivo_dominante,
            count(*) AS total_clientes,
            round(100.0 * sum(CASE WHEN cr.es_recurrente THEN 1 ELSE 0 END) / count(*), 2) AS pct_recurrencia
        FROM dispositivo_dominante dd
        JOIN clientes_recurrentes cr ON dd.user_id = cr.user_id
        GROUP BY dd.dispositivo_dominante
        ORDER BY pct_recurrencia DESC
    ''').df()


def sesiones_con_sin_user_id(con: duckdb.DuckDBPyConnection):
    return con.execute('''
        WITH sesiones_id AS (
            SELECT session_id, bool_or(user_id IS NOT NULL) AS tiene_user_id
            FROM eventos_con_id
            GROUP BY session_id
        )
        SELECT
            CASE WHEN tiene_user_id THEN 'con user_id (conocido)' ELSE 'sin user_id (desconocido)' END AS tipo_sesion,
            count(*) AS n_sesiones,
            round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_sesiones
        FROM sesiones_id
        GROUP BY tiene_user_id
        ORDER BY tiene_user_id DESC
    ''').df()


def conversion_por_dispositivo(con: duckdb.DuckDBPyConnection):
    return con.execute('''
        WITH eventos_dispositivo_sesion AS (
            SELECT session_id, device, count(*) AS n_eventos
            FROM eventos_con_id
            GROUP BY session_id, device
        ),
        dispositivo_dominante_sesion AS (
            SELECT session_id, device AS dispositivo_dominante
            FROM (
                SELECT session_id, device, n_eventos,
                       row_number() OVER (PARTITION BY session_id ORDER BY n_eventos DESC, device) AS rn
                FROM eventos_dispositivo_sesion
            )
            WHERE rn = 1
        )
        SELECT
            dds.dispositivo_dominante,
            count(*) AS total_sesiones,
            round(100.0 * sum(CASE WHEN sc.convirtio THEN 1 ELSE 0 END) / count(*), 2) AS tasa_conversion_pct
        FROM dispositivo_dominante_sesion dds
        JOIN sesiones_con_conversion sc ON dds.session_id = sc.session_id
        WHERE dds.dispositivo_dominante IN ('mobile', 'desktop')
        GROUP BY dds.dispositivo_dominante
        ORDER BY tasa_conversion_pct DESC
    ''').df()


def intervalo_recompra(con: duckdb.DuckDBPyConnection, fecha_desde=None, fecha_hasta=None):
    return con.execute('''
        WITH reservas_ordenadas AS (
            SELECT
                r.user_id,
                r.fecha_reserva,
                row_number() OVER (PARTITION BY r.user_id ORDER BY r.fecha_reserva, r.reserva_id) AS n_reserva,
                LAG(r.fecha_reserva) OVER (PARTITION BY r.user_id ORDER BY r.fecha_reserva, r.reserva_id) AS fecha_reserva_anterior
            FROM reservas_limpias r
            JOIN clientes_recurrentes cr ON r.user_id = cr.user_id
            WHERE r.estado != 'cancelada' AND cr.es_recurrente
              AND ($fecha_desde IS NULL OR CAST(r.fecha_reserva AS DATE) >= $fecha_desde)
              AND ($fecha_hasta IS NULL OR CAST(r.fecha_reserva AS DATE) <= $fecha_hasta)
        )
        SELECT
            round(avg(date_diff('day', fecha_reserva_anterior, fecha_reserva)), 2) AS intervalo_medio_dias,
            count(*) AS n_clientes_recurrentes
        FROM reservas_ordenadas
        WHERE n_reserva = 2
    ''', {'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta}).df()


# === Filtros del sidebar ===

def canales_disponibles(con: duckdb.DuckDBPyConnection):
    return con.execute("SELECT DISTINCT canal FROM reservas_limpias ORDER BY canal").df()['canal'].tolist()


def meses_disponibles(con: duckdb.DuckDBPyConnection):
    return con.execute('''
        SELECT DISTINCT strftime(CAST(fecha_reserva AS DATE), '%Y-%m') AS mes
        FROM reservas_limpias
        ORDER BY mes
    ''').df()['mes'].tolist()
