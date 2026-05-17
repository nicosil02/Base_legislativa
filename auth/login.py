"""Magic link auth flow: render login UI + send magic email + handle callback.

Persistencia: cookie `vi_session` con un token firmado de 30 dias. El cookie
sobrevive cierre de pestana y hard-navigations (como los <a href> de las
country cards). Sin esto, cada hard-nav perdia el session_state y el usuario
caia en un loop de login.
"""
from __future__ import annotations

import base64
import os
import re
import time
import urllib.parse
from pathlib import Path

import streamlit as st

from auth.store import is_registered, register
from auth.tokens import sign_token, verify_token


ALLOWED_DOMAIN = "@valiconsultores.com"
EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

# Token firmado de sesion (cookie): TTL 30 dias.
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
COOKIE_NAME = "vi_session"


def _get_cookie_controller():
    """Devuelve un CookieController cacheado en session_state."""
    if "_cookie_ctrl" not in st.session_state:
        try:
            from streamlit_cookies_controller import CookieController
            st.session_state["_cookie_ctrl"] = CookieController(key="vi_cookies")
        except Exception as e:
            print("[auth] no pude instanciar CookieController: " + str(e))
            st.session_state["_cookie_ctrl"] = None
    return st.session_state["_cookie_ctrl"]


def _save_session_cookie(email):
    ctrl = _get_cookie_controller()
    if ctrl is None:
        return
    try:
        long_token = sign_token(email, ttl_seconds=SESSION_TTL_SECONDS)
        # max_age en segundos; el component lo traduce a una Max-Age cookie attr.
        ctrl.set(COOKIE_NAME, long_token, max_age=SESSION_TTL_SECONDS)
    except Exception as e:
        print("[auth] error guardando cookie: " + str(e))


def _clear_session_cookie():
    ctrl = _get_cookie_controller()
    if ctrl is None:
        return
    try:
        ctrl.remove(COOKIE_NAME)
    except Exception:
        pass


def _restore_session_from_cookie():
    """Lee cookie + setea session_state.

    streamlit-cookies-controller monta un component JS que lee cookies
    asincrono — la primera vez que llamamos .get(), puede devolver None
    porque el JS aun no terminó. Si pasa eso, hacemos UN rerun para darle
    chance al JS, y al volver la cookie estará leida.
    """
    if st.session_state.get("user_email"):
        return True
    ctrl = _get_cookie_controller()
    if ctrl is None:
        return False
    try:
        token = ctrl.get(COOKIE_NAME)
    except Exception:
        token = None
    if not token:
        # Patron oficial de streamlit-cookies-controller: rerun una vez
        # despues del primer mount para que el JS lea las cookies.
        if not st.session_state.get("_cookie_read_attempted"):
            st.session_state["_cookie_read_attempted"] = True
            time.sleep(0.25)
            st.rerun()
        return False
    payload = verify_token(token)
    if not payload:
        return False
    st.session_state["user_email"] = payload["email"]
    # Limpia el flag para que en futuras reauths funcione
    st.session_state.pop("_cookie_read_attempted", None)
    return True


def _app_base_url():
    return os.environ.get("APP_BASE_URL", "http://localhost:8501").rstrip("/")


