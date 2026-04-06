# login_gruplac.py
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List
from urllib.parse import urljoin, urlparse, parse_qs

import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup
import streamlit.components.v1 as components


# =========================
# Constantes / Endpoints
# =========================
BASE = "https://scienti.minciencias.gov.co"

# Gruplac
INDEX = f"{BASE}/gruplac/jsp/index.jsp"
LOGIN = f"{BASE}/gruplac/LoginGruplac/login.do"

URL_INTEGRANTES = f"{BASE}/gruplac/EnRecursoHumanoGr/all.do?__tableAction=resetAll&act=t"
URL_LINEAS_INVESTIGACION = f"{BASE}/gruplac/EnLineaInvestigacion/all.do?__tableAction=resetAll"

# CvLAC
CVLAC_URL_TEMPLATE = f"{BASE}/cvlac/visualizador/generarCurriculoCv.do?cod_rh={{cod_rh}}"

REDIRECT_CODES = (301, 302, 303, 307, 308)


# =========================
# Modelos
# =========================
@dataclass
class LoginResult:
    ok: bool
    message: str
    session: Optional[requests.Session] = None
    final_url: Optional[str] = None


# =========================
# Utilidades (texto / html)
# =========================
def strip_jsessionid(u: str) -> str:
    return re.sub(r";jsessionid=[^?]+", "", u or "")


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def _norm_name(s: str) -> str:
    """Mayúsculas, sin tildes, espacios simples."""
    s = _strip_accents((s or "").strip())
    s = " ".join(s.split())
    return s.upper()


def _headers_basic(referer: str | None = None) -> Dict[str, str]:
    h = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    if referer:
        h["Referer"] = referer
    return h


# =========================
# Login y redirects
# =========================
def follow_302(
    session: requests.Session,
    start_url: str,
    headers: dict,
    max_hops: int = 15
) -> requests.Response:
    """
    Sigue redirects manualmente (sin allow_redirects), limpiando ;jsessionid y forzando https/domain.
    """
    url = strip_jsessionid(start_url)

    for _ in range(max_hops):
        r = session.get(url, headers=headers, allow_redirects=False, timeout=25)

        if r.status_code in REDIRECT_CODES:
            loc = r.headers.get("Location")
            if not loc:
                return r

            nxt = urljoin(BASE, loc).replace("http://", "https://")
            nxt = strip_jsessionid(nxt)

            p = urlparse(nxt)
            url = p._replace(scheme="https", netloc="scienti.minciencias.gov.co").geturl()
            continue

        return r

    raise RuntimeError("Demasiados redirects (posible loop).")


def perform_login(
    nme_rh: str,
    cpf_rh: str,
    dta_nasc_string: str,
    txt_senha_cnpq: str,
    tpo_nacionalidade: str = "C",
    sgl_pais_nasc: str = "COL",
) -> LoginResult:
    """
    Login real a Gruplac con requests.Session.
    """
    nme_rh = (nme_rh or "").strip()
    cpf_rh = (cpf_rh or "").strip()
    dta_nasc_string = (dta_nasc_string or "").strip()
    txt_senha_cnpq = (txt_senha_cnpq or "").strip()

    if not all([nme_rh, cpf_rh, dta_nasc_string, txt_senha_cnpq]):
        return LoginResult(False, "Faltan campos obligatorios.")

    s = requests.Session()

    headers0 = {
        "User-Agent": "Mozilla/5.0",
        "Referer": INDEX,
        "Origin": BASE,
    }

    payload = {
        "nme_rh": nme_rh,
        "cpf_rh": cpf_rh,
        "dta_nasc_string": dta_nasc_string,
        "txt_senha_cnpq": txt_senha_cnpq,
        "tpo_nacionalidade": tpo_nacionalidade,
        "sgl_pais_nasc": sgl_pais_nasc,
    }

    try:
        # 0) GET inicial (cookies)
        r0 = s.get(INDEX, headers=headers0, allow_redirects=True, timeout=25)
        r0.raise_for_status()

        # 1) POST login
        r_login = s.post(LOGIN, data=payload, headers=headers0, allow_redirects=False, timeout=25)
        loc = r_login.headers.get("Location")

        if r_login.status_code not in REDIRECT_CODES or not loc:
            snippet = (r_login.text or "")[:900]
            return LoginResult(False, f"Login no redirigió. Snippet:\n{snippet}")

        # 2) seguir redirects manual
        headers2 = _headers_basic()
        start = urljoin(BASE, loc).replace("http://", "https://")
        final_resp = follow_302(s, start, headers2)

        # chequeo simple
        soup = BeautifulSoup(final_resp.text or "", "html.parser")
        has_internal = any(a.get("href", "").startswith("/gruplac/En") for a in soup.select("a[href]"))
        has_group_word = "Grupo" in (final_resp.text or "")

        if not (has_internal or has_group_word):
            return LoginResult(False, "No se detectó sesión activa tras login. Revisa credenciales/formato.")

        return LoginResult(True, "Login exitoso.", session=s, final_url=final_resp.url)

    except requests.RequestException as e:
        return LoginResult(False, f"Error de red/HTTP: {e}")
    except Exception as e:
        return LoginResult(False, f"Error inesperado: {e}")


# =========================
# Session state / UI login
# =========================
def init_state(prefix: str = "gruplac") -> None:
    st.session_state.setdefault(f"{prefix}_logged_in", False)
    st.session_state.setdefault(f"{prefix}_session", None)       # requests.Session
    st.session_state.setdefault(f"{prefix}_user_payload", None)  # sin contraseña
    st.session_state.setdefault(f"{prefix}_last_message", "")


def logout(prefix: str = "gruplac") -> None:
    st.session_state[f"{prefix}_logged_in"] = False
    st.session_state[f"{prefix}_session"] = None
    st.session_state[f"{prefix}_user_payload"] = None
    st.session_state[f"{prefix}_last_message"] = "Sesión cerrada."


