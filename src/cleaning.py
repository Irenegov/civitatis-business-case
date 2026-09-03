"""Limpieza de datos en SQL sobre DuckDB.

Cada inconsistencia detectada en `notebooks/01_exploracion_inicial.ipynb`
(duplicados, fechas imposibles, categorías inconsistentes, nulos, outliers,
FKs rotas) se resuelve aquí como una vista SQL nueva, con la decisión de
tratamiento razonada en un comentario SQL junto a la columna afectada.

Criterio general aplicado en todo el módulo:

- **Excluir** solo cuando la fila no aporta información nueva (duplicado
  exacto) o el valor no tiene ninguna interpretación de negocio válida.
- **Imputar** cuando el valor correcto es inequívoco (typo conocido, mezcla
  de dos formatos de fecha que entre los dos cubren el 100% de los casos,
  categoría escrita de formas distintas pero con el mismo significado).
- **Flag** (marcar con una columna booleana, sin tocar la fila) cuando el
  dato es dudoso pero el resto de la fila sigue siendo información de
  negocio válida — típicamente una reserva con importe real pero con una FK
  rota (`proveedor_id`) o un campo secundario inválido (`personas`). Excluir
  la reserva completa en estos casos infravaloraría los ingresos.

Este módulo solo define las vistas de limpieza (`crear_vistas_limpias`) y
orquesta su persistencia (`construir_base_procesada`). La resolución de
identidad de `ga_eventos` vive en `src.identity`.
"""

from datetime import datetime

import duckdb

from src import db, identity

REPORTS_DIR = db.ROOT_DIR / "reports"
REPORT_PATH = REPORTS_DIR / "data_quality_report.md"


# ---------------------------------------------------------------------------
# ga_eventos -> ga_eventos_limpios
# ---------------------------------------------------------------------------

SQL_GA_EVENTOS_LIMPIOS = """
SELECT DISTINCT
    -- (1) DUPLICADOS EXACTOS: 798 filas de ga_eventos están repetidas
    -- íntegramente (mismo evento registrado dos veces). Se EXCLUYEN con
    -- SELECT DISTINCT: una fila idéntica a otra no aporta información nueva
    -- y, si se mantuviera, infla artificialmente cualquier conteo de
    -- eventos/tráfico.
    cookie_id,
    temp_client_id,
    user_id,
    session_id,

    -- (2) event_date MIXTO: la columna llega como VARCHAR porque mezcla dos
    -- formatos de fecha (ISO 'YYYY-MM-DD HH:MI:SS' y europeo
    -- 'DD/MM/YYYY HH:MI'). Entre los dos formatos cubren el 100% de las
    -- filas (0 sin parsear por ninguno de los dos), así que se IMPUTA
    -- reconstruyendo un TIMESTAMP real combinando ambos parsers en vez de
    -- descartar el ~4,6% de filas que solo se leían con el formato ISO.
    COALESCE(
        try_strptime(event_date, '%Y-%m-%d %H:%M:%S'),
        try_strptime(event_date, '%d/%m/%Y %H:%M')
    ) AS event_ts,
    event_date AS event_date_original,

    event_name,
    url,
    ip,
    pais_ip,
    ciudad_ip,

    -- (3) device INCONSISTENTE: mayúsculas mezcladas (Mobile/mobile,
    -- Desktop/desktop, tablet) y un typo ('desktp'). Se IMPUTA normalizando
    -- a minúsculas y corrigiendo el typo conocido: el valor real es
    -- inequívoco en los tres casos, no hay ambigüedad que justifique
    -- excluir la fila o dejar el campo en nulo.
    CASE lower(device)
        WHEN 'desktp' THEN 'desktop'
        ELSE lower(device)
    END AS device,

    reserva_id,

    -- (4) reserva_id HUÉRFANO: ~40 eventos de compra referencian un
    -- reserva_id que no existe en `reservas` (probable desfase entre el
    -- registro de analítica y la persistencia de la reserva en BBDD). Se
    -- FLAGEA en vez de excluir: el evento de compra sí ocurrió y es
    -- información válida de comportamiento; lo que falla aguas abajo es la
    -- reserva, no el evento.
    (
        reserva_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM reservas r WHERE r.reserva_id = ga_eventos.reserva_id)
    ) AS reserva_id_huerfano

FROM ga_eventos
"""


