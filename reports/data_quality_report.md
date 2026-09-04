# Informe de calidad de datos — Civitatis

_Generado automáticamente por `python -m src.limpieza`. Fecha: 2026-09-04 12:03._

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

- **Reservas con importe 0€**: había **1,295 reservas**
  con `importe_eur = 0€`, y quedaba por confirmar si eran tours realmente
  gratuitos o cancelaciones/errores sin cobro. Cruzando cada una con el
  precio de catálogo de su tour (`tours.precio_por_persona_eur`):
  **1,295 de
  1,295 (100.00%)**
  corresponden a un tour cuyo precio de catálogo también es 0€ — son tours
  gratuitos legítimos — y **0**
  corresponden a un tour de pago cobrado a 0€ (caso sospechoso de error).

  Desglose por estado de las 1,295 reservas
  con importe 0€: 1,076 confirmada, 175 cancelada, 44 pendiente.
  No se han excluido de `venta_bruta`/`venta_neta` ni de ningún conteo:
  al sumar 0€, no alteran ninguna cifra, y se ha añadido la columna
  `tour_gratuito` a `reservas_limpias` para dejar constancia explícita de
  que se investigó y documentar qué reservas son gratuitas por diseño.

**Resultado**: las reservas pasan de 8,414 a
8,384 filas, y el importe total pasa de
763,852.29 € a 760,568.30 €
(una bajada de 3,283.99 €,
un 0.43% del total).


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

No se ha encontrado ningún problema que corregir en esta tabla (según lo
visto en el análisis exploratorio). Se copia tal cual, solo con el nombre
`clientes_limpios` para seguir el mismo criterio que el resto de tablas.
Sigue teniendo **8,060 clientes**.


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