def render_login_module(prefix: str = "gruplac", title: str = "Login Gruplac") -> Tuple[bool, Optional[Dict[str, Any]]]:
    init_state(prefix)
    st.subheader(f"🔐 {title}")

    if st.session_state[f"{prefix}_logged_in"]:
        payload = st.session_state[f"{prefix}_user_payload"] or {}
        st.success("Sesión activa")
        st.write("**Nombre:**", payload.get("nme_rh"))
        st.write("**Identificación:**", payload.get("cpf_rh"))

        col1, col2 = st.columns([1, 2])
        with col1:
            if st.button("Cerrar sesión", key=f"{prefix}_logout", use_container_width=True):
                logout(prefix)
                st.rerun()
        with col2:
            st.info("Ya puedes consultar tablas autenticadas.")

        return True, {"session": st.session_state[f"{prefix}_session"], "payload": payload}

    with st.form(key=f"{prefix}_login_form", clear_on_submit=False):
        nme_rh = st.text_input("Nombre (exacto como en CvLAC)", placeholder="Ivonne Molinares")
        cpf_rh = st.text_input("Identificación (sin puntos ni espacios)", placeholder="22443688")
        dta_nasc_string = st.text_input("Fecha de nacimiento", placeholder="DD/MM/AAAA (ej: 02/02/1968)")
        orcid_id = st.text_input(
            "ORCID iD (opcional)",
            placeholder="0000-0002-8656-8179 o https://orcid.org/0000-0002-8656-8179"
        )
        show_pw = st.checkbox("Mostrar contraseña")
        txt_senha_cnpq = st.text_input(
            "Contraseña (CNPq/Gruplac)",
            type="default" if show_pw else "password",
            placeholder="••••••••"
        )

        submit = st.form_submit_button("Ingresar", use_container_width=True)

    if submit:
        res = perform_login(
            nme_rh=nme_rh,
            cpf_rh=cpf_rh,
            dta_nasc_string=dta_nasc_string,
            txt_senha_cnpq=txt_senha_cnpq,
            tpo_nacionalidade="C",
            sgl_pais_nasc="COL",
        )

        st.session_state[f"{prefix}_last_message"] = res.message

        if res.ok and res.session:
            st.session_state[f"{prefix}_logged_in"] = True
            st.session_state[f"{prefix}_session"] = res.session
            st.session_state[f"{prefix}_user_payload"] = {
                "nme_rh": nme_rh.strip(),
                "cpf_rh": cpf_rh.strip(),
                "dta_nasc_string": dta_nasc_string.strip(),
                "tpo_nacionalidade": "C",
                "sgl_pais_nasc": "COL",
                "final_url": res.final_url,
                "orcid_id": orcid_id.strip(),
            }
            st.success(res.message)
            st.rerun()
        else:
            st.error(res.message)

    if st.session_state.get(f"{prefix}_last_message"):
        st.caption(st.session_state[f"{prefix}_last_message"])

    return False, None


# =========================
# Integrantes
# =========================
def fetch_integrantes_html(session: requests.Session) -> str:
    r = session.get(URL_INTEGRANTES, headers=_headers_basic(), timeout=25, allow_redirects=True)
    r.raise_for_status()
    if not r.encoding:
        r.encoding = r.apparent_encoding
    return r.text or ""


def fetch_integrantes_df(session: requests.Session) -> pd.DataFrame:
    html = fetch_integrantes_html(session)
    tables = pd.read_html(html)
    if not tables:
        raise ValueError("No se encontraron tablas en la página de integrantes.")
    return tables[0]


def render_integrantes_table(ctx: Dict[str, Any], title: str = "Integrantes del grupo") -> None:
    st.subheader(f"📋 {title}")
    session = ctx.get("session") if ctx else None
    if session is None:
        st.warning("No hay sesión activa.")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        run = st.button("Cargar integrantes", use_container_width=True)
    with col2:
        st.caption("Extrae la primera tabla HTML de la página de integrantes.")

    if run:
        try:
            with st.spinner("Consultando integrantes..."):
                df = fetch_integrantes_df(session)
            st.success(f"Tabla cargada: {df.shape[0]} filas × {df.shape[1]} columnas")
            st.dataframe(df, use_container_width=True)

            st.download_button(
                "⬇️ Descargar CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="gruplac_integrantes.csv",
                mime="text/csv",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"No se pudo cargar la tabla: {e}")


# =========================
# Match CvLAC (usuario logueado)
# =========================
def _first_name_and_first_surname_from_input(user_name: str) -> tuple[str, str]:
    """
    user_name viene del input (ej: "Ivonne Molinares") => ("IVONNE", "MOLINARES")
    """
    parts = _norm_name(user_name).split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    if len(parts) == 1:
        return parts[0], ""
    return "", ""


def find_cvlac_for_logged_user(session: requests.Session, user_name_input: str) -> Dict[str, Any]:
    """
    Encuentra el cvlac_url del usuario logueado usando:
      - primer nombre igual
      - y que el primer apellido (del input) aparezca en CUALQUIER token posterior del nombre de la fila
        (soporta nombres compuestos: Ivonne Samira Molinares Guerrero)
    """
    html = fetch_integrantes_html(session)
    soup = BeautifulSoup(html, "html.parser")

    target_fn, target_ln = _first_name_and_first_surname_from_input(user_name_input)
    debug_rows: List[Dict[str, Any]] = []

    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        nombre = tds[0].get_text(" ", strip=True)
        nombre_norm = _norm_name(nombre)
        tokens = nombre_norm.split()

        # link CvLAC
        cvlac_a = None
        for a in tr.select("a[href]"):
            if a.get_text(" ", strip=True).lower() == "cvlac":
                cvlac_a = a
                break
        if not cvlac_a:
            continue

        href = (cvlac_a.get("href") or "").strip()
        full = urljoin(BASE, href)

        qs = parse_qs(urlparse(full).query)
        cod_rh = (qs.get("cod_rh") or [""])[0]

        row_fn = tokens[0] if tokens else ""
        surname_present = (target_ln in tokens[1:]) if target_ln else False

        debug_rows.append({
            "nombre": nombre,
            "nombre_norm": nombre_norm,
            "row_first_name": row_fn,
            "target_first_name": target_fn,
            "surname_present": surname_present,
            "target_first_surname": target_ln,
            "cvlac_url": full,
            "cod_rh": cod_rh,
        })

        if cod_rh and row_fn == target_fn and (surname_present or target_ln == ""):
            return {"ok": True, "cod_rh": cod_rh, "cvlac_url": full, "debug": {"rows": debug_rows}}

    return {"ok": False, "cod_rh": "", "cvlac_url": "", "debug": {"rows": debug_rows}}


# =========================
# CvLAC fetch + Debug + búsqueda términos
# =========================
def fetch_cvlac_response(session: requests.Session, cvlac_url: str) -> requests.Response:
    r = session.get(
        cvlac_url,
        headers=_headers_basic(referer=URL_INTEGRANTES),
        timeout=25,
        allow_redirects=True
    )
    r.raise_for_status()
    if not r.encoding:
        r.encoding = r.apparent_encoding
    return r


def debug_find_terms_in_html(html: str, terms: list[str], window: int = 350) -> Dict[str, Any]:
    """
    Busca términos (con y sin tildes) y devuelve:
      found, count, matched_mode, snippets
    """
    res: Dict[str, Any] = {}
    html_plain = html or ""
    html_noacc = _strip_accents(html_plain)

    for term in terms:
        term_noacc = _strip_accents(term)

        patt_plain = re.compile(re.escape(term), re.IGNORECASE)
        patt_noacc = re.compile(re.escape(term_noacc), re.IGNORECASE)

        matches_plain = list(patt_plain.finditer(html_plain))
        matches_noacc = list(patt_noacc.finditer(html_noacc))
        matches = matches_plain if matches_plain else matches_noacc

        snippets = []
        for m in matches[:5]:
            start = max(0, m.start() - window)
            end = min(len(html_plain), m.end() + window)
            snippets.append(html_plain[start:end])

        res[term] = {
            "found": bool(matches),
            "count": len(matches),
            "matched_mode": "plain" if matches_plain else ("noaccents" if matches_noacc else "none"),
            "snippets": snippets,
        }

    return res


