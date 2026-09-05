"""
App Streamlit de una sola página con las métricas de negocio de Civitatis.
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

# Filtros (sidebar)
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

# Tab 1: Estado del negocio
with tab_negocio:
    st.markdown(
        "**Cuánto se ha vendido realmente**: se distingue la venta bruta de la venta neta "
        "(descontando cancelaciones) y se tiene en cuenta que hasta julio de 2024 la operativa fue de "
        "prueba, con datos poco representativos del negocio real."
    )

    cancelacion = q.tasa_cancelacion(con, canal=canal, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)

    if cancelacion["total_reservas"][0] == 0:
        st.info("No hay reservas para este filtro.")
    else:
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
        col1, col2, col3 = st.columns(3)

        canceladas_fmt = f"{int(cancelacion['reservas_canceladas'][0]):,}".replace(",", ".")
        total_fmt = f"{int(cancelacion['total_reservas'][0]):,}".replace(",", ".")

        col1.metric("Reservas canceladas", canceladas_fmt)
        col2.metric("Total de reservas", total_fmt)
        col3.metric("Tasa de cancelación", f"{cancelacion['tasa_cancelacion_pct'][0]:.2f} %")

        st.subheader("Tasa de cancelación por canal")
        st.caption("Este gráfico ya desglosa por canal, así que ignora el filtro de canal del sidebar (sí respeta el de fechas).")
        cancelacion_canal = q.cancelacion_por_canal(con, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        fig = px.bar(cancelacion_canal.sort_values("tasa_cancelacion_pct"), x="tasa_cancelacion_pct", y="canal", orientation="h",
                      labels={"tasa_cancelacion_pct": "Tasa de cancelación (%)", "canal": "Canal"})
        st.plotly_chart(fig, width="stretch")

# Tab 2: Destinos
with tab_destinos:
    st.markdown(
        "Qué destinos tienen más acogida y cuáles retienen mejor a sus clientes**. "
        "No siempre coinciden: hay destinos que venden mucho pero retienen poco, y otros con menos "
        "volumen que fidelizan mejor a quien los reserva."
    )

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

        st.subheader("Tasa de cancelación por destino")
        cancelacion_destino = q.cancelacion_por_destino(con, canal=canal, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        fig = px.bar(cancelacion_destino.sort_values("tasa_cancelacion_pct"), x="tasa_cancelacion_pct", y="destino", orientation="h",
                      labels={"tasa_cancelacion_pct": "Tasa de cancelación (%)", "destino": "Destino"})
        st.plotly_chart(fig, width="stretch")

# Tab 3: Repetición
with tab_repeticion:
    st.markdown(
        "**Qué factores explican que un cliente repita**. El canal de adquisición y la "
        "campaña asociada a la reserva pesan más en la recurrencia que el dispositivo desde el que se "
        "navega o se compra."
    )

    st.subheader("% de clientes recurrentes por canal")
    st.caption("Este gráfico ya desglosa por canal, así que ignora el filtro de canal del sidebar (sí respeta el de fechas).")
    recurrencia_canal = q.recurrencia_por_canal(con, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    fig = px.bar(recurrencia_canal.sort_values("pct_recurrencia"), x="pct_recurrencia", y="canal", orientation="h",
                  labels={"pct_recurrencia": "% clientes recurrentes", "canal": "Canal"})
    st.plotly_chart(fig, width="stretch")

    st.subheader("% de clientes recurrentes por campaña")
    recurrencia_campana = q.recurrencia_campana(con, canal=canal, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    fig = px.bar(recurrencia_campana.sort_values("pct_recurrencia"), x="pct_recurrencia", y="campana", orientation="h",
                  labels={"pct_recurrencia": "% clientes recurrentes", "campana": "Campaña"})
    st.plotly_chart(fig, width="stretch")

    campana_recurrentes = q.recurrentes_sin_campana_vs_con_campana(con, canal=canal, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    if campana_recurrentes["total_recurrentes"][0] == 0:
        st.info("No hay clientes recurrentes para este filtro.")
    else:
        col1, col2 = st.columns(2)
        col1.metric("Recurrentes con alguna reserva sin campaña",
                     f"{campana_recurrentes['pct_con_reserva_sin_campana'][0]:.2f} %")
        col2.metric("Recurrentes con alguna reserva con campaña",
                     f"{campana_recurrentes['pct_con_alguna_campana'][0]:.2f} %")

    st.subheader("Distribución de frecuencia de reservas de clientes recurrentes")
    distribucion_frecuencia = q.distribucion_frecuencia_reservas(con, canal=canal, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    if distribucion_frecuencia.empty:
        st.info("No hay clientes recurrentes para este filtro.")
    else:
        fig = px.bar(distribucion_frecuencia, x="n_reservas", y="n_clientes",
                      labels={"n_reservas": "Nº de reservas", "n_clientes": "Nº de clientes"})
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
    if intervalo["n_clientes_recurrentes"][0] == 0:
        st.info("No hay clientes recurrentes para este filtro.")
    else:
        col1, col2 = st.columns(2)
        col1.metric("Intervalo medio", f"{intervalo['intervalo_medio_dias'][0]:.2f} días")
        col2.metric("Clientes recurrentes considerados", f"{int(intervalo['n_clientes_recurrentes'][0]):,}")
