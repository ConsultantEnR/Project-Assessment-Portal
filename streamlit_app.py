"""
Project Assessment Portal — Hub Streamlit
==========================================
Hub analytique Dolfines SA : supervision du portefeuille de projets ENR,
calculs financiers Python, rapports et synchronisation des données.

Lancement local : streamlit run streamlit_app.py
Hébergement     : Streamlit Community Cloud (share.streamlit.io)
"""

import streamlit as st
import streamlit.components.v1 as components
import json
import os
import math
from datetime import datetime, date
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import github_sync

# ─── Config page ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Project Assessment Portal — Dolfines",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Constantes ───────────────────────────────────────────────────────────────
DATA_FILE       = "data/projects.json"
GITHUB_PAGES_URL = "https://consultantenr.github.io/Project-Assessment-Portal"
REPO_NAME       = "ConsultantEnR/Project-Assessment-Portal"

# Couleurs Dolfines
ACCENT   = "#1863DC"
SUCCESS  = "#2E9E6E"
WARNING  = "#EF9F27"
DANGER   = "#D94F4F"
BG_LIGHT = "#F7F6F3"

# ─── CSS personnalisé ─────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Teko:wght@400;500;600&family=Montserrat:wght@300;400;500;600&family=Poppins:wght@300;400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'Montserrat', sans-serif; }
    h1, h2, h3 { font-family: 'Teko', sans-serif; letter-spacing: 0.5px; }

    .kpi-card {
        background: white;
        border: 1px solid #E2E0DB;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 8px;
    }
    .kpi-label { font-size: 11px; font-weight: 600; color: #A5A09A; text-transform: uppercase; letter-spacing: 0.08em; font-family: 'Poppins', sans-serif; }
    .kpi-value { font-family: 'Teko', sans-serif; font-size: 32px; font-weight: 500; color: #1A1A1A; line-height: 1.1; }
    .kpi-value.positive { color: #2E9E6E; }
    .kpi-value.accent   { color: #1863DC; }
    .kpi-value.warning  { color: #EF9F27; }

    .section-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 600;
        font-family: 'Poppins', sans-serif;
    }

    .stButton > button {
        font-family: 'Montserrat', sans-serif;
        font-weight: 600;
        border-radius: 8px;
    }

    [data-testid="stSidebar"] {
        background: #0E1520;
    }
    [data-testid="stSidebar"] .stMarkdown p,
    [data-testid="stSidebar"] .stMarkdown h1,
    [data-testid="stSidebar"] .stMarkdown h2,
    [data-testid="stSidebar"] label { color: #B8C4D8 !important; }
    [data-testid="stSidebar"] .stRadio label { color: #B8C4D8 !important; }
</style>
""", unsafe_allow_html=True)


# ─── Chargement / sauvegarde données ──────────────────────────────────────────
@st.cache_data(ttl=30)
def load_projects() -> list:
    """Charge les projets depuis data/projects.json."""
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return raw.get("projects", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_projects(projects: list):
    """Sauvegarde les projets dans data/projects.json."""
    os.makedirs("data", exist_ok=True)
    payload = {"projects": projects, "lastSync": datetime.utcnow().isoformat()}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    st.cache_data.clear()


def get_github_token() -> str | None:
    """Récupère le token GitHub depuis les secrets Streamlit."""
    try:
        return st.secrets.get("GITHUB_TOKEN")
    except Exception:
        return None


def import_from_localstorage_json(raw_json: str) -> list:
    """Parse le JSON exporté depuis localStorage du navigateur."""
    try:
        data = json.loads(raw_json)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "projects" in data:
            return data["projects"]
    except Exception:
        pass
    return []


# ─── Modèle financier Python ──────────────────────────────────────────────────
MONTHLY_FACTORS = [0.52, 0.63, 0.86, 1.00, 1.15, 1.26, 1.30, 1.22, 1.02, 0.78, 0.57, 0.49]
_sum = sum(MONTHLY_FACTORS)
MONTHLY_FACTORS = [v / _sum * 12 for v in MONTHLY_FACTORS]
MONTH_NAMES = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]


def pmt(rate: float, n_per: int, pv: float) -> float:
    if rate == 0:
        return pv / n_per
    return pv * rate / (1 - (1 + rate) ** (-n_per))


def npv_calc(rate: float, cashflows: list) -> float:
    return sum(cf / (1 + rate) ** (i + 1) for i, cf in enumerate(cashflows))


def irr_calc(cashflows: list, guess: float = 0.10) -> float | None:
    r = guess
    for _ in range(300):
        f  = sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))
        df = sum(-t * cf / (1 + r) ** (t + 1) for t, cf in enumerate(cashflows))
        if abs(df) < 1e-14:
            break
        r_new = r - f / df
        if abs(r_new - r) < 1e-9:
            return r_new
        r = r_new
    # Bisection fallback
    lo, hi = -0.99, 5.0
    f_lo = sum(cf / (1 + lo) ** t for t, cf in enumerate(cashflows))
    for _ in range(100):
        mid = (lo + hi) / 2
        f_mid = sum(cf / (1 + mid) ** t for t, cf in enumerate(cashflows))
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, hi = mid, hi
            f_lo = f_mid
    return None


def compute_site_financials(site: dict, params: dict) -> dict:
    """Calcule le P&L annuel, les cashflows mensuels et les KPIs d'un site."""
    defaults = {
        "electricityPrice": 85, "electricityEscalation": 1.5,
        "bessSpreadPrice": 30,  "inflation": 2.0, "tax": 25.0,
        "wacc": 8.0, "debtPercent": 70, "seniorRate": 4.5,
        "debtDuration": 18, "dsraMonths": 6, "dscrTarget": 1.15,
    }
    p = {**defaults, **params}

    pv_cap   = site.get("pvCapacity", 0)
    prod_p90 = site.get("pvProdP90", 1300)
    degrad   = site.get("pvDegradation", 0.5) / 100
    lifetime = site.get("pvLifetime", 25)
    has_bess = site.get("hasBESS", False) and (site.get("bessCapacity", 0) > 0)

    bess_cap    = site.get("bessCapacity", 0)
    bess_pow    = site.get("bessPower", 0)
    bess_cycles = site.get("bessCyclesPerDay", 1)
    eff_disch   = site.get("bessEffDCAC", 95) / 100
    bess_degrad = site.get("bessDegradation", 2.0) / 100
    bess_min_soh= site.get("bessMinSoH", 80) / 100

    # OPEX base
    opex_base = (
        site.get("omPv",   12) * pv_cap +
        site.get("insPv",   5) * pv_cap +
        site.get("amPv",    3) * pv_cap +
        site.get("rmPv",    2) * pv_cap +
        (site.get("omBess",   8) * bess_pow if has_bess else 0) +
        (site.get("insBess",  3) * bess_pow if has_bess else 0) +
        (site.get("amBess",   2) * bess_pow if has_bess else 0) +
        (site.get("rmBess",   2) * bess_pow if has_bess else 0) +
        site.get("rentEuros", 0)
    )

    capex_pv   = site.get("capexPv",   pv_cap * 700)
    capex_bess = site.get("capexBess", bess_pow * 400) if has_bess else 0
    total_capex = capex_pv + capex_bess

    debt        = total_capex * p["debtPercent"] / 100
    equity      = total_capex - debt
    monthly_r   = p["seniorRate"] / 100 / 12
    debt_months = int(p["debtDuration"] * 12)
    monthly_pmt = pmt(monthly_r, debt_months, debt) if debt > 0 else 0
    ann_debt_svc = monthly_pmt * 12

    annual, monthly_cf = [], []
    debt_remaining = debt

    for y in range(1, lifetime + 1):
        deg_f    = (1 - degrad) ** (y - 1)
        ann_prod = pv_cap * prod_p90 * deg_f

        bess_soh = max(bess_min_soh, (1 - bess_degrad) ** (y - 1)) if has_bess else 0
        bess_disch = bess_cap * bess_soh * eff_disch * bess_cycles * 365 if has_bess else 0

        elec_p = p["electricityPrice"] * (1 + p["electricityEscalation"] / 100) ** (y - 1)
        bess_sp = p["bessSpreadPrice"] * (1 + p["electricityEscalation"] / 100) ** (y - 1)

        pv_rev   = ann_prod * elec_p / 1000
        bess_rev = bess_disch * bess_sp / 1000 if has_bess else 0
        total_rev = pv_rev + bess_rev

        infl_f   = (1 + p["inflation"] / 100) ** (y - 1)
        total_opex = opex_base * infl_f

        ebitda = total_rev - total_opex
        deprec = total_capex / lifetime
        ebit   = ebitda - deprec

        ann_interest = min(debt_remaining * (p["seniorRate"] / 100), ann_debt_svc) if debt_remaining > 0 else 0
        ebt      = ebit - ann_interest
        tax_amt  = max(0, ebt) * p["tax"] / 100
        net_inc  = ebt - tax_amt
        cfads    = ebitda - tax_amt
        svc_y    = ann_debt_svc if y <= p["debtDuration"] else 0
        principal = max(0, svc_y - ann_interest)
        if y <= p["debtDuration"]:
            debt_remaining = max(0, debt_remaining - principal)

        dscr = cfads / svc_y if svc_y > 0 else None

        annual.append({
            "year": y,
            "production_kwh": round(ann_prod),
            "revenue_eur":    round(total_rev),
            "opex_eur":       round(total_opex),
            "ebitda_eur":     round(ebitda),
            "depreciation":   round(deprec),
            "ebit_eur":       round(ebit),
            "financial_charge": round(ann_interest),
            "ebt_eur":        round(ebt),
            "tax_eur":        round(tax_amt),
            "net_income_eur": round(net_inc),
            "cfads_eur":      round(cfads),
            "debt_service":   round(svc_y),
            "dscr":           round(dscr, 3) if dscr else None,
            "fcf_project":    round(cfads),
            "fcf_equity":     round(cfads - svc_y),
            "debt_remaining": round(debt_remaining),
        })

        for m in range(12):
            mf = MONTHLY_FACTORS[m]
            m_rev   = total_rev  * mf / 12
            m_opex  = total_opex / 12
            m_ebitda= m_rev - m_opex
            m_tax   = tax_amt / 12
            m_cfads = m_ebitda - m_tax
            m_svc   = monthly_pmt if y <= p["debtDuration"] else 0
            monthly_cf.append({
                "year": y, "month": m + 1,
                "period": (y - 1) * 12 + m + 1,
                "month_name": MONTH_NAMES[m],
                "revenue":  round(m_rev),
                "opex":     round(m_opex),
                "ebitda":   round(m_ebitda),
                "cfads":    round(m_cfads),
                "debt_svc": round(m_svc),
                "fcf":      round(m_cfads - m_svc),
            })

    project_cfs = [-total_capex] + [a["cfads_eur"] for a in annual]
    equity_cfs  = [-equity]      + [a["fcf_equity"] for a in annual]
    proj_irr = irr_calc(project_cfs)
    eq_irr   = irr_calc(equity_cfs)
    van      = -total_capex + npv_calc(p["wacc"] / 100, [a["cfads_eur"] for a in annual])

    dscr_vals = [a["dscr"] for a in annual if a["dscr"] is not None]

    return {
        "annual":    annual,
        "monthly":   monthly_cf,
        "kpis": {
            "project_irr": round(proj_irr * 100, 2) if proj_irr else None,
            "equity_irr":  round(eq_irr  * 100, 2) if eq_irr  else None,
            "van":         round(van),
            "dscr_min":    round(min(dscr_vals), 3) if dscr_vals else None,
            "dscr_avg":    round(sum(dscr_vals) / len(dscr_vals), 3) if dscr_vals else None,
            "total_capex": total_capex,
            "debt":        debt,
            "equity":      equity,
            "revenue_y1":  annual[0]["revenue_eur"] if annual else 0,
            "ebitda_y1":   annual[0]["ebitda_eur"]  if annual else 0,
        },
        "params": {**p, "total_capex": total_capex, "debt": debt, "equity": equity},
    }


# ─── Formatage ────────────────────────────────────────────────────────────────
def fmt_eur(val: float) -> str:
    if val is None: return "—"
    if abs(val) >= 1e6:
        return f"{val/1e6:.2f} M€"
    if abs(val) >= 1e3:
        return f"{val/1e3:.1f} k€"
    return f"{val:.0f} €"


def fmt_pct(val: float) -> str:
    return "—" if val is None else f"{val:.2f} %"


def kpi_card(label: str, value: str, css_class: str = "") -> str:
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value {css_class}">{value}</div>
    </div>"""


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding: 8px 0 16px;">
        <img src="https://raw.githubusercontent.com/ConsultantEnR/Project-Assessment-Portal/main/Banque%%20d%%27images/DOL-COG-IV-020-A%%20-Logo%%20final%%20Groupe%%20Dolfines%%20FR%%20transp.png"
             style="height:44px; filter:brightness(0) invert(1); opacity:0.92;">
    </div>
    <hr style="border-color:rgba(255,255,255,0.08); margin:0 0 12px;">
    """, unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        ["🏠 Portefeuille", "📊 Analyse site", "🔧 Outils HTML",
         "📁 Gestion projets", "💾 Import / Export", "⚙️ Paramètres"],
        label_visibility="collapsed",
    )

    st.markdown("""
    <hr style="border-color:rgba(255,255,255,0.08); margin:16px 0 12px;">
    <div style="font-size:11px; color:rgba(255,255,255,0.3); font-family:'Poppins',sans-serif;">
        v1.0 — Dolfines SA<br>Project Assessment Portal
    </div>
    """, unsafe_allow_html=True)

    # Lien vers l'app HTML
    st.markdown(f"""
    <div style="margin-top:12px;">
        <a href="{GITHUB_PAGES_URL}" target="_blank"
           style="display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
                  color:#B8D4FF;font-family:'Poppins',sans-serif;text-decoration:none;
                  padding:8px 12px;background:rgba(24,99,220,0.2);border-radius:8px;">
           🔗 Ouvrir l'app complète
        </a>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : PORTEFEUILLE
# ═══════════════════════════════════════════════════════════════════════════════
if page == "🏠 Portefeuille":
    st.markdown("# Portefeuille de projets")
    st.markdown("---")

    projects = load_projects()

    if not projects:
        st.info("Aucun projet chargé. Importez vos données depuis l'onglet **Import / Export**.")
        st.markdown(f"""
        <div style="background:white;border:1px solid #E2E0DB;border-radius:12px;padding:24px;margin-top:16px;">
            <h3 style="font-family:'Teko',sans-serif;margin:0 0 8px;">Démarrer</h3>
            <p style="font-size:13px;color:#7A7670;">
                1. Créez vos projets depuis <a href="{GITHUB_PAGES_URL}/creer_projet.html" target="_blank">l'application</a><br>
                2. Exportez les données (onglet Import / Export)<br>
                3. Rechargez cette page pour afficher le portefeuille
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # KPIs globaux
        total_sites = sum(len(p.get("sites", [])) for p in projects)
        total_pv_mwc = sum(
            s.get("pvCapacity", 0) / 1000
            for p in projects for s in p.get("sites", []) if s.get("hasPV")
        )
        total_bess_mwh = sum(
            s.get("bessCapacity", 0) / 1000
            for p in projects for s in p.get("sites", []) if s.get("hasBESS")
        )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(kpi_card("Projets", str(len(projects)), "accent"), unsafe_allow_html=True)
        with c2:
            st.markdown(kpi_card("Sites", str(total_sites), "accent"), unsafe_allow_html=True)
        with c3:
            st.markdown(kpi_card("Capacité PV", f"{total_pv_mwc:.1f} MWc", "positive"), unsafe_allow_html=True)
        with c4:
            st.markdown(kpi_card("Capacité BESS", f"{total_bess_mwh:.1f} MWh", "warning"), unsafe_allow_html=True)

        st.markdown("### Liste des projets")
        rows = []
        for proj in projects:
            for site in proj.get("sites", []):
                rows.append({
                    "Projet":    proj.get("name", "—"),
                    "Site":      site.get("name", "—"),
                    "Pays":      (site.get("countryFlag", "") + " " + site.get("country", "—")).strip(),
                    "Statut":    site.get("status", "—"),
                    "PV (MWc)":  round(site.get("pvCapacity", 0) / 1000, 2) if site.get("hasPV") else "—",
                    "BESS (MWh)":round(site.get("bessCapacity", 0) / 1000, 2) if site.get("hasBESS") else "—",
                    "Courtier":  proj.get("courtier", "—"),
                    "Vendeur":   proj.get("vendeur", "—"),
                })
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

        # Carte technologie
        st.markdown("### Répartition technologique")
        tech_pv   = sum(1 for p in projects for s in p.get("sites",[]) if s.get("hasPV") and not s.get("hasBESS"))
        tech_bess = sum(1 for p in projects for s in p.get("sites",[]) if not s.get("hasPV") and s.get("hasBESS"))
        tech_hyb  = sum(1 for p in projects for s in p.get("sites",[]) if s.get("hasPV") and s.get("hasBESS"))
        if tech_pv + tech_bess + tech_hyb > 0:
            fig = go.Figure(go.Pie(
                labels=["PV seul", "BESS seul", "PV + BESS"],
                values=[tech_pv, tech_bess, tech_hyb],
                marker_colors=[ACCENT, SUCCESS, WARNING],
                hole=0.5,
                textfont_family="Poppins",
            ))
            fig.update_layout(height=280, margin=dict(t=20, b=20, l=20, r=20),
                              font_family="Montserrat", showlegend=True,
                              legend=dict(font=dict(size=11)))
            st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : ANALYSE SITE
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📊 Analyse site":
    st.markdown("# Analyse financière — Site")
    st.markdown("---")

    projects = load_projects()
    if not projects:
        st.warning("Aucun projet disponible. Importez d'abord vos données.")
        st.stop()

    # Sélection projet / site
    proj_names = [p.get("name", f"Projet {i+1}") for i, p in enumerate(projects)]
    sel_proj_name = st.selectbox("Projet", proj_names)
    sel_proj = next((p for p in projects if p.get("name") == sel_proj_name), projects[0])

    sites = sel_proj.get("sites", [])
    if not sites:
        st.info("Ce projet n'a pas encore de sites.")
        st.stop()

    site_names = [s.get("name", f"Site {i+1}") for i, s in enumerate(sites)]
    sel_site_name = st.selectbox("Site", site_names)
    sel_site = next((s for s in sites if s.get("name") == sel_site_name), sites[0])

    params = sel_proj.get("params", {})

    # Bouton calcul
    if st.button("⚡ Calculer les KPIs financiers", type="primary"):
        with st.spinner("Calcul en cours..."):
            result = compute_site_financials(sel_site, params)
            kpis = result["kpis"]
            annual_df = pd.DataFrame(result["annual"])

        st.markdown("### KPIs financiers")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            irr_val = fmt_pct(kpis.get("project_irr"))
            css = "positive" if kpis.get("project_irr", 0) > 8 else "warning"
            st.markdown(kpi_card("TRI Projet", irr_val, css), unsafe_allow_html=True)
        with c2:
            irr_eq = fmt_pct(kpis.get("equity_irr"))
            css = "positive" if kpis.get("equity_irr", 0) > 12 else "warning"
            st.markdown(kpi_card("TRI Equity", irr_eq, css), unsafe_allow_html=True)
        with c3:
            van_val = fmt_eur(kpis.get("van"))
            css = "positive" if (kpis.get("van") or 0) > 0 else ""
            st.markdown(kpi_card("VAN", van_val, css), unsafe_allow_html=True)
        with c4:
            dscr_val = f"{kpis.get('dscr_min', '—')}" if kpis.get("dscr_min") else "—"
            css = "positive" if (kpis.get("dscr_min") or 0) > 1.15 else "warning"
            st.markdown(kpi_card("DSCR min", dscr_val, css), unsafe_allow_html=True)

        # Graphique P&L
        st.markdown("### Résultats financiers annuels")
        fig_pl = go.Figure()
        fig_pl.add_trace(go.Scatter(x=annual_df["year"], y=annual_df["revenue_eur"]/1000,
            name="Chiffre d'affaires", fill="tozeroy", fillcolor="rgba(55,138,221,0.12)",
            line=dict(color=ACCENT, width=2)))
        fig_pl.add_trace(go.Scatter(x=annual_df["year"], y=annual_df["ebitda_eur"]/1000,
            name="EBITDA", fill="tozeroy", fillcolor="rgba(46,158,110,0.10)",
            line=dict(color=SUCCESS, width=2)))
        fig_pl.add_trace(go.Scatter(x=annual_df["year"], y=annual_df["ebt_eur"]/1000,
            name="EBT", line=dict(color=WARNING, width=1.5, dash="dot")))
        fig_pl.add_trace(go.Scatter(x=annual_df["year"], y=annual_df["fcf_equity"]/1000,
            name="FCF Equity", line=dict(color="#7F77DD", width=1.5)))
        fig_pl.update_layout(
            height=350, yaxis_title="k€", xaxis_title="Année",
            font_family="Montserrat", legend=dict(font=dict(size=10)),
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(t=20, b=40, l=60, r=20),
        )
        fig_pl.update_xaxes(showgrid=False)
        fig_pl.update_yaxes(showgrid=True, gridcolor="#F0EDE8")
        st.plotly_chart(fig_pl, use_container_width=True)

        # DSCR
        dscr_data = annual_df[annual_df["dscr"].notna()]
        if not dscr_data.empty:
            st.markdown("### DSCR sur la durée du financement")
            target = params.get("dscrTarget", 1.15)
            fig_dscr = go.Figure()
            fig_dscr.add_trace(go.Bar(x=dscr_data["year"], y=dscr_data["dscr"],
                marker_color=[SUCCESS if v >= target else DANGER for v in dscr_data["dscr"]],
                name="DSCR annuel"))
            fig_dscr.add_hline(y=target, line_dash="dash", line_color=DANGER,
                annotation_text=f"Cible {target}", annotation_position="top right",
                line_width=1.5)
            fig_dscr.update_layout(
                height=280, yaxis_title="DSCR", xaxis_title="Année",
                font_family="Montserrat", plot_bgcolor="white", paper_bgcolor="white",
                margin=dict(t=20, b=40, l=60, r=20),
            )
            fig_dscr.update_yaxes(showgrid=True, gridcolor="#F0EDE8")
            st.plotly_chart(fig_dscr, use_container_width=True)

        # Tableau
        st.markdown("### Tableau P&L annuel")
        display_df = annual_df[[
            "year", "production_kwh", "revenue_eur", "ebitda_eur",
            "ebt_eur", "net_income_eur", "cfads_eur", "debt_service", "dscr", "fcf_equity"
        ]].copy()
        display_df.columns = [
            "Année", "Production (kWh)", "CA (€)", "EBITDA (€)",
            "EBT (€)", "RN (€)", "CFADS (€)", "Service dette (€)", "DSCR", "FCF Equity (€)"
        ]
        for col in ["CA (€)", "EBITDA (€)", "EBT (€)", "RN (€)", "CFADS (€)", "Service dette (€)", "FCF Equity (€)"]:
            display_df[col] = display_df[col].apply(lambda v: f"{v:,.0f}".replace(",", " "))
        display_df["Production (kWh)"] = display_df["Production (kWh)"].apply(lambda v: f"{v:,.0f}".replace(",", " "))
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Export CSV
        csv = annual_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Télécharger le P&L (CSV)",
            data=csv,
            file_name=f"pl_{sel_site_name.replace(' ', '_')}_{date.today()}.csv",
            mime="text/csv",
        )

        # Sauvegarde sur GitHub
        token = get_github_token()
        if token:
            if st.button("📁 Sauvegarder les résultats sur GitHub"):
                with st.spinner("Sauvegarde en cours..."):
                    ok = github_sync.save_financial_results(
                        token, REPO_NAME, sel_proj_name, sel_site_name, result
                    )
                if ok:
                    slug = github_sync.sanitize(sel_proj_name)
                    st.success(
                        f"✓ Résultats sauvegardés dans "
                        f"`projects/{slug}/financial_results/`"
                    )
                else:
                    st.error(
                        "Échec de la sauvegarde. "
                        "Vérifiez le token GitHub dans les secrets Streamlit."
                    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : OUTILS HTML
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔧 Outils HTML":
    st.markdown("# Outils HTML — Application complète")
    st.markdown("---")

    HTML_TOOLS = [
        ("🔐 Connexion",                   "index.html"),
        ("🏠 Portefeuille projets",         "portefeuille_projets.html"),
        ("➕ Créer un projet",               "creer_projet.html"),
        ("➕ Créer un site",                 "creation_site.html"),
        ("📊 Dashboard projet",              "projet_dashboard.html"),
        ("📊 Dashboard site",                "site_dashboard.html"),
        ("📋 Fiche site",                    "fiche_site.html"),
        ("⚡ Simulation flux énergétiques",  "simulation_flux_energetiques.html"),
        ("🔬 Modèle financier",              "test_modele_financier.html"),
        ("📋 Données & Ressources",          "donnees.html"),
        ("📈 Analyse de marché",             "analyse_marche.html"),
    ]

    tool_labels = [t[0] for t in HTML_TOOLS]
    sel_tool = st.selectbox("Sélectionner un outil", tool_labels)
    sel_file = next(t[1] for t in HTML_TOOLS if t[0] == sel_tool)
    sel_url  = f"{GITHUB_PAGES_URL}/{sel_file}"

    st.markdown(f"""
    <div style="background:white;border:1px solid #E2E0DB;border-radius:12px;
                padding:16px 20px;margin-bottom:16px;">
        <p style="font-size:13px;color:#7A7670;margin:0 0 10px;">
            ⚠️ <strong>Note :</strong> Les outils HTML stockent les données dans le
            navigateur (<em>localStorage</em>). Chaque utilisateur voit ses propres
            données. Pour partager entre utilisateurs, utilisez
            <strong>💾 Import / Export</strong>.
        </p>
        <a href="{sel_url}" target="_blank"
           style="display:inline-block;padding:8px 16px;background:#1863DC;
                  color:white;border-radius:8px;text-decoration:none;
                  font-weight:600;font-size:13px;">
            Ouvrir dans un nouvel onglet ↗
        </a>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"**URL :** `{sel_url}`")
    components.iframe(sel_url, height=720, scrolling=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : GESTION PROJETS (GitHub)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📁 Gestion projets":
    st.markdown("# Gestion des projets — GitHub")
    st.markdown("---")

    token = get_github_token()
    if not token:
        st.error("""
**Token GitHub non configuré.**

Pour activer la synchronisation GitHub :
1. Allez sur [share.streamlit.io](https://share.streamlit.io) → votre app → **Settings → Secrets**
2. Ajoutez la ligne :
   ```
   GITHUB_TOKEN = "ghp_votreTokenPersonnel"
   ```
3. Le token doit avoir la permission **repo** (lecture + écriture).

En développement local, créez `.streamlit/secrets.toml` avec le même contenu.
        """)
        st.stop()

    projects = load_projects()
    if not projects:
        st.info("Aucun projet disponible. Importez d'abord vos données via **💾 Import / Export**.")
        st.stop()

    proj_names = [p.get("name", f"Projet {i+1}") for i, p in enumerate(projects)]
    sel_proj_name = st.selectbox("Projet", proj_names)
    sel_proj = next((p for p in projects if p.get("name") == sel_proj_name), projects[0])

    slug = github_sync.sanitize(sel_proj_name)
    folder_url = f"https://github.com/{REPO_NAME}/tree/main/projects/{slug}"

    tab_folder, tab_upload, tab_rename = st.tabs(
        ["📁 Dossier GitHub", "📤 Upload documents", "✏️ Renommer projet"]
    )

    # ── Tab : Dossier GitHub ───────────────────────────────────────────────────
    with tab_folder:
        st.markdown(f"**Chemin GitHub :** `projects/{slug}/`")
        st.markdown(f"[Voir le dossier sur GitHub ↗]({folder_url})")

        if st.button("🔄 Créer / Vérifier le dossier sur GitHub"):
            with st.spinner("En cours..."):
                ok = github_sync.create_project_folder(
                    token, REPO_NAME, sel_proj_name, sel_proj.get("id", "")
                )
            if ok:
                st.success(f"✓ Dossier `projects/{slug}/` créé/vérifié.")
            else:
                st.error("Échec. Vérifiez le token GitHub.")

        st.markdown("### Documents existants")
        with st.spinner("Chargement..."):
            docs = github_sync.list_documents(token, REPO_NAME, sel_proj_name)

        if docs:
            for doc in docs:
                c1, c2 = st.columns([4, 1])
                with c1:
                    size_kb = doc["size"] / 1024
                    st.markdown(f"📄 **{doc['name']}** — {size_kb:.1f} ko")
                with c2:
                    st.markdown(f"[⬇ Télécharger]({doc['download_url']})")
        else:
            st.info("Aucun document dans ce projet.")

    # ── Tab : Upload documents ─────────────────────────────────────────────────
    with tab_upload:
        st.markdown("""
        Uploadez ici les documents associés au projet (études, permis, contrats…).
        Ils seront stockés dans `projects/{slug}/documents/` sur GitHub.
        """.replace("{slug}", slug))

        uploaded_files = st.file_uploader(
            "Sélectionner des fichiers",
            accept_multiple_files=True,
            type=["pdf", "xlsx", "xls", "csv", "docx", "doc",
                  "png", "jpg", "jpeg", "zip"],
        )

        if uploaded_files:
            if st.button("📤 Uploader sur GitHub", type="primary"):
                # Créer le dossier s'il n'existe pas encore
                github_sync.create_project_folder(
                    token, REPO_NAME, sel_proj_name, sel_proj.get("id", "")
                )
                success_count = 0
                for uf in uploaded_files:
                    with st.spinner(f"Upload : {uf.name}…"):
                        ok, url = github_sync.upload_document(
                            token, REPO_NAME, sel_proj_name,
                            uf.name, uf.getvalue()
                        )
                    if ok:
                        success_count += 1
                        st.success(f"✓ {uf.name} → [voir sur GitHub]({url})")
                    else:
                        st.error(f"✗ Échec pour {uf.name}")
                if success_count:
                    st.balloons()

    # ── Tab : Renommer projet ──────────────────────────────────────────────────
    with tab_rename:
        st.markdown("""
        Renommer le projet met à jour :
        - Le nom dans `data/projects.json`
        - Le dossier GitHub (`projects/{ancien}` → `projects/{nouveau}`)
        """)
        new_name = st.text_input("Nouveau nom du projet", value=sel_proj_name)

        if st.button("✏️ Renommer", type="primary"):
            if not new_name or new_name == sel_proj_name:
                st.warning("Le nouveau nom est identique ou vide.")
            else:
                with st.spinner("Renommage du dossier GitHub…"):
                    ok_gh = github_sync.rename_project_folder(
                        token, REPO_NAME, sel_proj_name, new_name
                    )

                if ok_gh:
                    # Mettre à jour le nom dans projects.json
                    for p in projects:
                        if p.get("name") == sel_proj_name:
                            p["name"] = new_name
                            break
                    save_projects(projects)
                    st.success(
                        f"✓ Projet renommé : **{sel_proj_name}** → **{new_name}**"
                    )
                    st.rerun()
                else:
                    st.error("Échec du renommage sur GitHub. Vérifiez le token.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : IMPORT / EXPORT
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "💾 Import / Export":
    st.markdown("# Import / Export des données")
    st.markdown("---")

    tab1, tab2 = st.tabs(["📥 Importer depuis le navigateur", "📤 Exporter"])

    with tab1:
        st.markdown("""
        #### Comment exporter vos données depuis l'application HTML

        Depuis votre navigateur, ouvrez la console développeur (`F12` → onglet **Console**) sur n'importe quelle page de l'app, puis copiez-collez cette commande :

        ```javascript
        copy(localStorage.getItem('pi_projects'))
        ```

        Collez ensuite le résultat ci-dessous :
        """)

        raw = st.text_area("JSON exporté depuis localStorage", height=200,
                            placeholder='[{"id": "proj_...", "name": "...", "sites": [...]}]')

        if st.button("Importer les projets", type="primary") and raw.strip():
            imported = import_from_localstorage_json(raw.strip())
            if imported:
                existing = load_projects()
                existing_ids = {p.get("id") for p in existing}
                new_projects = [p for p in imported if p.get("id") not in existing_ids]
                updated = existing + new_projects
                save_projects(updated)
                st.success(f"✓ {len(new_projects)} nouveau(x) projet(s) importé(s). {len(imported) - len(new_projects)} déjà présent(s).")
                st.balloons()
                # Auto-créer les dossiers GitHub pour les nouveaux projets
                token = get_github_token()
                if token and new_projects:
                    github_ok = sum(
                        1 for p in new_projects
                        if github_sync.create_project_folder(
                            token, REPO_NAME,
                            p.get("name", ""), p.get("id", "")
                        )
                    )
                    if github_ok:
                        st.info(f"📁 {github_ok} dossier(s) créé(s) sur GitHub.")
            else:
                st.error("Format JSON invalide. Vérifiez le contenu copié.")

    with tab2:
        projects = load_projects()
        if projects:
            export_data = json.dumps({"projects": projects, "exportDate": datetime.utcnow().isoformat()},
                                     ensure_ascii=False, indent=2)
            st.download_button(
                label="📥 Télécharger projects.json",
                data=export_data.encode("utf-8"),
                file_name=f"projects_{date.today()}.json",
                mime="application/json",
            )
            st.markdown("**Réimporter dans le navigateur :**")
            st.code(
                "// Collez dans la console F12 de l'app HTML :\n"
                "const data = /* collez ici le contenu du JSON */;\n"
                "localStorage.setItem('pi_projects', JSON.stringify(data.projects));",
                language="javascript"
            )
        else:
            st.info("Aucun projet à exporter.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : PARAMÈTRES
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "⚙️ Paramètres":
    st.markdown("# Paramètres")
    st.markdown("---")

    st.markdown("### Hypothèses économiques par défaut")
    st.caption("Ces valeurs sont utilisées quand un projet ne définit pas ses propres paramètres.")

    c1, c2 = st.columns(2)
    with c1:
        elec_price = st.number_input("Prix électricité (€/MWh)", value=85.0, step=1.0)
        elec_esc   = st.number_input("Escalation prix (% /an)", value=1.5, step=0.1)
        inflation  = st.number_input("Inflation ICP (% /an)",   value=2.0, step=0.1)
        tax_rate   = st.number_input("Taux IS (%)",             value=25.0, step=0.5)
        wacc       = st.number_input("WACC (%)",                value=8.0,  step=0.1)
    with c2:
        debt_pct   = st.number_input("Part dette (%)",          value=70.0, step=1.0)
        senior_r   = st.number_input("Taux dette senior (%)",   value=4.5,  step=0.1)
        debt_dur   = st.number_input("Durée emprunt (ans)",     value=18,   step=1)
        dsra_m     = st.number_input("DSRA (mois)",             value=6,    step=1)
        dscr_t     = st.number_input("DSCR cible",              value=1.15, step=0.01)

    st.markdown("### Liens rapides")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"[🔐 Connexion]({GITHUB_PAGES_URL}/index.html)")
        st.markdown(f"[🏠 Portefeuille projets]({GITHUB_PAGES_URL}/portefeuille_projets.html)")
        st.markdown(f"[➕ Créer un projet]({GITHUB_PAGES_URL}/creer_projet.html)")
        st.markdown(f"[➕ Créer un site]({GITHUB_PAGES_URL}/creation_site.html)")
    with col2:
        st.markdown(f"[📊 Dashboard projet]({GITHUB_PAGES_URL}/projet_dashboard.html)")
        st.markdown(f"[📊 Dashboard site]({GITHUB_PAGES_URL}/site_dashboard.html)")
        st.markdown(f"[📋 Fiche site]({GITHUB_PAGES_URL}/fiche_site.html)")
        st.markdown(f"[📊 Données & Ressources]({GITHUB_PAGES_URL}/donnees.html)")
    with col3:
        st.markdown(f"[⚡ Simulation flux énergétiques]({GITHUB_PAGES_URL}/simulation_flux_energetiques.html)")
        st.markdown(f"[🔬 Modèle financier]({GITHUB_PAGES_URL}/test_modele_financier.html)")
        st.markdown(f"[📈 Analyse de marché]({GITHUB_PAGES_URL}/analyse_marche.html)")

    st.markdown("---")
    st.caption(f"Repository : [{REPO_NAME}](https://github.com/{REPO_NAME})")
