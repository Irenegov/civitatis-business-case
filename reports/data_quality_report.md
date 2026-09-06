# Informe de calidad de datos — Civitatis

_Generado automáticamente por `python -m src.limpieza`. Fecha: 2026-09-06 21:07._

Este informe explica qué se ha limpiado en cada tabla
y cuánto cambian los números por ello.

## 1. Reservas (`reservas` → `reservas_limpias`)

- **Estados escritos de formas distintas**: `estado` venía con mayúsculas y
  hasta un valor en inglés (`CONFIRMADA`, `Confirmada`, `confirmada`,
  `CANCELLED`, `Cancelada`, `cancelada`...) para referirse a solo 3
  situaciones reales. Se ha dejado todo en minúsculas y en español
  (`confirmada` / `cancelada` / `pendiente`). Esto afectó a
  **5,624 reservas** — no cambia ningún
  importe, solo cómo se escribe el estado.

- **Reservas con 0 o menos personas**: no tiene sentido reservar un tour para
  "0" o "-1" personas, así que se han eliminado directamente. Eran
  **30 reservas**, que sumaban
  **3,283.99 €**.

- **Reservas con importe 0€ (decisión pendiente del análisis exploratorio,
  ahora resuelta)**: había **1,291 reservas**
  con `importe_eur = 0€`, y quedaba por confirmar si eran tours realmente
  gratuitos o cancelaciones/errores sin cobro. Cruzando cada una con el
  precio de catálogo de su tour (`tours.precio_por_persona_eur`):
  **1,291 de
  1,291 (100.00%)**
  corresponden a un tour cuyo precio de catálogo también es 0€ — son tours
  gratuitos legítimos — y **0**
  corresponden a un tour de pago cobrado a 0€ (caso sospechoso de error).
  Desglose por estado de las 1,291 reservas
  con importe 0€: 1,072 confirmada, 175 cancelada, 44 pendiente.
  No se han excluido de `venta_bruta`/`venta_neta` ni de ningún conteo:
  al sumar 0€, no alteran ninguna cifra, y se ha añadido la columna
  `tour_gratuito` a `reservas_limpias` para dejar constancia explícita de
  que se investigó y documentar qué reservas son gratuitas por diseño.

- **Reservas de clientes con `fecha_alta`/`fecha_baja` futura (decisión
  pendiente del análisis exploratorio, ahora resuelta; ver detalle en la
  sección 3, "Clientes")**: se han eliminado también las
  **40 reservas** (
  4,397.02 €) de esos clientes —
  de ellas, 1 ya
  estaba contada en el filtro de "personas <= 0" anterior, así que no se
  resta dos veces del total.

**Resultado**: las reservas pasan de 8,414 a
8,345 filas, y el importe total pasa de
763,852.29 € a 756,248.12 €
(una bajada de 7,604.17 €,
un 1.00% del total).


## 2. Eventos web (`ga_eventos` → `eventos_limpios`)

- **Eventos duplicados**: había eventos guardados dos veces de forma
  idéntica. Se han eliminado **798 filas**
  duplicadas.

- **Dispositivo escrito de formas distintas**: `device` venía como
  `Mobile`/`mobile`, `Desktop`/`desktop`, `tablet`, y con un error de
  escritura (`desktp`). Se ha dejado todo en minúsculas y corregido el error,
  afectando a **70,328 filas**.

**Resultado**: los eventos pasan de 702,821 a
702,023 filas.


## 3. Clientes (`clientes` → `clientes_limpios`)

- **Clientes con `fecha_alta` o `fecha_baja` en el futuro (decisión pendiente
  del análisis exploratorio, ahora resuelta)**: el notebook de exploración
  (`notebooks/01_exploracion_inicial.ipynb`) detectó 39 clientes con
  `fecha_baja` posterior a hoy y 1 con `fecha_alta` posterior a hoy
  (**40 en total**). Antes de
  tratarlos como error, se investigó si esas fechas respondían a una decisión
  del cliente ligada a su actividad reservada — p. ej. programar la baja para
  justo después de disfrutar su último tour, o el alta coincidiendo con su
  primera reserva. Esa hipótesis **no se confirmó con los datos**: ninguno de
  los 39 casos de `fecha_baja` coincide, ni exacto ni con un margen de días,
  con la `fecha_actividad` de su última reserva (la diferencia mínima
  observada es de 182 días), y el único cliente con `fecha_alta` futura no
  tiene ninguna reserva asociada. Sin esa explicación operativa, se tratan
  como error de captura: se excluyen de `clientes_limpios` y de sus
  `reservas_limpias` asociadas (ver sección 1).

**Resultado**: los clientes pasan de 8,060 a
8,020 filas (40
excluidos).


## 4. Identificar al visitante detrás de cada evento (`paso1` → `paso2` → `eventos_con_id`)

Cada evento de `eventos_limpios` trae tres posibles identificadores del
visitante (`user_id`, `cookie_id`, `temp_client_id`), y no siempre vienen
todos rellenos. Se resuelve en 3 pasos, cada uno en su propia consulta para
poder revisarlo por separado (`paso1` y `paso2` son VIEW, no TABLE: solo
`eventos_con_id`, el resultado final, se guarda como tabla):

1. **`paso1`** — usa `user_id` cuando el visitante ha iniciado sesión. Así se
   identifican **72,202** de 702,023
   eventos (10.28%).

2. **`paso2`** — para los eventos que siguen sin id, usa `cookie_id` (el
   identificador anónimo del navegador). Con esto se identifican
   **629,821 eventos** más, llegando a
   **702,023** en total
   (100.00%).

3. **`eventos_con_id`** — para los que aún faltan, usa `temp_client_id` como
   último recurso. Esto resuelve **0
   eventos** adicionales.


**Resultado final**: de 702,023 eventos,
**702,023** quedan con un id de visitante asignado
(100.00%), y
**0** se quedan sin ninguno de los tres
identificadores.