# ---------------------------------------------------------------------------
# clientes -> clientes_limpios
# ---------------------------------------------------------------------------

SQL_CLIENTES_LIMPIOS = """
SELECT
    user_id,
    nombre,
    apellidos,
    direccion,
    email,
    telefono,

    -- (5) fecha_alta FUTURA (1 fila): un alta no puede registrarse "en el
    -- futuro" -> error de captura. Se IMPUTA a NULL en vez de inventar una
    -- fecha plausible (no hay forma de reconstruir la fecha real a partir
    -- del resto de columnas), y se deja constancia en fecha_alta_corregida
    -- para no perder la fila ni la trazabilidad del cambio.
    CASE WHEN fecha_alta > CURRENT_DATE THEN NULL ELSE fecha_alta END AS fecha_alta,
    (fecha_alta > CURRENT_DATE) AS fecha_alta_corregida,

    -- (6) fecha_baja FUTURA (40 filas): mismo razonamiento que fecha_alta —
    -- no se puede dar de baja "en el futuro". Se IMPUTA a NULL (equivale a
    -- "sigue de alta / fecha de baja desconocida") en vez de arriesgarse a
    -- fabricar una fecha de baja falsa.
    CASE WHEN fecha_baja > CURRENT_DATE THEN NULL ELSE fecha_baja END AS fecha_baja,
    (fecha_baja > CURRENT_DATE) AS fecha_baja_corregida,

    fecha_nacimiento,
    dni,

    -- (7) dni DUPLICADO: mismo DNI compartido por dos filas con distinto
    -- user_id y distinto email (y mismo nombre+apellidos en todos los casos
    -- observados) -> muy probablemente la misma persona registrada dos
    -- veces. No se fusionan ni se eliminan filas: ambos user_id están
    -- referenciados desde `reservas`/`ga_eventos`, y fusionarlos sin más
    -- contexto de negocio (¿cuál de los dos historiales de compra es el
    -- "bueno"?) podría atribuir incorrectamente compras entre dos cuentas
    -- reales. Se FLAGEA para que el análisis de clientes únicos decida.
    (dni IN (SELECT dni FROM clientes GROUP BY dni HAVING count(*) > 1)) AS dni_duplicado

FROM clientes
"""


# ---------------------------------------------------------------------------
# reservas -> reservas_limpias
# ---------------------------------------------------------------------------

SQL_RESERVAS_LIMPIAS = """
SELECT
    reserva_id,
    user_id,
    tour_id,
    proveedor_id,

    -- (8) proveedor_id HUÉRFANO: ~187 reservas (~2,2%) referencian un
    -- proveedor_id que no existe en `proveedores` (además de 1 tour, ver
    -- tours_limpios). Se FLAGEA, no se excluye: la reserva y su importe son
    -- reales y facturables — el problema es un hueco en el maestro de
    -- proveedores, no una reserva inválida. Excluirla infravaloraría los
    -- ingresos.
    NOT EXISTS (SELECT 1 FROM proveedores p WHERE p.proveedor_id = r.proveedor_id) AS proveedor_huerfano,

    fecha_reserva,

    -- fecha_actividad EN EL FUTURO (24 filas): NO se trata como error (ver
    -- notebook 01, sección 4) — son reservas de tours para fechas próximas,
    -- comportamiento esperado de cualquier negocio de reservas.
    fecha_actividad,

    -- (9) estado INCONSISTENTE: mismo valor en distinta grafía/idioma
    -- (CONFIRMADA/Confirmada/confirmada; Cancelada/cancelada/CANCELLED). Se
    -- IMPUTA normalizando a 3 valores canónicos en español -- el
    -- significado de negocio es inequívoco (CANCELLED es sencillamente
    -- "cancelada" en inglés, no un cuarto estado).
    CASE lower(estado)
        WHEN 'cancelled' THEN 'cancelada'
        ELSE lower(estado)
    END AS estado,
    estado AS estado_original,

    personas,

    -- (10) personas <= 0 (30 filas: 15 con 0, 15 con -1): error de captura
    -- evidente, no un caso extremo estadístico (no existe una reserva de
    -- "0" o "-1" personas; el propio cálculo IQR no lo detecta como
    -- outlier, ver notebook 01 sección 3). Se FLAGEA en vez de excluir la
    -- reserva completa: importe_eur y estado siguen siendo información de
    -- ingresos válida y verificable; solo debe excluirse de métricas que
    -- dependan de `personas` (p. ej. importe medio por persona).
    (personas <= 0) AS personas_invalida,

    importe_eur,
    -- (11) importe_eur = 0 (1.297 filas): se comprobó por JOIN contra
    -- `tours` que las 1.297 corresponden a reservas de tours cuyo
    -- precio_por_persona_eur también es 0 en el catálogo -> son tours
    -- gratuitos reales, no reservas sin cobrar. Verificación reproducible en
    -- calcular_metricas_calidad(). SIN TRATAMIENTO: el dato es correcto.
    -- (12) importe_eur OUTLIERS (>283,22€ según IQR, 237 filas): se
    -- mantienen sin modificar (ver notebook 01, sección 3) — son reservas
    -- grupales/tours premium legítimos, no ruido de captura.

    campana,
    canal

FROM reservas r
"""


