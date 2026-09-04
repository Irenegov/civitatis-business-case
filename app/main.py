"""App Streamlit de una sola página con las métricas de negocio de Civitatis.
Reutiliza las consultas de /src/queries.py (las mismas de los notebooks 02 y
03) sobre la base ya limpia /data/processed/civitatis.duckdb.

Arrancar con: streamlit run app/main.py
"""

import calendar
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from src import conexion, queries as q

st.set_page_config(page_title="Civitatis — Panel de negocio", layout="wide")


@st.cache_resource
def get_connection():
    return conexion.connect_processed()


try:
    con = get_connection()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

st.title("Civitatis — Panel de negocio")

# === Filtros (sidebar) ===
st.sidebar.header("Filtros")

canales = ["Todos"] + q.canales_disponibles(con)
canal_seleccionado = st.sidebar.selectbox("Canal", canales)
canal = None if canal_seleccionado == "Todos" else canal_seleccionado

meses = q.meses_disponibles(con)
mes_desde = st.sidebar.selectbox("Desde (mes)", meses, index=0)
mes_hasta = st.sidebar.selectbox("Hasta (mes)", meses, index=len(meses) - 1)

fecha_desde = f"{mes_desde}-01"
anio_hasta, num_mes_hasta = (int(x) for x in mes_hasta.split("-"))
ultimo_dia_hasta = calendar.monthrange(anio_hasta, num_mes_hasta)[1]
fecha_hasta = f"{mes_hasta}-{ultimo_dia_hasta:02d}"

if mes_desde > mes_hasta:
    st.sidebar.warning("'Desde' es posterior a 'Hasta': no habrá resultados en ese rango.")

tab_negocio, tab_destinos, tab_repeticion = st.tabs(["Estado del negocio", "Destinos", "Repetición"])

# === Tab 1: Estado del negocio ===
with tab_negocio:
    ventas = q.venta_bruta_vs_neta(con, canal=canal, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    bruta = ventas["venta_bruta"][0] or 0
    neta = ventas["venta_neta"][0] or 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Venta bruta", f"{bruta:,.2f} €")
    col2.metric("Venta neta", f"{neta:,.2f} €")
    col3.metric("Diferencia (cancelaciones)", f"{bruta - neta:,.2f} €")

    st.subheader("Evolución mensual de venta neta")
    evolucion = q.evolucion_mensual_venta_neta(con, canal=canal, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    fig = px.line(evolucion, x="mes", y="venta_neta", markers=True,
                   labels={"mes": "Mes", "venta_neta": "Venta neta (€)"})
    st.plotly_chart(fig, width="stretch")

    st.subheader("Tasa de cancelación")
    cancelacion = q.tasa_cancelacion(con, canal=canal, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    col1, col2 = st.columns(2)
    col1.metric("Tasa de cancelación", f"{cancelacion['tasa_cancelacion_pct'][0]:.2f} %")
    col2.metric("Total de reservas", f"{int(cancelacion['total_reservas'][0]):,}")

# === Tab 2: Destinos ===
with tab_destinos:
    st.subheader("Ranking de destinos por venta neta")
    ranking = q.ranking_destinos(con, canal=canal, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    if ranking.empty:
        st.info("No hay reservas para este filtro.")
    else:
        fig = px.bar(ranking.sort_values("venta_neta"), x="venta_neta", y="destino", orientation="h",
                      labels={"venta_neta": "Venta neta (€)", "destino": "Destino"})
        st.plotly_chart(fig, width="stretch")

        st.subheader("% de clientes recurrentes en esos destinos")
        recurrencia = q.recurrencia_destinos(con, tuple(ranking["destino"]), canal=canal,
                                              fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        fig = px.bar(recurrencia.sort_values("pct_recurrencia"), x="pct_recurrencia", y="destino", orientation="h",
                      labels={"pct_recurrencia": "% clientes recurrentes", "destino": "Destino"})
        st.plotly_chart(fig, width="stretch")

# === Tab 3: Repetición ===
with tab_repeticion:
    st.subheader("% de clientes recurrentes por canal")
    st.caption("Este gráfico ya desglosa por canal, así que ignora el filtro de canal del sidebar (sí respeta el de fechas).")
    recurrencia_canal = q.recurrencia_por_canal(con, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    fig = px.bar(recurrencia_canal.sort_values("pct_recurrencia"), x="pct_recurrencia", y="canal", orientation="h",
                  labels={"pct_recurrencia": "% clientes recurrentes", "canal": "Canal"})
    st.plotly_chart(fig, width="stretch")

    st.caption("Los siguientes gráficos usan `eventos_con_id` (tráfico web), que no tiene columna de canal "
               "ni una fecha fiable para filtrar, así que no responden a los filtros del sidebar.")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("% de clientes recurrentes por dispositivo dominante")
        recurrencia_dispositivo = q.recurrencia_por_dispositivo(con)
        fig = px.bar(recurrencia_dispositivo.sort_values("pct_recurrencia"),
                      x="pct_recurrencia", y="dispositivo_dominante", orientation="h",
                      labels={"pct_recurrencia": "% clientes recurrentes", "dispositivo_dominante": "Dispositivo dominante"})
        st.plotly_chart(fig, width="stretch")

    with col2:
        st.subheader("Tasa de conversión: mobile vs. desktop")
        conversion = q.conversion_por_dispositivo(con)
        fig = px.bar(conversion.sort_values("tasa_conversion_pct"),
                      x="tasa_conversion_pct", y="dispositivo_dominante", orientation="h",
                      labels={"tasa_conversion_pct": "Tasa de conversión (%)", "dispositivo_dominante": "Dispositivo dominante"})
        st.plotly_chart(fig, width="stretch")

    st.subheader("% de sesiones con user_id vs. sin user_id")
    sesiones = q.sesiones_con_sin_user_id(con)
    fig = px.pie(sesiones, names="tipo_sesion", values="n_sesiones")
    st.plotly_chart(fig, width="stretch")

    st.subheader("Intervalo medio entre la 1ª y 2ª reserva de clientes recurrentes")
    intervalo = q.intervalo_recompra(con, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    col1, col2 = st.columns(2)
    col1.metric("Intervalo medio", f"{intervalo['intervalo_medio_dias'][0]:.2f} días")
    col2.metric("Clientes recurrentes considerados", f"{int(intervalo['n_clientes_recurrentes'][0]):,}")