def _send_magic_email(email, token):
    """Manda el magic link via Resend."""
    from alerts.send import send_email

    link = _app_base_url() + "/?token=" + urllib.parse.quote(token)
    subject = "Vali Intelligence - link de acceso"
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:0;background:#F4F6F8;'
        "font-family:Inter,Segoe UI,Arial,sans-serif;\">"
        '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="background:#F4F6F8;"><tr><td align="center" style="padding:40px 0;">'
        '<table cellpadding="0" cellspacing="0" border="0" width="520" '
        'style="background:#FFFFFF;border-radius:14px;border:1px solid #CFD9E0;'
        'padding:36px;"><tr><td>'
        '<div style="display:inline-block;padding:6px 14px;background:#0A294D;'
        'color:#FFFFFF;border-radius:6px;font-size:14px;font-weight:700;">'
        'Vali Intelligence</div>'
        '<h1 style="font-size:22px;margin:24px 0 12px 0;color:#0A294D;'
        'font-weight:800;letter-spacing:-0.02em;">Link de acceso</h1>'
        '<p style="font-size:14px;color:#435D74;line-height:1.55;">'
        "Hace click en el siguiente boton para iniciar sesion. "
        "El link es valido por 15 minutos.</p>"
        '<p style="margin:28px 0;"><a href="' + link + '" '
        'style="display:inline-block;background:#0A294D;color:#FFFFFF;'
        'text-decoration:none;padding:12px 24px;border-radius:8px;'
        'font-weight:700;font-size:14px;">Iniciar sesion &rarr;</a></p>'
        '<p style="font-size:12px;color:#869FB2;line-height:1.5;">'
        "Si el boton no funciona, copia esta URL:<br>"
        '<span style="color:#0A294D;font-family:monospace;">' + link + '</span></p>'
        '<p style="font-size:12px;color:#869FB2;margin-top:32px;">'
        "Si no pediste este link, ignora este mail.</p>"
        "</td></tr></table></td></tr></table></body></html>"
    )
    send_email(subject, html, recipient=email)


def _handle_token_in_url():
    """Si la URL tiene ?token=..., verificarlo y setear la sesion."""
    params = st.query_params
    token = params.get("token")
    if not token:
        return False
    payload = verify_token(token)
    if not payload:
        st.error("Link invalido o vencido. Pedi uno nuevo.")
        return False
    email = payload["email"]
    if email.endswith(ALLOWED_DOMAIN):
        try:
            register(email)
        except Exception as e:
            st.warning("No pude persistir el registro: " + str(e)[:200])
    elif not is_registered(email):
        st.error("Tu email no esta autorizado.")
        return False
    st.session_state["user_email"] = email
    _save_session_cookie(email)
    try:
        st.query_params.clear()
    except Exception:
        pass
    return True


def _render_login_styles():
    st.markdown(
        """<style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
        .stApp { background-color: #F4F6F8 !important; }
        section[data-testid="stSidebar"] { display: none !important; }
        [data-testid="stHeader"] { background: transparent !important; }
        [data-testid="stToolbar"] { display: none !important; }
        .block-container {
            max-width: 480px !important;
            padding-top: 8vh !important;
            font-family: 'Inter', sans-serif !important;
        }
        /* Estilo del st.container(border=True) — actua como card */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #FFFFFF !important;
            border: 1px solid #CFD9E0 !important;
            border-radius: 16px !important;
            padding: 40px 36px !important;
            margin-top: 24px !important;
        }
        .vi-eyebrow {
            font-size: 11px; font-weight: 800; letter-spacing: 0.28em;
            text-transform: uppercase; color: #0A294D; margin-bottom: 8px;
        }
        .vi-title {
            font-size: 2.2rem; font-weight: 900; letter-spacing: -0.03em;
            color: #0A294D; line-height: 1; margin: 0 0 12px 0;
        }
        .vi-sub {
            font-size: 14px; color: #435D74; line-height: 1.55;
            margin-bottom: 24px;
        }
        .vi-footer {
            text-align: center; font-size: 10px; font-weight: 700;
            letter-spacing: 0.22em; text-transform: uppercase;
            color: #869FB2; margin-top: 32px;
        }
        div[data-testid="stForm"] {
            background: transparent !important; border: 0 !important;
            padding: 0 !important;
        }
        div[data-testid="stTextInput"] input {
            border: 1px solid #CFD9E0 !important; border-radius: 10px !important;
            padding: 12px 14px !important; font-size: 14px !important;
            color: #0A294D !important;
        }
        div[data-testid="stTextInput"] input:focus {
            border-color: #0A294D !important;
            box-shadow: 0 0 0 3px rgba(10,41,77,0.08) !important;
        }
        div[data-testid="stFormSubmitButton"] button {
            background: #0A294D !important; color: #FFFFFF !important;
            border: 0 !important; padding: 12px 24px !important;
            border-radius: 10px !important; font-weight: 700 !important;
            font-size: 14px !important; width: 100% !important;
        }
        div[data-testid="stFormSubmitButton"] button:hover {
            background: #14406F !important;
        }
        </style>""",
        unsafe_allow_html=True,
    )