def render_cvlac_debug_for_logged_user(ctx: Dict[str, Any]) -> None:
    """
    1) toma nombre desde ctx.payload.nme_rh
    2) encuentra cvlac_url en integrantes (match robusto)
    3) abre cvlac_url y muestra todo (redirects, url final, cookies, title, snippet)
    4) busca términos (Artículos, Eventos científicos, Líneas de investigación)
    """

    session = ctx.get("session") if ctx else None
    payload = ctx.get("payload") if ctx else None
    if session is None or payload is None:
        st.warning("No hay sesión/payload. Inicia sesión primero.")
        return

    user_name = payload.get("nme_rh", "")



    with st.spinner("Buscando cvlac_url desde Integrantes..."):
        found = find_cvlac_for_logged_user(session, user_name)



    if not found["ok"]:
        st.error("No pude encontrar el CvLAC del usuario. Revisa el expander.")
        return

    with st.spinner("Abriendo CvLAC..."):
        resp = fetch_cvlac_response(session, found["cvlac_url"])

    html = resp.text or ""
    links = debug_cvlac_profile_links(html)
    render_orcid_connector(ctx, fallback_orcid=links.get("ORCID"))


# =========================
# Debug: Profile links (Scholar, ResearchGate, Academia, ORCID)
# =========================
def debug_cvlac_profile_links(html: str) -> None:
    soup = BeautifulSoup(html or "", "html.parser")

    TARGETS = {
        "Google Scholar": ["scholar.google"],
        "ResearchGate":   ["researchgate.net"],
        "Academia.edu":   ["academia.edu"],
        "ORCID":          ["orcid.org"],
    }

    found = {name: None for name in TARGETS}

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        label = a.get_text(" ", strip=True)
        for name, patterns in TARGETS.items():
            if found[name]:
                continue
            if any(p in href for p in patterns) or any(p in label.lower() for p in [name.lower()]):
                found[name] = href

    with st.expander("Ver todos los <a href> del CvLAC"):
        all_links = [(a.get_text(" ", strip=True), a["href"]) for a in soup.find_all("a", href=True)]
        st.dataframe(
            {"Texto": [l[0] for l in all_links], "URL": [l[1] for l in all_links]},
            use_container_width=True
        )
    return found
# =========================
# Líneas de investigación (Gruplac)
# =========================
def fetch_lineas_investigacion_df(session: requests.Session) -> pd.DataFrame:
    resp = session.get(URL_LINEAS_INVESTIGACION, headers=_headers_basic(), timeout=25, allow_redirects=True)
    resp.raise_for_status()
    if not resp.encoding:
        resp.encoding = resp.apparent_encoding
    html = resp.text or ""
    soup = BeautifulSoup(html, "html.parser")

    # intentamos ubicar la tabla por texto
    target_table = None
    for tbl in soup.find_all("table"):
        txt = tbl.get_text(" ", strip=True)
        if ("Nombre de la Línea" in txt) or ("Nombre de la Linea" in _strip_accents(txt)):
            target_table = tbl
            break

    if target_table is None:
        # fallback: intentar con pandas directamente
        tables = pd.read_html(html)
        if tables:
            # buscar la que contenga "Nombre de la Línea"
            for t in tables:
                joined = " ".join(map(str, t.columns)).lower()
                if "nombre" in joined and ("línea" in joined or "linea" in joined):
                    return t
        raise ValueError("No se encontró la tabla de líneas de investigación en el HTML.")

    rows = []
    for tr in target_table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) >= 2:
            num = tds[0].get_text(" ", strip=True)
            nombre = tds[1].get_text(" ", strip=True)
            if num and nombre:
                rows.append({"nro": num, "nombre_linea": nombre})

    if not rows:
        raise ValueError("Se encontró la tabla, pero no se pudieron extraer filas.")
    return pd.DataFrame(rows)


def render_lineas_investigacion_table(ctx: Dict[str, Any], title: str = "Líneas de investigación") -> None:
    st.subheader(f"🧭 {title}")
    session = ctx.get("session") if ctx else None
    if session is None:
        st.warning("No hay sesión activa.")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        run = st.button("Cargar líneas de investigación", use_container_width=True)
    with col2:
        st.caption("Extrae la tabla HTML desde la sección de Líneas de investigación.")

    if run:
        try:
            with st.spinner("Consultando líneas de investigación..."):
                df = fetch_lineas_investigacion_df(session)

            st.success(f"Tabla cargada: {df.shape[0]} filas × {df.shape[1]} columnas")
            st.dataframe(df, use_container_width=True)

            st.download_button(
                "⬇️ Descargar CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="gruplac_lineas_investigacion.csv",
                mime="text/csv",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"No se pudo cargar la tabla: {e}")
def extract_section_html_by_heading(html: str, heading_text: str) -> str:
    """
    Extrae el bloque HTML 'cercano' a un heading (por texto).
    Devuelve un HTML mínimo renderizable (con wrapper y estilos básicos).
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # Buscar nodo que contenga el heading (con y sin tildes)
    target = None
    heading_norm = _strip_accents(heading_text).lower()

    for tag in soup.find_all(True):
        txt = tag.get_text(" ", strip=True)
        if not txt:
            continue
        if heading_text.lower() in txt.lower():
            target = tag
            break
        if _strip_accents(txt).lower() == heading_norm or heading_norm in _strip_accents(txt).lower():
            target = tag
            break

    if not target:
        return ""

    # Subir a un contenedor “razonable” (para atrapar la lista completa)
    container = target
    for _ in range(6):
        if container.name in ("td", "div", "section", "article"):
            break
        if container.parent:
            container = container.parent
        else:
            break

    # Dentro del contenedor buscamos un UL/OL cercano (lo típico de esa sección)
    ul = container.find(["ul", "ol"])
    if not ul:
        # fallback: tomar el contenedor completo
        content_html = str(container)
    else:
        # construir un bloque con el título + lista
        title_html = f"<h3 style='margin:0 0 10px 0'>{heading_text}</h3>"
        content_html = title_html + str(ul)

    # Wrapper con estilo simple (para que se vea limpio)
    wrapped = f"""
    <div style="
        font-family: Arial, sans-serif;
        font-size: 14px;
        line-height: 1.35;
        padding: 12px 14px;
        border: 1px solid #e6e6e6;
        border-radius: 10px;
        background: #ffffff;
        max-width: 100%;
    ">
      {content_html}
    </div>
    """
    return wrapped
def render_cvlac_lineas_investigacion_section(html: str):
    st.subheader("📌 CvLAC — Líneas de investigación (render)")

    section_html = extract_section_html_by_heading(html, "Líneas de investigación")

    if not section_html:
        st.warning("No encontré la sección 'Líneas de investigación' en el HTML.")
        return

    components.html(section_html, height=320, scrolling=True)
def extract_cvlac_articulos_html(html: str) -> str:
    """
    Extrae SOLO los ítems de artículos (los bullets con:
    'Producción bibliográfica - Artículo - Publicado ...'),
    evitando el índice/menú y el resto del CvLAC.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # 1) Encontrar únicamente <li> que sean entradas reales de artículos
    items = []
    for li in soup.find_all("li"):
        txt = li.get_text(" ", strip=True)
        if not txt:
            continue

        cond_base = ("Producción bibliográfica" in txt and "Artículo" in txt)
        cond_tipo = ("Publicado" in txt) or ("revista" in txt) or ("especializada" in txt)

        # Este filtro evita el índice porque el índice NO tiene "Producción bibliográfica - Artículo - Publicado..."
        if cond_base and cond_tipo:
            items.append(li)

    if not items:
        return ""

    # 2) Renderizar SOLO esos <li> dentro de un <ul> nuevo
    ul_html = "<ul style='padding-left: 22px; margin: 0;'>" + "".join(str(li) for li in items) + "</ul>"

    wrapped = f"""
    <div style="
        font-family: Arial, sans-serif;
        font-size: 14px;
        line-height: 1.35;
        padding: 12px 14px;
        border: 1px solid #e6e6e6;
        border-radius: 10px;
        background: #ffffff;
        max-width: 100%;
    ">
      <h3 style="margin:0 0 10px 0">Artículos</h3>
      {ul_html}
    </div>
    """
    return wrapped