# ---------------------------------------------------------------------------
# tours -> tours_limpios
# ---------------------------------------------------------------------------

SQL_TOURS_LIMPIOS = """
SELECT
    t.tour_id,
    t.url,
    t.descripcion,
    t.precio_por_persona_eur,
    t.proveedor_id,

    -- (13) proveedor_id HUÉRFANO: 1 tour referencia un proveedor_id
    -- inexistente en `proveedores`. Mismo tratamiento y misma razón que en
    -- reservas_limpias: se FLAGEA, no se excluye (el tour es real y con
    -- precio válido).
    NOT EXISTS (SELECT 1 FROM proveedores p WHERE p.proveedor_id = t.proveedor_id) AS proveedor_huerfano

FROM tours t
"""


def _create(con: duckdb.DuckDBPyConnection, name: str, select_sql: str, materialize: bool = False) -> None:
    kind = "TABLE" if materialize else "VIEW"
    con.execute(f"CREATE OR REPLACE {kind} {name} AS {select_sql}")


def crear_vistas_limpias(con: duckdb.DuckDBPyConnection, materialize: bool = False) -> None:
    """Crea, sobre `con`, las vistas (o tablas) de limpieza descritas arriba.

    Requiere que las 5 vistas raw (`ga_eventos`, `reservas`, `clientes`,
    `tours`, `proveedores`) ya estén registradas, p. ej. con
    `src.db.connect_raw()` o `src.db.registrar_vistas_raw(con)`.
    """
    # clientes_limpios primero: reservas_limpias y eventos_con_cliente no
    # dependen de ella, pero mantener el orden de dependencias explícito
    # (raw -> *_limpios -> eventos_con_cliente) evita sorpresas si se amplía.
    _create(con, "clientes_limpios", SQL_CLIENTES_LIMPIOS, materialize)
    _create(con, "ga_eventos_limpios", SQL_GA_EVENTOS_LIMPIOS, materialize)
    _create(con, "reservas_limpias", SQL_RESERVAS_LIMPIAS, materialize)
    _create(con, "tours_limpios", SQL_TOURS_LIMPIOS, materialize)
    identity.crear_vista_identidad(con, materialize)  # depende de las dos primeras


# ---------------------------------------------------------------------------
# Métricas de calidad (para el informe)
# ---------------------------------------------------------------------------

