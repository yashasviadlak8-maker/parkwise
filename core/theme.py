"""Look and feel: calm green background with grey road drawings, red for important things, colour-coded buttons."""
import urllib.parse
from pathlib import Path
import streamlit as st

_TILE = """<svg xmlns='http://www.w3.org/2000/svg' width='640' height='640' viewBox='0 0 640 640' fill='none' stroke='#6f8576' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round' opacity='0.30'>
<g transform='translate(30,60)'><path d='M0 40 L10 15 Q14 5 26 5 H64 Q76 5 82 15 L96 40 V55 H0Z'/><circle cx='24' cy='58' r='10'/><circle cx='72' cy='58' r='10'/><path d='M22 15 H42 V32 H14Z M48 15 H64 L74 32 H48Z'/></g>
<g transform='translate(420,30)'><rect width='46' height='110' rx='10'/><circle cx='23' cy='24' r='11'/><circle cx='23' cy='55' r='11'/><circle cx='23' cy='86' r='11'/><path d='M23 110 V150'/></g>
<g transform='translate(470,330)'><polygon points='28,0 62,0 90,28 90,62 62,90 28,90 0,62 0,28'/><path d='M22 38 H38 M30 38 V60 M46 38 H62 M54 38 V60 M70 38 H78'/></g>
<g transform='translate(60,330)'><circle cx='42' cy='42' r='42'/><path d='M22 42 H58 M46 26 L62 42 L46 58'/></g>
<g transform='translate(250,200)'><path d='M0 40 L8 12 Q12 4 22 4 H70 Q80 4 86 14 L100 40 V54 H0Z'/><circle cx='22' cy='58' r='10'/><circle cx='78' cy='58' r='10'/></g>
<g transform='translate(520,480)'><circle cx='14' cy='40' r='14'/><circle cx='70' cy='40' r='14'/><path d='M14 40 L34 10 H54 L70 40 M34 10 L44 40 H14 M28 4 H42'/></g>
<path d='M0 590 H640' stroke-dasharray='28 22'/><path d='M0 610 H640'/><path d='M0 560 H640'/>
<path d='M230 430 V640' stroke-dasharray='20 16'/><path d='M200 430 V640 M260 430 V640'/>
</svg>"""
_BG = "data:image/svg+xml;utf8," + urllib.parse.quote(_TILE)

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@500;700&family=Nunito:wght@400;600;800&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap');
html, body, .stApp, p, label, input, select, textarea, div.stMarkdown { font-family: 'Nunito', sans-serif; }
/* Protect Streamlit Material Icons from font-family override without affecting text */
[data-testid*="Icon"], [data-testid="stIconMaterial"], [class*="material-symbols"], [class*="material-icons"], [data-testid="stSidebarCollapseButton"] span, [data-testid="stExpanderToggleIcon"] {
    font-family: 'Material Symbols Rounded', 'Material Icons' !important;
}
details[data-testid="stExpander"] summary p, details[data-testid="stExpander"] summary span:last-child {
    font-family: 'Nunito', sans-serif !important;
    letter-spacing: normal !important;
}
h1, h2, h3, .pw-word { font-family: 'Fredoka', sans-serif !important; letter-spacing: .3px; }
.stApp { background-color: #cfe3d3; background-image: url("BG"); background-size: 640px 640px; }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: #b9d4be; }
.block-container { background: rgba(247,251,247,.88); border-radius: 20px; padding: 1.4rem 2.2rem 2rem; margin-top: 1rem; box-shadow: 0 6px 24px rgba(40,70,50,.15); }
h1 { color: #1f4d33; display: inline-block; padding-bottom: 2px; }
h2, h3 { color: #2b5f42; }
/* tabs */
button[data-baseweb="tab"] { font-family: 'Fredoka', sans-serif; font-size: 1.02rem; color: #3d6a4f; }
button[data-baseweb="tab"][aria-selected="true"] { color: #D62828; }
[data-baseweb="tab-highlight"] { background-color: #D62828 !important; height: 3px; }
/* buttons: colour = action */
.stButton button, [data-testid="stFormSubmitButton"] button { color: #fff !important; border: 0; border-radius: 12px; font-family: 'Fredoka', sans-serif; font-size: 1rem; padding: .45rem 1.3rem; box-shadow: 0 3px 0 rgba(0,0,0,.2); transition: transform .08s, filter .15s; }
.stButton button:hover, [data-testid="stFormSubmitButton"] button:hover { filter: brightness(1.1); transform: translateY(-1px); }
.stButton button:active, [data-testid="stFormSubmitButton"] button:active { transform: translateY(2px); box-shadow: none; }
.stButton button { background: #7b4fd1; }                                              /* search / record: purple */
[data-testid="stFormSubmitButton"] button { background: #0e9aa7; }                      /* add / register / book: teal */
[class*="st-key-"][class*="_u_btn"] button { background: #f08a00; }                    /* update: orange */
[class*="st-key-"][class*="_d_btn"] button { background: #D62828; }                     /* delete: red (important) */
[class*="st-key-"][class*="_d_btn"] button:disabled { background: #e3a3a3; }
/* red = important */
[data-testid="stAlert"] { border-radius: 12px; }
div[data-testid="stAlertContainer"] { border-left: 6px solid #D62828; }
[data-testid="stColumn"]:last-child [data-testid="stMetricValue"] { color: #D62828; }
[data-testid="stMetricValue"] { font-family: 'Fredoka', sans-serif; color: #1f4d33; }
.pw-brand { display: flex; align-items: center; gap: 14px; }
.pw-word { font-size: 2.4rem; font-weight: 700; color: #1f4d33; line-height: 1; }
.pw-word b { color: #D62828; }
.pw-tag { color: #4d6b58; font-size: .95rem; margin-top: 2px; }
</style>
""".replace("BG", _BG)

_LOGO = """<svg width="62" height="62" viewBox="0 0 62 62" xmlns="http://www.w3.org/2000/svg">
<rect width="62" height="62" rx="16" fill="#1f4d33"/><rect x="4" y="4" width="54" height="54" rx="12" fill="none" stroke="#9fd1ad" stroke-width="2"/>
<text x="31" y="45" text-anchor="middle" font-family="Fredoka,Arial" font-weight="700" font-size="40" fill="#fff">P</text>
<circle cx="49" cy="13" r="5" fill="#D62828"/><circle cx="49" cy="27" r="5" fill="#2e9e4f"/></svg>"""


def header(tagline="Smart city parking and reservation system"):
    st.markdown(_CSS, unsafe_allow_html=True)
    left, right = st.columns([1, 1.4])
    left.markdown(f'<div class="pw-brand">{_LOGO}<div><div class="pw-word">Park<b>Wise</b></div>'
                  f'<div class="pw-tag">{tagline}</div></div></div>', unsafe_allow_html=True)
    right.image(str(Path(__file__).parent.parent / "assets" / "banner.gif"), width=440)
