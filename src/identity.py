"""Unificación de identidad de visitantes en `ga_eventos`.

`ga_eventos` trae tres identificadores por fila: `cookie_id`, `temp_client_id`
y `user_id`. Este módulo construye la vista `eventos_con_cliente`, que resuelve
esos tres ids en un único `cliente_id_resuelto` por evento.

## Regla de precedencia: user_id > cookie_id > temp_client_id

1. `user_id` (visitante autenticado). Es el único de los tres validado al 100%
   contra `clientes` (todo `user_id` de `ga_eventos` existe en `clientes`,
   ver notebook 01 sección 2) y nunca aparece repetido con distinto
   `cookie_id`/`temp_client_id` en la misma fila. Cuando está presente en la
   fila, manda siempre.
2. `cookie_id` (identificador anónimo persistente). Nunca es nulo, y es el
   identificador que el resto del análisis exploratorio ya usa como proxy de
   "visitante" (250.063 `cookie_id` distintos vs. 272.530 `session_id`, ver
   notebook 01 sección 2). Se usa como primer fallback para no romper esa
   convención y porque agrupa el comportamiento anónimo a nivel de
   navegador/dispositivo.
3. `temp_client_id` (identificador anónimo más granular/efímero). Un mismo
   `cookie_id` se reparte, en los datos, entre una media de varios
   `temp_client_id` distintos (6.745 `cookie_id` con más de un
   `temp_client_id` asociado) — es decir, cambia con más frecuencia que
   `cookie_id` (limpiezas de caché, nuevas pestañas/sesiones, etc.). Se deja
   como último recurso, solo por robustez ante un futuro `cookie_id` nulo.

## Qué pasa en conflicto

La resolución se hace **fila a fila**, nunca propagando un `user_id`
"principal" desde otras filas que compartan `cookie_id`/`temp_client_id`. Esto
importa por el caso de un dispositivo compartido por varias personas: si dos
usuarios distintos usan el mismo navegador (mismo `cookie_id`) en momentos
distintos, cada evento conserva su propio `user_id` de fila cuando existe, y
solo se recurre a `cookie_id`/`temp_client_id` para los eventos anónimos de
ese mismo navegador — sin arriesgarse a atribuir una compra autenticada de una
persona a la identidad de otra.

En los datos actuales no hay conflicto real de este tipo: ningún `cookie_id`
ni `temp_client_id` aparece ligado a más de un `user_id` no nulo distinto
(comprobado en `contar_conflictos_identidad`, incluido en el informe de
calidad). Si en el futuro apareciera, la regla fila a fila de arriba ya lo
maneja de forma segura sin necesitar tratamiento adicional.
"""

# Solo el SELECT: src.cleaning decide si esto se crea como VIEW o como TABLE.
# Depende de `ga_eventos_limpios` y `clientes_limpios` (deben existir ya en la
# conexión antes de ejecutar este SQL).
SQL_EVENTOS_CON_CLIENTE = """
SELECT
    e.*,

    -- cliente_id_resuelto: ver docstring del módulo para la justificación de
    -- la precedencia user_id > cookie_id > temp_client_id.
    COALESCE(CAST(e.user_id AS VARCHAR), e.cookie_id, e.temp_client_id) AS cliente_id_resuelto,

    CASE
        WHEN e.user_id IS NOT NULL THEN 'user_id'
        WHEN e.cookie_id IS NOT NULL THEN 'cookie_id'
        ELSE 'temp_client_id'
    END AS fuente_identidad,

    (e.user_id IS NOT NULL) AS es_visitante_identificado,

    -- Datos del cliente ya identificado, para no tener que volver a hacer
    -- este JOIN en cada notebook. NULL en todas estas columnas = visitante
    -- anónimo (no es un error, es la mayoría del tráfico).
    c.fecha_alta AS cliente_fecha_alta,
    c.fecha_baja AS cliente_fecha_baja,
    c.dni_duplicado AS cliente_dni_duplicado

FROM ga_eventos_limpios e
LEFT JOIN clientes_limpios c ON e.user_id = c.user_id
"""


def crear_vista_identidad(con, materialize: bool = False) -> None:
    """Crea `eventos_con_cliente` sobre la conexión dada.

    Requiere que `ga_eventos_limpios` y `clientes_limpios` ya existan en `con`
    (ver `src.cleaning.crear_vistas_limpias`).
    """
    kind = "TABLE" if materialize else "VIEW"
    con.execute(f"CREATE OR REPLACE {kind} eventos_con_cliente AS {SQL_EVENTOS_CON_CLIENTE}")


def contar_conflictos_identidad(con) -> dict:
    """Cuenta cuántos `cookie_id`/`temp_client_id` aparecen ligados a más de un
    `user_id` no nulo distinto en `ga_eventos_limpios`.

    Sirve para verificar con datos reales que resolver la identidad fila a
    fila (en vez de propagar un `user_id` "canónico" por cookie/sesión) no
    está enmascarando un problema de varias personas compartiendo un mismo
    identificador anónimo.
    """
    cookie, temp_client = con.execute(
        """
        SELECT
            (SELECT count(*) FROM (
                SELECT cookie_id FROM ga_eventos_limpios
                WHERE user_id IS NOT NULL
                GROUP BY cookie_id HAVING count(DISTINCT user_id) > 1
            )) AS cookie_id_con_varios_user_id,
            (SELECT count(*) FROM (
                SELECT temp_client_id FROM ga_eventos_limpios
                WHERE user_id IS NOT NULL
                GROUP BY temp_client_id HAVING count(DISTINCT user_id) > 1
            )) AS temp_client_id_con_varios_user_id
        """
    ).fetchone()
    return {
        "cookie_id_con_varios_user_id": cookie,
        "temp_client_id_con_varios_user_id": temp_client,
    }
