# Civitatis — Business Case Data Analyst

Análisis del comportamiento de clientes de Civitatis con el objetivo de responder a tres preguntas de negocio con hipótesis explícitas y conclusiones accionables:

1. **Repetición** — ¿qué factores explican que un cliente repita o no? (canal, campaña, destino, dispositivo...)
2. **Destinos** — ¿qué localizaciones tienen mayor acogida y cuáles retienen mejor a los clientes?
3. **Estado del negocio** — ¿cuánto se ha vendido realmente, y qué cuenta como "venta"?

Además, se cubren otras preguntas de apoyo: proporción de clientes conocidos vs. desconocidos, frecuencia e intervalo entre reservas, tasa e impacto de las cancelaciones, influencia de canales y campañas, y efecto del dispositivo en la probabilidad de compra.

Todo el pipeline (limpieza, resolución de identidad de cliente, métricas y análisis) está construido sobre DuckDB, y el resultado se explora tanto en notebooks como en una app interactiva de Streamlit.

## Cómo ejecutar la app

1. Clona el repositorio
2. Crea un entorno virtual e instala dependencias:
```bash
   python -m venv venv
   venv\Scripts\activate (en Windows)
   pip install -r requirements.txt
```
3. Ejecuta la app:
```bash
   streamlit run app/main.py
```

No hace falta ningún paso previo con los CSV: `/data/processed/civitatis.duckdb`
(la base ya limpia y con las métricas calculadas) viene incluida en el repo,
y es lo único que usan tanto la app como los notebooks 02 y 03.

**Solo si quieres regenerar esa base desde cero** (por ejemplo, usando
`src/limpieza.py` o `src/metricas.py`) necesitas los CSV originales de
Civitatis, que sí hay que colocar a mano en `/data/raw` porque no se
incluyen en el repo (por tamaño y por política del ejercicio). Con ellos
en su sitio:
```bash
   python -m src.limpieza
   python -m src.metricas
```

**Enlace a la app (solo es necesario hacer click, sin comandos):** https://civitatis-business-case-irenegov.streamlit.app/

## Estructura del repositorio
civitatis-business-case/
├── app/
│   └── main.py                        # App Streamlit: 3 pestañas (Estado del
│                                       # negocio, Destinos, Repetición)
├── data/
│   ├── raw/                           # CSV originales de Civitatis
│   │                                   # (colocar a mano solo si se va a regenerar la base)
│   └── processed/
│       └── civitatis.duckdb           # Base ya limpia + métricas calculadas
│                                       
├── notebooks/
│   ├── 01_exploracion_inicial.ipynb   # Perfilado de calidad de los CSV originales:
│   │                                   
│   ├── 02_negocio_y_destinos.ipynb    # Estado del negocio y ranking de
│   │                                   # destinos por venta y por retención
│   │
│   └── 03_repeticion.ipynb            # Factores que afectan a la repetición de compra
│                                       
├── src/
│   ├── conexion.py                    # Conexión DuckDB 
│   │                                   
│   ├── limpieza.py                    # Limpieza de datos e identificación de clientes 
│   │                                   
│   ├── metricas.py                    # Define y calcula venta, cliente
│   │                                   # recurrente y conversión 
│   │                                   
│   └── queries.py                     # Consultas reutilizadas por la app
│                                       
├── reports/
│   └── data_quality_report.md         # Informe cuantificado del impacto de
│                                       # cada decisión de limpieza
├── requirements.txt
├── .gitignore
└── README.md

## Decisiones y uso de IA

### Supuestos adoptados

- **Identidad de cliente**: en `ga_eventos`, un mismo visitante puede tener hasta 3 identificadores (`cookie_id`, `temp_client_id`, `user_id`). Se resuelven en cascada por fiabilidad decreciente: `user_id` (visitante autenticado, verificado al 100% contra `clientes`) → `cookie_id` (casi nunca nulo) → `temp_client_id` (más volátil, cambia con más frecuencia). 
Se verificó que ningún `cookie_id`/`temp_client_id` está ligado a más de un `user_id` distinto, así que la regla es segura sin necesitar tratamiento adicional para dispositivos compartidos.

- **Periodo pre-operativo (abril 2023 – junio 2024)**: solo hubo 11 reservas sueltas en 14 meses, con `fecha_actividad` mínima el 4 de julio de 2024 (ninguna actividad realizada antes de esa fecha). Se investigó con 4 señales independientes (importe medio estable, altas de cliente sin salto, catálogo ya completo, ausencia total de `fecha_actividad` previa) para descartar que fuera un artefacto de datos. Se trata como fase pre-operativa: no se eliminan esas reservas, pero las conclusiones sobre tendencia de venta se apoyan en el periodo **desde** julio 2024.