def _render_logo():
    logo_path = Path(__file__).resolve().parent.parent / "assets" / "vali_logo.jpg"
    if not logo_path.exists():
        logo_path = logo_path.with_suffix(".svg")
    if logo_path.exists():
        try:
            mime = "image/jpeg" if logo_path.suffix.lower() in (".jpg", ".jpeg") else "image/svg+xml"
            b64 = base64.b64encode(logo_path.read_bytes()).decode()
            st.markdown(
                '<div style="text-align:center;margin-bottom:8px;">'
                + '<img src="data:' + mime + ';base64,' + b64 + '" '
                + 'style="width:88px;height:88px;border-radius:14px;" /></div>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass


def render_login_page():
    _render_login_styles()
    _render_logo()
    st.markdown(
        '<div style="text-align:center;">'
        '<div class="vi-eyebrow">Asuntos Publicos &middot; Vali Consultores</div>'
        '<h1 class="vi-title">Vali Intelligence</h1>'
        '</div>',
        unsafe_allow_html=True,
    )

    # st.container con borde = card real (los widgets sí viven dentro).
    # `<div class="vi-card">` por markdown NO funciona porque Streamlit
    # renderea cada widget en su propio container y la card queda vacia.
    with st.container(border=True):
        sent = st.session_state.get("magic_sent_to")
        if sent:
            st.markdown(
                '<div class="vi-eyebrow">Link enviado</div>'
                '<p class="vi-sub">Te mandamos un link de acceso a '
                '<strong>' + sent + '</strong>. Revisa tu inbox (y spam) y '
                'haz click en el boton. El link es valido por 15 minutos.</p>',
                unsafe_allow_html=True,
            )
            if st.button("Usar otro email", type="secondary",
                         use_container_width=True):
                del st.session_state["magic_sent_to"]
                st.rerun()
        else:
            st.markdown(
                '<div class="vi-eyebrow">Iniciar sesion / registrarse</div>'
                '<p class="vi-sub">Ingresa tu correo corporativo '
                '<strong>@valiconsultores.com</strong>. Te vamos a mandar un '
                'link para acceder sin password.</p>',
                unsafe_allow_html=True,
            )
            with st.form("login_form", clear_on_submit=False, border=False):
                email = st.text_input(
                    "Email",
                    placeholder="nombre.apellido@valiconsultores.com",
                    label_visibility="collapsed",
                )
                submitted = st.form_submit_button(
                    "Enviar link de acceso", use_container_width=True
                )
                if submitted:
                    email = (email or "").strip().lower()
                    if not EMAIL_RE.match(email):
                        st.error("Email invalido.")
                    elif not email.endswith(ALLOWED_DOMAIN):
                        st.error("Solo emails @valiconsultores.com pueden acceder.")
                    else:
                        token = sign_token(email)
                        try:
                            _send_magic_email(email, token)
                            st.session_state["magic_sent_to"] = email
                            st.rerun()
                        except Exception as e:
                            st.error("Error mandando el link: " + str(e)[:200])

    st.markdown(
        '<div class="vi-footer">Vali Intelligence &middot; '
        'Asuntos Publicos y de Gobierno</div>',
        unsafe_allow_html=True,
    )


def is_authenticated():
    return bool(st.session_state.get("user_email"))


def current_user():
    return st.session_state.get("user_email")


def logout():
    _clear_session_cookie()
    for k in ("user_email", "magic_sent_to"):
        st.session_state.pop(k, None)


def gate_or_render():
    """Devuelve True si el usuario esta autenticado. Sino, renderea login.

    Orden de chequeo:
      1. ?token=... en URL (magic link recien clickeado) → setea sesion + cookie
      2. Cookie persistente vi_session (login previo dentro de los 30 dias)
      3. Si nada, renderea login y devuelve False
    """
    _handle_token_in_url()
    if is_authenticated():
        return True
    if _restore_session_from_cookie():
        return True
    render_login_page()
    return False
