# Informe de calidad de datos — Civitatis

_Generado automáticamente por `python -m src.cleaning` a partir de los CSV en `/data/raw`._

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
| Duplicados exactos | 702,821 | 798 | 0.11% | Excluidas |
| `event_date` no parseable (formato ISO únicamente) | 702,821 | 32,589 | 4.64% | Imputado combinando 2 parsers de fecha |
| `device` con mayúsculas/typo inconsistentes | 702,821 | 70,328 | 10.01% | Imputado (normalizado a minúsculas + typo corregido) |
| `reserva_id` huérfano (compra sin reserva persistida) | 702,821 | 40 | 0.0057% | Flag `reserva_id_huerfano` (no se excluye) |

Tras la limpieza, `event_date` queda parseado al 100%: 0 filas
sin `event_ts` (combinando `try_strptime` en formato ISO y europeo, entre los
dos cubren todas las filas).

`ga_eventos_limpios` pasa de 702,821 a 702,023 filas
(solo por los duplicados excluidos; ningún otro tratamiento cambia el número
de filas).

## 2. Unificación de identidad — `eventos_con_cliente`

Regla de precedencia `user_id > cookie_id > temp_client_id` (razonamiento
completo en `src/identity.py`). Verificación de conflictos sobre los datos
reales:

- `cookie_id` ligados a más de un `user_id` distinto: **0**
- `temp_client_id` ligados a más de un `user_id` distinto: **0**

0 conflictos en ambos casos: ningún identificador anónimo se comparte entre
dos cuentas autenticadas distintas, así que la regla de precedencia fila a
fila no está enmascarando ningún caso de identidad cruzada.

De 702,023 eventos, 72,202
(10.28%) quedan resueltos por
`user_id` (visitante autenticado); el resto se resuelve por `cookie_id`
(visitante anónimo).

## 3. `reservas` → `reservas_limpias`

Base de ingresos: **763,852.29 €** en 8,414 reservas.
Ninguna reserva se excluye de esta tabla — las inconsistencias se marcan con
un flag para que cada análisis decida si las incluye.

| Comprobación | Filas afectadas | % filas | Importe afectado | % del importe total | Tratamiento |
|---|---:|---:|---:|---:|---|
| `estado` con grafía inconsistente | 5,624 | 66.84% | — | — | Imputado (normalizado a confirmada/cancelada/pendiente) |
| `personas` ≤ 0 | 30 | 0.36% | 3,283.99 € | 0.43% | Flag `personas_invalida` |
| `proveedor_id` inexistente | 187 | 2.22% | 29,026.37 € | 3.8% | Flag `proveedor_huerfano` |
| `importe_eur` = 0 | 1,297 | 15.41% | 0.00 € | 0.00% | Sin tratamiento (verificado como legítimo, ver abajo) |
| `importe_eur` outlier (> 283.22 €, IQR) | 237 | 2.82% | 81,665.46 € | 10.69% | Sin tratamiento (legítimo, ver notebook 01) |

**Impacto si se excluyeran en vez de flagear** (es decir, filtrando
`WHERE NOT personas_invalida` / `WHERE NOT proveedor_huerfano` en un análisis
concreto): excluir las 30 reservas con `personas`
inválida bajaría el importe total en 3,283.99 €
(0.43%); excluir las
187 reservas con `proveedor_id` inexistente
lo bajaría en 29,026.37 €
(3.8%). Por eso se ha optado por
flagear y no excluir: son análisis (ticket medio por persona, ranking de
proveedores) los que deben decidir si filtran, no la tabla limpia de base.

**`importe_eur` = 0 — verificación de legitimidad**: de las 1,297
reservas con importe 0€, 1,297 corresponden a
un tour cuyo `precio_por_persona_eur` también es 0 en el catálogo
(0 sin explicar por esta vía). Son tours
gratuitos reales, no reservas sin cobrar — no se aplica ningún tratamiento.

## 4. `clientes` → `clientes_limpios`

8,060 clientes en total, ninguno excluido.

| Comprobación | Filas afectadas | % | Tratamiento |
|---|---:|---:|---|
| `fecha_alta` en el futuro | 1 | 0.012% | Imputado a NULL + flag `fecha_alta_corregida` |
| `fecha_baja` en el futuro | 40 | 0.50% | Imputado a NULL + flag `fecha_baja_corregida` |
| `dni` duplicado (mismo DNI y nombre, distinto `user_id`/email) | 118 filas (59 pares) | 1.46% | Flag `dni_duplicado` (no se fusiona) |

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
| `proveedor_id` inexistente | 1 | Flag `proveedor_huerfano` |

## `proveedores`

Sin inconsistencias detectadas en el perfilado inicial (0 duplicados, 0
nulos relevantes) — se persiste sin cambios.
