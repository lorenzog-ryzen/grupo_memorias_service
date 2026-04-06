import streamlit as st
from login_grouplac import (
    render_login_module,
    render_integrantes_table,
    render_lineas_investigacion_table,
    render_all_integrantes_cvlac,
    render_cvlac_debug_for_logged_user,
    render_orcid_connector,
)

# ─────────────────────────────────────────────
# Configuración de página
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="CvLAC Scraper — Grupo Memorias",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CSS global (pequeño toque visual)
# ─────────────────────────────────────────────
st.markdown("""
<style>
    /* Sidebar title */
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2 {
        font-size: 1.05rem !important;
        color: #1a4080;
    }
    /* Separador suave */
    hr { border-color: #c7d4e8; }
    /* Radio buttons del menú lateral como pills */
    [data-testid="stSidebar"] .stRadio > label {
        font-weight: 600;
        color: #2c4a7c;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# Encabezado principal
# ─────────────────────────────────────────────
st.title("🔬 CvLAC Scrapper — Grupo Memorias")

# ─────────────────────────────────────────────
# Módulo de login (siempre visible arriba)
# ─────────────────────────────────────────────
logged, ctx = render_login_module(prefix="gruplac", title="Login Gruplac")

st.divider()

# ─────────────────────────────────────────────
# Contenido principal (solo si hay sesión)
# ─────────────────────────────────────────────
if not logged:
    st.info("🔐 Inicia sesión para acceder a las herramientas de consulta.")
    st.stop()

# ── Sidebar: navegación en dos pestañas ──────
with st.sidebar:
    st.markdown("## 🧭 Navegación")
    st.markdown("---")
    tab_sel = st.radio(
        "Selecciona una sección:",
        options=[
            "📋 CvLAC — Integrantes & Líneas",
            "🟢 ORCID",
        ],
        index=0,
        key="sidebar_tab",
    )
    st.markdown("---")
    st.caption("Grupo Memorias · Minciencias")

# ─────────────────────────────────────────────
# PESTAÑA 1 — CvLAC Integrantes, Líneas y Timeline
# ─────────────────────────────────────────────
if tab_sel == "📋 CvLAC — Integrantes & Líneas":
    st.header("📋 CvLAC del Grupo")

    with st.container():
        render_integrantes_table(ctx, title="Integrantes del grupo")

    st.divider()

    with st.container():
        render_lineas_investigacion_table(ctx, title="Líneas de investigación")

    st.divider()

    with st.container():
        render_all_integrantes_cvlac(ctx)

# ─────────────────────────────────────────────
# PESTAÑA 2 — ORCID
# ─────────────────────────────────────────────
elif tab_sel == "🟢 ORCID":
    st.header("🟢 Conector ORCID")
    st.caption(
        "Consulta el perfil ORCID y las publicaciones (works) de cualquier investigador. "
        "Puedes usar el ORCID iD del usuario logueado (si se ingresó al iniciar sesión) "
        "o escribir uno manualmente."
    )

    st.divider()

    # Opción 1: ORCID del usuario logueado + lookup en CvLAC
    with st.expander("🔍 Detectar ORCID desde CvLAC del usuario logueado", expanded=True):
        st.caption(
            "Busca automáticamente el CvLAC del usuario en la lista de integrantes "
            "y extrae su ORCID iD."
        )
        render_cvlac_debug_for_logged_user(ctx)

    st.divider()

    # Opción 2: Consulta manual libre
    with st.expander("✏️ Consultar ORCID manualmente (cualquier investigador)", expanded=False):
        render_orcid_connector(ctx)