def calcular_metricas_calidad(con: duckdb.DuckDBPyConnection) -> dict:
    """Cuantifica, con SQL sobre `con`, el impacto de cada decisión de
    limpieza. Requiere que las vistas raw y las *_limpias ya existan.

    Se recalcula todo dinámicamente (nada de números fijados a mano) para que
    el informe siga siendo correcto si cambian los CSV de origen.
    """
    m: dict = {}

    # --- ga_eventos ---------------------------------------------------
    filas_ga_raw = con.execute("SELECT count(*) FROM ga_eventos").fetchone()[0]
    filas_ga_limpio = con.execute("SELECT count(*) FROM ga_eventos_limpios").fetchone()[0]
    m["ga_eventos_filas_raw"] = filas_ga_raw
    m["ga_eventos_filas_limpio"] = filas_ga_limpio
    m["ga_eventos_duplicados_excluidos"] = filas_ga_raw - filas_ga_limpio

    m["event_date_no_parseable_antes"] = con.execute(
        "SELECT count(*) FROM ga_eventos WHERE try_cast(event_date AS TIMESTAMP) IS NULL"
    ).fetchone()[0]
    m["event_date_no_parseable_despues"] = con.execute(
        "SELECT count(*) FROM ga_eventos_limpios WHERE event_ts IS NULL"
    ).fetchone()[0]

    m["device_filas_normalizadas"] = con.execute(
        """
        SELECT count(*) FROM ga_eventos
        WHERE device != CASE lower(device) WHEN 'desktp' THEN 'desktop' ELSE lower(device) END
        """
    ).fetchone()[0]

    m["reserva_id_huerfano_eventos"] = con.execute(
        "SELECT count(*) FROM ga_eventos_limpios WHERE reserva_id_huerfano"
    ).fetchone()[0]

    # --- identidad ------------------------------------------------------
    m["conflictos_identidad"] = identity.contar_conflictos_identidad(con)
    m["eventos_identificados"] = con.execute(
        "SELECT count(*) FROM eventos_con_cliente WHERE es_visitante_identificado"
    ).fetchone()[0]

    # --- reservas: base de ingresos --------------------------------------
    total_reservas = con.execute("SELECT count(*), sum(importe_eur) FROM reservas_limpias").fetchone()
    m["reservas_filas"] = total_reservas[0]
    m["importe_total_eur"] = round(total_reservas[1], 2)

    # --- reservas: estado ------------------------------------------------
    m["estado_filas_normalizadas"] = con.execute(
        """
        SELECT count(*) FROM reservas
        WHERE estado != CASE lower(estado) WHEN 'cancelled' THEN 'cancelada' ELSE lower(estado) END
        """
    ).fetchone()[0]

    # --- reservas: personas invalida (impacto si se excluyera) ----------
    n_personas, importe_personas = con.execute(
        "SELECT count(*), coalesce(sum(importe_eur), 0) FROM reservas_limpias WHERE personas_invalida"
    ).fetchone()
    m["personas_invalida_filas"] = n_personas
    m["personas_invalida_importe_eur"] = round(importe_personas, 2)
    m["personas_invalida_pct_filas"] = round(100 * n_personas / m["reservas_filas"], 2)
    m["personas_invalida_pct_importe"] = round(100 * importe_personas / m["importe_total_eur"], 2)

    # --- reservas: proveedor huerfano (impacto si se excluyera) ----------
    n_prov, importe_prov = con.execute(
        "SELECT count(*), coalesce(sum(importe_eur), 0) FROM reservas_limpias WHERE proveedor_huerfano"
    ).fetchone()
    m["proveedor_huerfano_reservas_filas"] = n_prov
    m["proveedor_huerfano_reservas_importe_eur"] = round(importe_prov, 2)
    m["proveedor_huerfano_reservas_pct_filas"] = round(100 * n_prov / m["reservas_filas"], 2)
    m["proveedor_huerfano_reservas_pct_importe"] = round(100 * importe_prov / m["importe_total_eur"], 2)
    m["proveedor_huerfano_tours_filas"] = con.execute(
        "SELECT count(*) FROM tours_limpios WHERE proveedor_huerfano"
    ).fetchone()[0]

    # --- reservas: importe_eur = 0, verificación de legitimidad ----------
    n_importe_cero = con.execute("SELECT count(*) FROM reservas_limpias WHERE importe_eur = 0").fetchone()[0]
    n_importe_cero_tour_gratis = con.execute(
        """
        SELECT count(*) FROM reservas_limpias r
        JOIN tours_limpios t ON r.tour_id = t.tour_id
        WHERE r.importe_eur = 0 AND t.precio_por_persona_eur = 0
        """
    ).fetchone()[0]
    m["importe_cero_filas"] = n_importe_cero
    m["importe_cero_explicadas_por_tour_gratis"] = n_importe_cero_tour_gratis
    m["importe_cero_sin_explicar"] = n_importe_cero - n_importe_cero_tour_gratis

    # --- reservas: outliers de importe_eur (mismo método IQR que notebook 01) --
    q1, q3 = con.execute(
        """
        SELECT
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY importe_eur),
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY importe_eur)
        FROM reservas_limpias
        """
    ).fetchone()
    iqr = q3 - q1
    limite_sup = q3 + 1.5 * iqr
    n_outliers, importe_outliers = con.execute(
        f"SELECT count(*), coalesce(sum(importe_eur), 0) FROM reservas_limpias WHERE importe_eur > {limite_sup}"
    ).fetchone()
    m["importe_outlier_limite_sup"] = round(limite_sup, 2)
    m["importe_outlier_filas"] = n_outliers
    m["importe_outlier_importe_eur"] = round(importe_outliers, 2)
    m["importe_outlier_pct_importe"] = round(100 * importe_outliers / m["importe_total_eur"], 2)

    # --- clientes ---------------------------------------------------------
    m["clientes_filas"] = con.execute("SELECT count(*) FROM clientes_limpios").fetchone()[0]
    m["fecha_alta_corregida_filas"] = con.execute(
        "SELECT count(*) FROM clientes_limpios WHERE fecha_alta_corregida"
    ).fetchone()[0]
    m["fecha_baja_corregida_filas"] = con.execute(
        "SELECT count(*) FROM clientes_limpios WHERE fecha_baja_corregida"
    ).fetchone()[0]

    n_grupos_dni, n_filas_dni = con.execute(
        """
        SELECT count(*), coalesce(sum(n), 0) FROM (
            SELECT dni, count(*) AS n FROM clientes GROUP BY dni HAVING count(*) > 1
        )
        """
    ).fetchone()
    m["dni_duplicado_grupos"] = n_grupos_dni
    m["dni_duplicado_filas"] = n_filas_dni

    return m


