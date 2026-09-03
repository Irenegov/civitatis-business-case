# Civitatis — Business Case Data Analyst

Análisis de comportamiento de clientes (repetición, destinos y estado del negocio) a partir de datos de Civitatis.

## Cómo ejecutar la app

1. Clona el repositorio
2. Crea un entorno virtual e instala dependencias:
```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   pip install -r requirements.txt
```
3. Coloca los 5 CSV proporcionados por Civitatis en `/data/raw`
   (no se incluyen en el repo por tamaño y por política del ejercicio)
4. Ejecuta la app:
```bash
   streamlit run app/main.py
```

## Estructura del repositorio

- `/data` — CSV procesados
    - `/data/raw`— CSV originales
- `/notebooks` — exploración y análisis iterativo
- `/src` — código de limpieza, features y modelos
- `/app` — aplicación interactiva (Streamlit)

## Decisiones y uso de IA

_(Pendiente de completar a medida que avance el análisis)_

- **Supuestos adoptados:** 
- **Definición de métricas clave:**
  - Venta: 
  - Cliente recurrente: 
  - Sesión: 
  - Conversión: 
- **Tareas delegadas en IA:** 
- **Qué propuso la IA y descarté (y por qué):**