from bs4 import BeautifulSoup, Tag

def extract_cvlac_articulos_items(html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")

    def is_article_header_li(tag: Tag) -> bool:
        if not tag or tag.name != "li":
            return False
        txt = tag.get_text(" ", strip=True)
        if not txt:
            return False
        cond_base = ("Producción bibliográfica" in txt and "Artículo" in txt)
        cond_tipo = ("Publicado" in txt) or ("revista" in txt) or ("especializada" in txt)
        return cond_base and cond_tipo

    headers = [li for li in soup.find_all("li") if is_article_header_li(li)]
    if not headers:
        return []

    items_html = []
    seen_texts = set()

    for li in headers:
        chunks = [str(li)]

        # Recorre en orden de documento, no solo siblings inmediatos
        for el in li.next_elements:
            # saltar strings
            if not getattr(el, "name", None):
                continue

            # si encontramos otro header de artículo, paramos
            if el is not li and is_article_header_li(el):
                break

            # evita arrastrar scripts
            if el.name == "script":
                continue

            # agrega solo tags "relevantes"
            chunks.append(str(el))

            # (opcional) freno por seguridad de tamaño
            if sum(len(c) for c in chunks) > 120_000:
                break

        # Limpieza ligera: quitar onclick para evitar basura
        tmp = BeautifulSoup("<div>" + "\n".join(chunks) + "</div>", "html.parser")
        for t in tmp.select("script"):
            t.decompose()
        for t in tmp.select("[onclick]"):
            del t["onclick"]

        # --- DEDUPLICACIÓN del chunk ensamblado ---
        # El chunk puede contener el mismo bloque de texto varias veces porque
        # next_elements recorre tanto el <li> padre como cada hijo individualmente.
        # Solución: partir el chunk en sub-bloques por texto único.
        seen_blocks = set()
        clean_children = []
        for child in tmp.find("div").children:
            child_text = child.get_text(" ", strip=True) if hasattr(child, "get_text") else str(child).strip()
            if not child_text:
                continue
            if child_text in seen_blocks:
                continue
            seen_blocks.add(child_text)
            clean_children.append(str(child))

        clean_html = "<div>" + "\n".join(clean_children) + "</div>"
        clean_soup = BeautifulSoup(clean_html, "html.parser")

        # Deduplicar artículos completos entre sí (mismo texto = mismo artículo)
        article_key = clean_soup.get_text(" ", strip=True)
        if article_key in seen_texts:
            continue
        seen_texts.add(article_key)

        items_html.append(str(clean_soup))

    return items_html

def render_cvlac_articulos_items(html: str) -> None:
    st.subheader("📚 CvLAC — Artículos ")

    items = extract_cvlac_articulos_items(html)
    st.caption(f"Artículos encontrados: {len(items)}")

    for i, item_html in enumerate(items, start=1):
        with st.expander(f"Artículo #{i}", expanded=(i == 1)):
            # Inject JS that resizes the iframe to fit its content automatically
            auto_html = f"""
            <html><body style="margin:0;padding:8px;font-family:Arial,sans-serif;font-size:14px;line-height:1.4">
            {item_html}
            <script>
                function sendHeight() {{
                    const h = document.body.scrollHeight;
                    window.parent.postMessage({{type:'streamlit:setFrameHeight', height: h}}, '*');
                }}
                window.addEventListener('load', sendHeight);
                window.addEventListener('resize', sendHeight);
                setTimeout(sendHeight, 200);
            </script>
            </body></html>
            """
            # Estimate height from content to avoid initial collapse before JS fires
            approx_lines = max(4, item_html.count("<br") + item_html.count("</p") + item_html.count("</li") + 4)
            est_height = min(approx_lines * 22 + 40, 600)
            components.html(auto_html, height=est_height, scrolling=False)
def debug_locate_article_details(html: str, limit: int = 3):
    soup = BeautifulSoup(html or "", "html.parser")

    # 1) Encuentra headers de artículos
    headers = []
    for li in soup.find_all("li"):
        txt = li.get_text(" ", strip=True)
        if "Producción bibliográfica" in txt and "Artículo" in txt:
            headers.append(li)

    st.write("Headers encontrados:", len(headers))

    # 2) Para los primeros N headers, mostramos: padre, contenido cercano y links
    for idx, li in enumerate(headers[:limit], start=1):
        st.markdown(f"### Header #{idx}")

        st.code(str(li)[:800])

        parent = li.parent
        st.write("Parent tag:", getattr(parent, "name", None))
        if parent:
            st.write("Parent preview:", parent.get_text(" ", strip=True)[:250])

        # Mostrar links cerca (por si hay onclick/url que trae detalle)
        links = []
        for a in li.find_all("a", href=True):
            links.append(a["href"])
        st.write("Links dentro del li:", links)

        # Mostrar atributos del li y de hijos (por si hay onclick)
        attrs = dict(li.attrs) if hasattr(li, "attrs") else {}
        st.write("LI attrs:", attrs)
def _find_anchor_container(soup: BeautifulSoup, anchor_id: str):
    """
    Encuentra el contenedor real de una sección por id/name,
    y si el nodo es muy pequeño sube hasta un contenedor útil.
    """
    # 1) id="articulos"
    node = soup.find(id=anchor_id)

    # 2) <a name="articulos">
    if node is None:
        node = soup.find("a", attrs={"name": anchor_id})

    if node is None:
        return None

    # Si el nodo es un <a name=...>, el contenido suele venir después
    # Intentamos tomar el siguiente contenedor grande
    if node.name == "a" and node.get("name") == anchor_id:
        nxt = node.find_next(["div", "table", "ul", "p"])
        if nxt is not None:
            node = nxt

    # Subir un poco para capturar todo el bloque de la sección
    container = node
    for _ in range(6):
        if not container.parent:
            break
        # Si el padre contiene el título "Artículos", nos quedamos con él
        parent_txt = container.parent.get_text(" ", strip=True)
        if "Artículos" in parent_txt and len(parent_txt) > 200:
            container = container.parent
            break
        container = container.parent

    return container


def extract_cvlac_section_by_anchor(html: str, anchor_id: str) -> str:
    """
    Devuelve HTML renderizable de una sección del CvLAC usando el anchor #id del menú.
    Ej: anchor_id="articulos", "eventos", "lineas_investigacion", etc.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    container = _find_anchor_container(soup, anchor_id)
    if container is None:
        return ""

    # Limpieza ligera
    for sc in container.select("script"):
        sc.decompose()
    for t in container.select("[onclick]"):
        del t["onclick"]

    # Fix imgs relativas /cvlac/...
    for img in container.select("img[src]"):
        src = img.get("src", "")
        if src.startswith("/"):
            img["src"] = BASE + src

    return f"""
    <div style="
        font-family: Arial, sans-serif;
        font-size: 14px;
        line-height: 1.35;
        padding: 12px 14px;
        border: 1px solid #e6e6e6;
        border-radius: 12px;
        background: #ffffff;
        max-width: 100%;
    ">
      {str(container)}
    </div>
    """


def render_cvlac_articulos_section(html: str) -> None:
    st.subheader("📚 CvLAC — Artículos")

    section_html = extract_cvlac_section_by_anchor(html, "articulos")

    if not section_html:
        st.warning("No pude ubicar la sección real 'Artículos' por anchor #articulos.")
        return

    components.html(section_html, height=900, scrolling=True)


    from urllib.parse import urlparse

def _safe_snippet(text: str, n: int = 700) -> str:
    text = text or ""
    text = text.replace("\x00", "")
    return text[:n]

def probe_url_format(session: requests.Session, url: str, referer: str | None = None, timeout: int = 25) -> dict:
    """
    Hace GET con requests (siguiendo redirects) y devuelve un resumen del formato/resultado:
    - status_code, final_url, content_type, encoding, size_bytes
    - si HTML: <title> y snippet
    - si JSON: keys / tipo
    """
    try:
        # algunos sitios (Scholar) se ponen delicados: mejor UA realista
        headers = _headers_basic(referer=referer)
        headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        # acepta json también por si hay endpoints API
        headers["Accept"] = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"

        r = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        ct = (r.headers.get("Content-Type") or "").lower()

        info = {
            "input_url": url,
            "final_url": r.url,
            "status_code": r.status_code,
            "content_type": ct.split(";")[0].strip() if ct else "",
            "encoding": r.encoding or "",
            "size_bytes": len(r.content or b""),
            "server": r.headers.get("Server", ""),
        }

        # HTML
        if "text/html" in ct or (r.text and "<html" in r.text.lower()):
            soup = BeautifulSoup(r.text or "", "html.parser")
            title = (soup.title.get_text(" ", strip=True) if soup.title else "")
            info["detected_format"] = "html"
            info["title"] = title
            info["snippet"] = _safe_snippet(soup.get_text("\n", strip=True), 900)
            return info

        # JSON
        if "application/json" in ct or (r.text and r.text.strip().startswith(("{", "["))):
            info["detected_format"] = "json"
            try:
                obj = r.json()
                info["json_type"] = type(obj).__name__
                if isinstance(obj, dict):
                    info["json_keys_sample"] = list(obj.keys())[:25]
                elif isinstance(obj, list):
                    info["json_list_len"] = len(obj)
            except Exception as e:
                info["json_parse_error"] = str(e)
                info["snippet"] = _safe_snippet(r.text, 900)
            return info

        # PDF / bin
        if "application/pdf" in ct:
            info["detected_format"] = "pdf"
            return info

        # otros binarios (imágenes, etc.)
        if ct.startswith("image/"):
            info["detected_format"] = "image"
            return info

        # texto plano u otros
        info["detected_format"] = "other"
        info["snippet"] = _safe_snippet(r.text, 900)
        return info

    except requests.RequestException as e:
        return {
            "input_url": url,
            "error": f"requests_error: {e}"
        }
    

def render_probe_external_links(ctx: Dict[str, Any], links: Dict[str, str]) -> None:
    """
    links: {"Google Scholar": "...", "ORCID": "...", ...}
    """
    st.subheader("🧪 Probe — URLs externas (requests)")

    session = ctx.get("session") if ctx else None
    if session is None:
        st.warning("No hay sesión activa (requests.Session).")
        return

    # Botón para correr probes
    if not st.button("Probar accesos con requests", use_container_width=True):
        return

    results = []
    for name, url in links.items():
        if not url:
            results.append({"name": name, "url": "", "status_code": None, "detected_format": "missing"})
            continue

        with st.spinner(f"Probando {name}..."):
            info = probe_url_format(session, url, referer=BASE)

        row = {
            "name": name,
            "url": url,
            "status_code": info.get("status_code"),
            "format": info.get("detected_format"),
            "content_type": info.get("content_type"),
            "final_url": info.get("final_url", ""),
            "size_bytes": info.get("size_bytes", ""),
            "title_or_keys": info.get("title") or info.get("json_keys_sample") or info.get("json_type") or "",
            "error": info.get("error", ""),
        }
        results.append(row)

        with st.expander(f"Detalle {name}"):
            st.json(info)

    st.dataframe(results, use_container_width=True)



ORCID_API_BASE = "https://pub.orcid.org/v3.0"

def normalize_orcid_id(orcid_input: str) -> str:
    """Acepta ORCID iD o URL y devuelve solo el id 0000-0000-0000-0000."""
    s = (orcid_input or "").strip()
    if not s:
        return ""
    # si llega URL
    if s.startswith("http"):
        p = urlparse(s)
        s = p.path.strip("/")

    # extraer patrón ORCID
    m = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", s)
    return m.group(1) if m else ""

def orcid_api_get(orcid_id: str, endpoint: str = "record") -> dict:
    """
    endpoint: 'record' o 'works'
    """
    oid = normalize_orcid_id(orcid_id)
    if not oid:
        raise ValueError("ORCID iD inválido.")

    url = f"{ORCID_API_BASE}/{oid}/{endpoint}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    return r.json()

def orcid_works_to_df(works_json: dict) -> pd.DataFrame:
    """
    Convierte /works JSON a DataFrame (título, año, tipo, DOI, url).
    Nota: ORCID entrega 'groups' -> 'work-summary' (puede haber varios).
    """
    rows = []
    groups = works_json.get("group", []) if isinstance(works_json, dict) else []

    for g in groups:
        summaries = g.get("work-summary", []) or []
        for w in summaries:
            title = (((w.get("title") or {}).get("title") or {}).get("value")) or ""
            wtype = w.get("type") or ""

            pub_date = w.get("publication-date") or {}
            year = ((pub_date.get("year") or {}).get("value")) or ""

            # external-ids (DOI)
            doi = ""
            url = (w.get("url") or {}).get("value") or ""
            ext = w.get("external-ids") or {}
            for eid in (ext.get("external-id") or []):
                if (eid.get("external-id-type") or "").lower() == "doi":
                    doi = (eid.get("external-id-value") or "").strip()
                    break

            rows.append({
                "title": title,
                "year": year,
                "type": wtype,
                "doi": doi,
                "url": url,
            })

    df = pd.DataFrame(rows)
    # limpiar vacíos y duplicados típicos por título+doi
    if not df.empty:
        df["title_norm"] = df["title"].fillna("").str.strip().str.lower()
        df["doi_norm"] = df["doi"].fillna("").str.strip().str.lower()
        df = df.drop_duplicates(subset=["doi_norm", "title_norm"], keep="first").drop(columns=["title_norm", "doi_norm"])
    return df
def render_orcid_connector(ctx: Dict[str, Any], fallback_orcid: str | None = None) -> None:
    st.subheader("🟢 ORCID — Conector (API)")

    payload = (ctx or {}).get("payload") or {}
    typed = payload.get("orcid_id") or ""
    default_orcid = normalize_orcid_id(typed) or normalize_orcid_id(fallback_orcid or "")

    orcid_id = st.text_input(
        "ORCID iD a consultar",
        value=default_orcid,
        placeholder="0000-0002-8656-8179"
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        run_works = st.button("Traer Works (publicaciones)", use_container_width=True)
    with col2:
        run_record = st.button("Traer Record (perfil completo)", use_container_width=True)

    if run_record:
        try:
            with st.spinner("Consultando ORCID /record ..."):
                data = orcid_api_get(orcid_id, "record")
            st.success("Record obtenido (JSON).")
            st.json(data)
        except Exception as e:
            st.error(f"No se pudo consultar ORCID record: {e}")

    if run_works:
        try:
            with st.spinner("Consultando ORCID /works ..."):
                works = orcid_api_get(orcid_id, "works")
            df = orcid_works_to_df(works)
            st.success(f"Works: {len(df)} items")
            st.dataframe(df, use_container_width=True)

            st.download_button(
                "⬇️ Descargar ORCID works (CSV)",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="orcid_works.csv",
                mime="text/csv",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"No se pudo consultar ORCID works: {e}")


# =========================
# CvLAC — Todos los integrantes
# =========================
def fetch_all_integrantes_cvlac(session: requests.Session) -> List[Dict[str, str]]:
    """
    Parsea la página de integrantes y devuelve una lista de:
      [{"nombre": ..., "cod_rh": ..., "cvlac_url": ...}, ...]
    Solo incluye filas que tengan link CvLAC.
    """
    html = fetch_integrantes_html(session)
    soup = BeautifulSoup(html, "html.parser")

    integrantes: List[Dict[str, str]] = []
    seen_cod: set = set()

    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        nombre = tds[0].get_text(" ", strip=True)

        cvlac_a = None
        for a in tr.select("a[href]"):
            if a.get_text(" ", strip=True).lower() == "cvlac":
                cvlac_a = a
                break
        if not cvlac_a:
            continue

        href = (cvlac_a.get("href") or "").strip()
        full = urljoin(BASE, href)
        qs = parse_qs(urlparse(full).query)
        cod_rh = (qs.get("cod_rh") or [""])[0]

        if not cod_rh or cod_rh in seen_cod:
            continue

        seen_cod.add(cod_rh)
        cvlac_url = CVLAC_URL_TEMPLATE.format(cod_rh=cod_rh)
        integrantes.append({"nombre": nombre, "cod_rh": cod_rh, "cvlac_url": cvlac_url})

    return integrantes


# =========================
# Extractor de secciones CvLAC por anchor
# =========================

import copy as _copy_module

# Mapa anchor_id → (título visible, emoji)
# Orden = orden en que aparecen en el HTML real del CvLAC
CVLAC_ANCHOR_MAP: List[tuple] = [
    ("articulos",           "Artículos",                               "📄"),
    ("capitulos",           "Capítulos de libro",                      "📖"),
    ("libros",              "Libros",                                   "📚"),
    ("otra_prod_biblio",    "Otra producción bibliográfica",            "📋"),
    ("trabajos_dirigi",     "Trabajos dirigidos/tutorías",              "🎓"),
    ("proyectos",           "Proyectos",                               "🔬"),
    ("evento",              "Eventos científicos",                     "🏛️"),
    ("edicion",             "Ediciones/revisiones",                    "✏️"),
    ("jurado",              "Jurado en comités de evaluación",         "⚖️"),
    ("comite",              "Participación en comités",                "📝"),
    ("par",                 "Par evaluador",                           "🔍"),
    ("formacion_acad",      "Formación académica",                     "🎒"),
    ("formacion_comp",      "Formación complementaria",                "📚"),
    ("experiencia",         "Experiencia profesional",                 "💼"),
    ("otra_info_personal",  "Áreas / Idiomas / Reconocimientos",       "👤"),
    ("div_ced",             "Publicaciones editoriales no especializadas", "📰"),
    ("re_co",               "Redes de conocimiento",                   "🌐"),
    ("patentes",            "Patentes",                                "📜"),
    ("software",            "Software",                                "💻"),
    ("tecnologicos",        "Productos tecnológicos",                  "⚙️"),
    ("otra_prod_tecnica",   "Otra producción técnica",                 "🔧"),
    ("demas_trabajos",      "Demás trabajos",                          "📂"),
]


def _clean_soup_tag(tag) -> str:
    """Deep-copy, elimina scripts/onclick, arregla imgs relativas."""
    tag = _copy_module.copy(tag)
    for sc in tag.select("script"):
        sc.decompose()
    for t in tag.select("[onclick]"):
        del t["onclick"]
    for img in tag.select("img[src]"):
        src = img.get("src", "")
        if src.startswith("/"):
            img["src"] = BASE + src
    return str(tag)


def _extract_items_from_table(table) -> List[str]:
    """
    Dado un <table> de sección del CvLAC, extrae ítems como pares
    (li-header + blockquote siguiente) o blockquotes sueltos.
    Devuelve lista de HTML strings, uno por ítem, deduplicados.
    """
    items: List[str] = []
    seen_keys: set = set()

    rows = table.find_all("tr")
    i = 0
    while i < len(rows):
        row = rows[i]
        tds = row.find_all("td")
        if not tds:
            i += 1
            continue

        cell_html = "".join(str(td) for td in tds)
        cell_text = row.get_text(" ", strip=True)

        # Caso A: fila con <li><b>Tipo...</b></li> seguida de fila con <blockquote>
        li_tags = row.find_all("li")
        has_header_li = any(
            li.find("b") and len(li.get_text(" ", strip=True)) > 5
            for li in li_tags
        )

        if has_header_li and i + 1 < len(rows):
            next_row = rows[i + 1]
            bq = next_row.find("blockquote")
            if bq:
                # Combinar li header + blockquote
                li_html = "".join(_clean_soup_tag(li) for li in li_tags)
                bq_html = _clean_soup_tag(bq)
                combined = f"<div>{li_html}{bq_html}</div>"
                key = bq.get_text(" ", strip=True)[:120]
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    items.append(combined)
                i += 2
                continue

        # Caso B: fila con solo blockquote (proyectos, experiencia, etc.)
        bq = row.find("blockquote")
        if bq and not has_header_li:
            key = bq.get_text(" ", strip=True)[:120]
            if key and key not in seen_keys:
                seen_keys.add(key)
                items.append(f"<div>{_clean_soup_tag(bq)}</div>")
            i += 1
            continue

        # Caso C: fila con <li> de contenido directo (formación, reconocimientos)
        for li in li_tags:
            txt = li.get_text(" ", strip=True)
            if len(txt) < 10:
                continue
            key = txt[:120]
            if key not in seen_keys:
                seen_keys.add(key)
                items.append(_clean_soup_tag(li))

        # Caso D: fila con <table> interna (eventos científicos)
        inner_tables = row.find_all("table")
        for it in inner_tables:
            txt = it.get_text(" ", strip=True)
            if len(txt) < 20:
                continue
            key = txt[:120]
            if key not in seen_keys:
                seen_keys.add(key)
                items.append(_clean_soup_tag(it))

        i += 1

    return items


def extract_cvlac_all_sections(html: str) -> List[Dict[str, Any]]:
    """
    Extrae secciones del CvLAC usando los anchors <a name="..."> reales.
    Devuelve lista de {"title", "emoji", "items": [html_str, ...]}.
    Solo incluye secciones con al menos un ítem.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    result: List[Dict[str, Any]] = []

    for (anchor_id, title, emoji) in CVLAC_ANCHOR_MAP:
        # Buscar anchor: <a name="anchor_id"> o id="anchor_id"
        anchor = soup.find("a", attrs={"name": anchor_id})
        if anchor is None:
            anchor = soup.find(id=anchor_id)
        if anchor is None:
            continue

        # El <table> de contenido es el primer <table> dentro del <td> que contiene el anchor,
        # o el siguiente <table> en el documento.
        container_td = anchor.find_parent("td")
        if container_td:
            table = container_td.find("table")
        else:
            # Buscar el siguiente <table> en el árbol
            table = anchor.find_next("table")

        if table is None:
            continue

        # Verificar que la tabla tiene contenido real (no solo anchor vacío)
        table_text = table.get_text(" ", strip=True)
        if len(table_text) < 20:
            continue

        items = _extract_items_from_table(table)

        # Para "proyectos" el anchor es un id dentro de <td id="proyectos">
        # que puede ser el <h3> contenedor, buscar la tabla padre si no hubo items
        if not items and anchor_id == "proyectos":
            h3 = soup.find("td", id="proyectos")
            if h3:
                parent_table = h3.find_parent("table")
                if parent_table:
                    items = _extract_items_from_table(parent_table)

        if items:
            result.append({
                "title": title,
                "emoji": emoji,
                "items": items,
            })

    return result



def _extract_year_from_item(item_html: str) -> Optional[int]:
    """Extrae el primer año (1950-2029) que aparezca en el texto de un ítem."""
    import re as _re
    text = BeautifulSoup(item_html, "html.parser").get_text(" ", strip=True)
    m = _re.search(r"\b(19[5-9]\d|20[0-2]\d)\b", text)
    return int(m.group(1)) if m else None


def _filter_sections_by_year(
    sections: List[Dict[str, Any]],
    year_min: int,
    year_max: int,
) -> List[Dict[str, Any]]:
    """
    Filtra los ítems de cada sección al rango [year_min, year_max].
    Ítems sin año detectable se INCLUYEN siempre (no los descartamos).
    Elimina secciones que queden vacías.
    """
    result = []
    for sec in sections:
        filtered_items = []
        for item_html in sec["items"]:
            yr = _extract_year_from_item(item_html)
            if yr is None or (year_min <= yr <= year_max):
                filtered_items.append(item_html)
        if filtered_items:
            result.append({**sec, "items": filtered_items})
    return result

def _build_cvlac_full_page_html(nombre: str, cvlac_url: str,
                                 sections: List[Dict[str, Any]]) -> str:
    """
    Construye un HTML completo con acordeones de dos niveles en JS puro:
      - Nivel 1: sección (Artículos, Proyectos, ...)  → dropdown grande
      - Nivel 2: cada ítem dentro de la sección       → dropdown pequeño
    """
    total_items = sum(len(s["items"]) for s in sections)

    if not sections:
        sections_html = "<p style='color:#888;padding:12px'>No se encontró contenido en este CvLAC.</p>"
    else:
        sec_blocks = []
        for si, sec in enumerate(sections):
            sid = f"sec_{si}"
            emoji = sec["emoji"]
            title = sec["title"]
            count = len(sec["items"])

            # Ítems dentro de la sección
            item_rows = []
            for ii, item_html in enumerate(sec["items"]):
                iid = f"{sid}_it_{ii}"
                preview_soup = BeautifulSoup(item_html, "html.parser")
                full_txt = preview_soup.get_text(" ", strip=True)
                # 1) Extraer título entre comillas
                import re as _re
                quoted = _re.search(r'["“”]([^"“”]{10,120})["“”]', full_txt)
                if quoted:
                    label = quoted.group(1).strip()
                else:
                    # 2) Texto del blockquote sin autores en mayúsculas al inicio
                    bq = preview_soup.find("blockquote")
                    raw = (bq or preview_soup).get_text(" ", strip=True)
                    raw = _re.sub(r'^([A-ZÁÉÍÓÚÑ\s,]+,\s*)+', '', raw).strip()
                    label = raw[:100] + ("…" if len(raw) > 100 else "")

                item_rows.append(f"""
                <div class="item-row">
                  <button class="item-header" onclick="tog('{iid}')">
                    <span class="item-num">#{ii+1}</span>
                    <span class="item-label">{label}</span>
                    <span class="item-arrow" id="ia_{iid}">▶</span>
                  </button>
                  <div class="item-body" id="{iid}">
                    {item_html}
                  </div>
                </div>""")

            sec_blocks.append(f"""
            <div class="sec-block">
              <button class="sec-header" onclick="tog('{sid}')">
                <span>{emoji} {title}</span>
                <span style="display:flex;align-items:center;gap:8px">
                  <span class="sec-badge">{count}</span>
                  <span class="sec-arrow" id="sa_{sid}">▶</span>
                </span>
              </button>
              <div class="sec-body" id="{sid}">
                {"".join(item_rows)}
              </div>
            </div>""")

        sections_html = "\n".join(sec_blocks)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:Arial,sans-serif;font-size:13px;line-height:1.5;
       background:#f4f6fb;padding:10px 12px 20px;color:#222}}

  /* ── Cabecera del integrante ── */
  .top-header{{display:flex;align-items:center;gap:10px;margin-bottom:14px;
              padding-bottom:10px;border-bottom:2px solid #3a7bd5}}
  .top-header h2{{font-size:15px;color:#1a4080;flex:1}}
  .top-header a{{font-size:11px;color:#3a7bd5;text-decoration:none;white-space:nowrap}}
  .top-header a:hover{{text-decoration:underline}}
  .top-badge{{background:#dbeafe;color:#1a4080;border-radius:12px;
              padding:2px 10px;font-size:12px;font-weight:700;white-space:nowrap}}

  /* ── Bloque de sección (nivel 1) ── */
  .sec-block{{border:1px solid #c7d4e8;border-radius:10px;margin-bottom:8px;
             overflow:hidden;background:#fff}}
  .sec-header{{width:100%;text-align:left;background:#e8eef8;border:none;
               padding:10px 16px;font-size:13.5px;font-weight:700;color:#1a4080;
               cursor:pointer;display:flex;justify-content:space-between;
               align-items:center;transition:background .15s}}
  .sec-header:hover{{background:#d4e0f5}}
  .sec-badge{{background:#3a7bd5;color:#fff;border-radius:10px;
              padding:1px 8px;font-size:11px;font-weight:700}}
  .sec-arrow{{font-size:11px;transition:transform .2s;color:#3a7bd5}}
  .sec-body{{display:none;padding:8px 10px 10px;border-top:1px solid #c7d4e8}}
  .sec-body.open{{display:block}}

  /* ── Ítem dentro de sección (nivel 2) ── */
  .item-row{{border:1px solid #e2e8f2;border-radius:7px;margin-bottom:5px;
             overflow:hidden;background:#fafbff}}
  .item-header{{width:100%;text-align:left;background:#f5f7fd;border:none;
                padding:7px 12px;font-size:12px;color:#2c4a7c;cursor:pointer;
                display:flex;align-items:center;gap:8px;transition:background .12s}}
  .item-header:hover{{background:#eaeffa}}
  .item-num{{background:#e0e9ff;color:#3a7bd5;border-radius:8px;
             padding:1px 6px;font-size:11px;font-weight:700;white-space:nowrap}}
  .item-label{{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
               font-size:12px;color:#333}}
  .item-arrow{{font-size:10px;transition:transform .18s;color:#888;flex-shrink:0}}
  .item-body{{display:none;padding:10px 14px 12px;border-top:1px solid #e2e8f2;
              font-size:12.5px;line-height:1.55}}
  .item-body.open{{display:block}}
  .item-body ul{{padding-left:18px;margin:4px 0}}
  .item-body li{{margin-bottom:4px}}
  .item-body b,.item-body strong{{color:#1a4080}}
</style>
</head>
<body>
<div class="top-header">
  <h2>🧑‍🔬 {nombre}</h2>
  <span class="top-badge">📦 {len(sections)} secciones · {total_items} ítems</span>
  <a href="{cvlac_url}" target="_blank">Ver CvLAC ↗</a>
</div>
{sections_html}
<script>
  function tog(id) {{
    var el  = document.getElementById(id);
    var isOpen = el.classList.toggle('open');
    // flecha de sección
    var sa = document.getElementById('sa_' + id);
    if (sa) sa.style.transform = isOpen ? 'rotate(90deg)' : '';
    // flecha de ítem
    var ia = document.getElementById('ia_' + id);
    if (ia) ia.style.transform = isOpen ? 'rotate(90deg)' : '';
    sendH();
  }}
  function sendH() {{
    var h = document.documentElement.scrollHeight;
    window.parent.postMessage({{type:'streamlit:setFrameHeight', height: h + 6}}, '*');
  }}
  window.addEventListener('load', sendH);
  setTimeout(sendH, 350);
</script>
</body>
</html>"""


def render_all_integrantes_cvlac(ctx: Dict[str, Any]) -> None:
    """
    Muestra TODAS las secciones del CvLAC de cada integrante del grupo,
    organizadas en acordeones de dos niveles (sección → ítem).
    Incluye slider de rango de años para filtrar publicaciones.
    Un solo st.expander por integrante (sin anidamiento Streamlit).
    """
    st.subheader("👥 CvLAC — Todos los integrantes")

    session = ctx.get("session") if ctx else None
    if session is None:
        st.warning("No hay sesión activa.")
        return

    # ── Botón de carga ──
    col1, col2 = st.columns([1, 2])
    with col1:
        run = st.button("Cargar CvLAC de todos los integrantes", use_container_width=True)
    with col2:
        st.caption("Extrae todas las secciones del CvLAC de cada integrante.")

    # ── Slider de rango de años (siempre visible tras el botón) ──
    import datetime as _dt
    current_year = _dt.datetime.now().year
    year_range = st.slider(
        "📅 Filtrar por rango de publicación",
        min_value=1950,
        max_value=current_year,
        value=(1990, current_year),
        step=1,
        help="Solo se muestran ítems cuyo año detectado esté dentro del rango. "
             "Ítems sin año identificable se muestran siempre.",
        key="cvlac_year_range",
    )
    year_min, year_max = year_range
    st.caption(
        f"Mostrando publicaciones de **{year_min}** a **{year_max}**. "
        "Ítems sin año siempre visibles."
    )

    if not run:
        return

    with st.spinner("Obteniendo lista de integrantes..."):
        try:
            integrantes = fetch_all_integrantes_cvlac(session)
        except Exception as e:
            st.error(f"No se pudo obtener la lista de integrantes: {e}")
            return

    if not integrantes:
        st.warning("No se encontraron integrantes con link CvLAC.")
        return

    st.success(f"Integrantes con CvLAC encontrados: {len(integrantes)}")

    for integrante in integrantes:
        nombre    = integrante["nombre"]
        cvlac_url = integrante["cvlac_url"]
        cod_rh    = integrante["cod_rh"]

        with st.expander(f"🧑‍🔬 {nombre}  (cod_rh: {cod_rh})", expanded=False):
            try:
                with st.spinner(f"Cargando CvLAC de {nombre}..."):
                    resp = fetch_cvlac_response(session, cvlac_url)
                html = resp.text or ""

                sections = extract_cvlac_all_sections(html)

                # ── Aplicar filtro de años ──
                sections_filtered = _filter_sections_by_year(sections, year_min, year_max)

                total_orig    = sum(len(s["items"]) for s in sections)
                total_filtered = sum(len(s["items"]) for s in sections_filtered)
                if total_orig != total_filtered:
                    st.caption(
                        f"🔎 Mostrando **{total_filtered}** de **{total_orig}** ítems "
                        f"({year_min}–{year_max})"
                    )

                page_html = _build_cvlac_full_page_html(nombre, cvlac_url, sections_filtered)

                # Altura: cabecera (60) + N secciones colapsadas (44px) + margen
                est_height = 80 + len(sections_filtered) * 44 + 40
                components.html(page_html, height=est_height, scrolling=True)

            except Exception as e:
                st.error(f"Error al cargar CvLAC de {nombre}: {e}")