# ---------------------------------------------------------------------------
# Informe de calidad (markdown)
# ---------------------------------------------------------------------------

def generar_informe_calidad(m: dict) -> str:
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    conflictos = m["conflictos_identidad"]

    return f"""# Informe de calidad de datos — Civitatis

_Generado automáticamente por `python -m src.cleaning` a partir de los CSV en `/data/raw`. Fecha: {fecha}._

Criterio aplicado: **excluir** solo duplicados exactos que no aportan
información nueva; **imputar** cuando el valor correcto es inequívoco
(typo conocido, formato de fecha mixto, categoría con distinta grafía);
**flag** (marcar sin tocar la fila) cuando el dato es dudoso pero el resto de
la fila sigue siendo información de negocio válida. El detalle y el porqué de
cada decisión está también como comentario SQL en `src/cleaning.py` e
`src/identity.py`.

## 1. `ga_eventos` → `ga_eventos_limpios`

| Comprobación | Filas originales | Afectadas | % | Tratamiento |
|---|---:|---:|---:|---|
| Duplicados exactos | {m['ga_eventos_filas_raw']:,} | {m['ga_eventos_duplicados_excluidos']:,} | {100 * m['ga_eventos_duplicados_excluidos'] / m['ga_eventos_filas_raw']:.2f}% | Excluidas |
| `event_date` no parseable (formato ISO únicamente) | {m['ga_eventos_filas_raw']:,} | {m['event_date_no_parseable_antes']:,} | {100 * m['event_date_no_parseable_antes'] / m['ga_eventos_filas_raw']:.2f}% | Imputado combinando 2 parsers de fecha |
| `device` con mayúsculas/typo inconsistentes | {m['ga_eventos_filas_raw']:,} | {m['device_filas_normalizadas']:,} | {100 * m['device_filas_normalizadas'] / m['ga_eventos_filas_raw']:.2f}% | Imputado (normalizado a minúsculas + typo corregido) |
| `reserva_id` huérfano (compra sin reserva persistida) | {m['ga_eventos_filas_raw']:,} | {m['reserva_id_huerfano_eventos']:,} | {100 * m['reserva_id_huerfano_eventos'] / m['ga_eventos_filas_raw']:.4f}% | Flag `reserva_id_huerfano` (no se excluye) |

Tras la limpieza, `event_date` queda parseado al 100%: {m['event_date_no_parseable_despues']} filas
sin `event_ts` (combinando `try_strptime` en formato ISO y europeo, entre los
dos cubren todas las filas).

`ga_eventos_limpios` pasa de {m['ga_eventos_filas_raw']:,} a {m['ga_eventos_filas_limpio']:,} filas
(solo por los duplicados excluidos; ningún otro tratamiento cambia el número
de filas).

## 2. Unificación de identidad — `eventos_con_cliente`

Regla de precedencia `user_id > cookie_id > temp_client_id` (razonamiento
completo en `src/identity.py`). Verificación de conflictos sobre los datos
reales:

- `cookie_id` ligados a más de un `user_id` distinto: **{conflictos['cookie_id_con_varios_user_id']}**
- `temp_client_id` ligados a más de un `user_id` distinto: **{conflictos['temp_client_id_con_varios_user_id']}**

0 conflictos en ambos casos: ningún identificador anónimo se comparte entre
dos cuentas autenticadas distintas, así que la regla de precedencia fila a
fila no está enmascarando ningún caso de identidad cruzada.

De {m['ga_eventos_filas_limpio']:,} eventos, {m['eventos_identificados']:,}
({100 * m['eventos_identificados'] / m['ga_eventos_filas_limpio']:.2f}%) quedan resueltos por
`user_id` (visitante autenticado); el resto se resuelve por `cookie_id`
(visitante anónimo).

## 3. `reservas` → `reservas_limpias`

Base de ingresos: **{m['importe_total_eur']:,.2f} €** en {m['reservas_filas']:,} reservas.
Ninguna reserva se excluye de esta tabla — las inconsistencias se marcan con
un flag para que cada análisis decida si las incluye.

| Comprobación | Filas afectadas | % filas | Importe afectado | % del importe total | Tratamiento |
|---|---:|---:|---:|---:|---|
| `estado` con grafía inconsistente | {m['estado_filas_normalizadas']:,} | {100 * m['estado_filas_normalizadas'] / m['reservas_filas']:.2f}% | — | — | Imputado (normalizado a confirmada/cancelada/pendiente) |
| `personas` ≤ 0 | {m['personas_invalida_filas']} | {m['personas_invalida_pct_filas']}% | {m['personas_invalida_importe_eur']:,.2f} € | {m['personas_invalida_pct_importe']}% | Flag `personas_invalida` |
| `proveedor_id` inexistente | {m['proveedor_huerfano_reservas_filas']} | {m['proveedor_huerfano_reservas_pct_filas']}% | {m['proveedor_huerfano_reservas_importe_eur']:,.2f} € | {m['proveedor_huerfano_reservas_pct_importe']}% | Flag `proveedor_huerfano` |
| `importe_eur` = 0 | {m['importe_cero_filas']:,} | {100 * m['importe_cero_filas'] / m['reservas_filas']:.2f}% | 0.00 € | 0.00% | Sin tratamiento (verificado como legítimo, ver abajo) |
| `importe_eur` outlier (> {m['importe_outlier_limite_sup']:,.2f} €, IQR) | {m['importe_outlier_filas']} | {100 * m['importe_outlier_filas'] / m['reservas_filas']:.2f}% | {m['importe_outlier_importe_eur']:,.2f} € | {m['importe_outlier_pct_importe']}% | Sin tratamiento (legítimo, ver notebook 01) |

**Impacto si se excluyeran en vez de flagear** (es decir, filtrando
`WHERE NOT personas_invalida` / `WHERE NOT proveedor_huerfano` en un análisis
concreto): excluir las {m['personas_invalida_filas']} reservas con `personas`
inválida bajaría el importe total en {m['personas_invalida_importe_eur']:,.2f} €
({m['personas_invalida_pct_importe']}%); excluir las
{m['proveedor_huerfano_reservas_filas']} reservas con `proveedor_id` inexistente
lo bajaría en {m['proveedor_huerfano_reservas_importe_eur']:,.2f} €
({m['proveedor_huerfano_reservas_pct_importe']}%). Por eso se ha optado por
flagear y no excluir: son análisis (ticket medio por persona, ranking de
proveedores) los que deben decidir si filtran, no la tabla limpia de base.

**`importe_eur` = 0 — verificación de legitimidad**: de las {m['importe_cero_filas']:,}
reservas con importe 0€, {m['importe_cero_explicadas_por_tour_gratis']:,} corresponden a
un tour cuyo `precio_por_persona_eur` también es 0 en el catálogo
({m['importe_cero_sin_explicar']} sin explicar por esta vía). Son tours
gratuitos reales, no reservas sin cobrar — no se aplica ningún tratamiento.

## 4. `clientes` → `clientes_limpios`

{m['clientes_filas']:,} clientes en total, ninguno excluido.

| Comprobación | Filas afectadas | % | Tratamiento |
|---|---:|---:|---|
| `fecha_alta` en el futuro | {m['fecha_alta_corregida_filas']} | {100 * m['fecha_alta_corregida_filas'] / m['clientes_filas']:.3f}% | Imputado a NULL + flag `fecha_alta_corregida` |
| `fecha_baja` en el futuro | {m['fecha_baja_corregida_filas']} | {100 * m['fecha_baja_corregida_filas'] / m['clientes_filas']:.2f}% | Imputado a NULL + flag `fecha_baja_corregida` |
| `dni` duplicado (mismo DNI y nombre, distinto `user_id`/email) | {m['dni_duplicado_filas']} filas ({m['dni_duplicado_grupos']} pares) | {100 * m['dni_duplicado_filas'] / m['clientes_filas']:.2f}% | Flag `dni_duplicado` (no se fusiona) |

Ni `fecha_alta` ni `fecha_baja` se pueden ocurrir en el futuro por
definición de negocio, así que no hay una fecha "correcta" que imputar más
allá de NULL: inventar una fecha pasada plausible fabricaría un dato que no
existe. Los `dni` duplicados no se fusionan porque ambos `user_id` tienen
historial real en `reservas`/`ga_eventos`; fusionarlos exigiría decidir a
qué cuenta atribuir cada reserva, una decisión de negocio fuera del alcance
de la limpieza de datos.

## 5. `tours` → `tours_limpios`

| Comprobación | Filas afectadas | Tratamiento |
|---|---:|---|
| `proveedor_id` inexistente | {m['proveedor_huerfano_tours_filas']} | Flag `proveedor_huerfano` |

## `proveedores`

Sin inconsistencias detectadas en el perfilado inicial (0 duplicados, 0
nulos relevantes) — se persiste sin cambios.
"""