- **Reservas con `importe_eur = 0`**: se cruzaron las 1.297 reservas con 
  `importe_eur = 0€` contra el `precio_por_persona_eur` de su tour en el 
  catálogo. El 100% corresponde a tours cuyo precio de catálogo también 
  es 0€ por lo que se trataron como tours gratuitos legítimos, no cancelaciones sin cobro ni 
  errores de captura. 
  No se altera `venta_bruta` ni `venta_neta`, y se 
  documenta con la columna `tour_gratuito` en `reservas_limpias`.

- **Análisis de destinos sobre el acumulado histórico**: se comprobó que la mayor retención de los destinos top no se explica por antigüedad en el catálogo (874 vs. 871 días de media entre el top-3 y el resto), descartando ese sesgo.


### Definición de métricas clave

- **Venta**: se cuenta por `fecha_reserva` (el día en que se genera la reserva), no por `fecha_actividad` (el día en que se disfruta el tour, que puede ser meses después) — se reconoce el ingreso cuando se genera, no cuando se presta el servicio. Se distingue **venta bruta** (todas las reservas) de **venta neta** (excluyendo canceladas), para aislar el impacto de las cancelaciones.

- **Cliente recurrente**: cliente con 2 o más reservas no canceladas. Las canceladas no cuentan porque no representan una compra real.

- **Sesión**: cada `session_id` distinto de `ga_eventos`, sin importar cuántos eventos contenga.

- **Conversión**: una sesión convierte si contiene al menos un evento `purchase`.

- **Dispositivo dominante (cliente)**: el `device` con más eventos de navegación de ese cliente en todo su historial — mide *hábito*, no un instante concreto. Se usa para la pregunta de recurrencia.

- **Dispositivo dominante (sesión)**: el `device` con más eventos dentro de una sesión concreta — mide el dispositivo *en el momento de decidir comprar o no*. Se usa para la pregunta de conversión.


### Limitaciones documentadas

- **"Experiencia de compra" como factor de repetición**: el dataset no contiene señales directas de experiencia (valoraciones, encuestas, incidencias).

- **Campañas con muestra pequeña**: varias campañas analizadas tienen menos de 300 clientes (alguna con solo 61), así que sus porcentajes de recurrencia se presentan como tendencia orientativa, no como conclusión cerrada.

- **Gráficos basados en `eventos_con_id`** (dispositivo dominante y conversión) no responden a los filtros de canal/fecha del sidebar de la app, porque `ga_eventos` no tiene columna de canal ni una fecha suficientemente fiable para filtrar sin introducir sesgo — se muestran siempre sobre el histórico completo, marcado explícitamente en la propia app.


### Tareas delegadas en IA

- Diseño de la estructura del repositorio y del pipeline de datos (conexión → limpieza → identidad → métricas → análisis)

- Escritura de las consultas SQL de limpieza, resolución de identidad y análisis, sobre decisiones tomadas y verificadas por mí en cada paso

- Código de la app Streamlit

- Auditorías de cobertura (¿qué preguntas del enunciado quedaban sin responder?) y de sanidad técnica (chequear la posible existencia de números inconsistentes entre notebooks, código muerto)

### Qué propuso la IA y descarté (y por qué)

- **Modelo predictivo (regresión logística / Random Forest) para repetición**: descartado. Las 3 preguntas del comité son descriptivas/explicativas ("qué factores explican"), no predictivas, y el criterio de evaluación del enunciado no incluye modelado — prioricé síntesis ejecutiva sobre profundidad técnica no solicitada.

- **DuckDB solo para el CSV grande (`ga_eventos`) y pandas para el resto**: descartado en favor de DuckDB para los 5 ficheros. Los notebooks necesitan cruzar constantemente el fichero grande con los pequeños; mantener dos motores obligaba a cargar igualmente el fichero grande en pandas para poder cruzarlo, anulando la ventaja de usar DuckDB.

- **Resolución de identidad con una única consulta SQL (`COALESCE` anidado) envuelta en una función con flag `materialize: bool`**: descartado en favor de una versión en pasos explícitos (`paso1` → `paso2` → `eventos_con_id`), cada uno su propia tabla/vista con nombre descriptivo. Es más código, pero cada paso se puede inspeccionar por separado (preferible en mi opinión cuando el tiempo del ejercicio es limitado).

- **Función `connect_raw()`**: propuesta como utilidad para explorar los CSV crudos sueltos sin resolver limpieza. Descartada por no tener ningún uso real en el proyecto.


### Ejemplos de prompts usados con Claude Code

**Ejemplo 1**. Reescribe /src/limpieza.py con este criterio obligatorio: nada de funciones
genéricas con parámetros que cambian el comportamiento, nada de una sola
consulta SQL gigante — en vez de eso, pasos separados y explícitos, cada uno
su propio CREATE TABLE con nombre descriptivo y un comentario de una línea
explicando qué hace.

**Ejemplo 2**. Revisa los 3 notebooks y confirma si las 3 preguntas principales y las 5 de
apoyo del enunciado están respondidas. Dame un informe con qué está cubierto,
qué está parcial y qué falta, sin corregir nada todavía.