# ---------------------------------------------------------------------------
# Construcción de /data/processed/civitatis.duckdb
# ---------------------------------------------------------------------------

def construir_base_procesada() -> dict:
    """Genera `/data/processed/civitatis.duckdb` con las 5 tablas originales
    y las tablas limpias (`ga_eventos_limpios`, `clientes_limpios`,
    `reservas_limpias`, `tours_limpios`, `eventos_con_cliente`) ya
    materializadas, para que los notebooks posteriores solo tengan que abrir
    ese fichero (`src.db.connect_processed()`) en vez de repetir la limpieza.

    Devuelve el diccionario de métricas de `calcular_metricas_calidad`, para
    poder generar el informe de calidad con los mismos números.
    """
    db.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    nombres_finales = list(db.RAW_TABLES.keys()) + [
        "clientes_limpios",
        "ga_eventos_limpios",
        "reservas_limpias",
        "tours_limpios",
        "eventos_con_cliente",
    ]

    con = duckdb.connect(str(db.PROCESSED_DB_PATH))
    try:
        # Rebuild idempotente: si el fichero ya existía de una ejecución
        # anterior, estos nombres pueden estar como TABLE en vez de VIEW, lo
        # que rompería el `CREATE OR REPLACE VIEW` de registrar_vistas_raw.
        for nombre in nombres_finales:
            try:
                con.execute(f"DROP VIEW IF EXISTS {nombre}")
            except duckdb.CatalogException:
                pass
            try:
                con.execute(f"DROP TABLE IF EXISTS {nombre}")
            except duckdb.CatalogException:
                pass

        db.registrar_vistas_raw(con)
        crear_vistas_limpias(con, materialize=False)

        metricas = calcular_metricas_calidad(con)

        # Materializa todo (raw + limpio) como tablas físicas, en orden de
        # dependencia, para que el .duckdb resultante sea autocontenido y no
        # necesite volver a leer /data/raw.
        for nombre in nombres_finales:
            con.execute(f"CREATE OR REPLACE TABLE {nombre}__tbl AS SELECT * FROM {nombre}")
            con.execute(f"DROP VIEW {nombre}")
            con.execute(f"ALTER TABLE {nombre}__tbl RENAME TO {nombre}")
    finally:
        con.close()

    return metricas


def main() -> None:
    metricas = construir_base_procesada()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(generar_informe_calidad(metricas), encoding="utf-8")

    print(f"Base procesada generada en {db.PROCESSED_DB_PATH}")
    print(f"Informe de calidad generado en {REPORT_PATH}")


if __name__ == "__main__":
    main()
