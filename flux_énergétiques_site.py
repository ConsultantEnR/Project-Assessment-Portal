"""
Générateur HTML — Centrale PV utility-scale — 2 cycles BESS/jour
=================================================================
Ce script calcule la simulation en Python puis génère un fichier HTML
autonome et interactif (Chart.js embarqué) qui s'ouvre directement
dans n'importe quel navigateur Windows (Edge, Chrome, Firefox).

Aucune dépendance externe : uniquement la bibliothèque standard Python.
Exécution : python pv_html_export.py
Sortie : simulation_flux_energetiques.html (dans le même dossier)
"""

import math
import json
import webbrowser
import os

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — modifiez ces valeurs
# ─────────────────────────────────────────────────────────────────────────────

PV_MW = 50.0 # Puissance crête PV installée (MWc)
IRR_KWH_M2 = 5.5 # Irradiance journalière (kWh/m²/j)
PR = 0.82 # Performance Ratio PV

BESS_MWH = 100.0 # Capacité utile BESS (MWh)
BESS_MW = 50.0 # Puissance max charge / décharge (MW)
BESS_EFF_CH = 0.95 # Rendement charge
BESS_EFF_DISCH = 0.95 # Rendement décharge
DOD_MAX = 0.90 # Profondeur de décharge max
SOC_INIT = 0.05 # SoC initial (fraction de BESS_MWH)

GRID_CAP_MW = 60.0 # Plafond raccordement réseau (MW)

C1_CHARGE_START = 7
C1_CHARGE_END = 10
C1_DISCHARGE_START = 11
C1_DISCHARGE_END = 13

C2_CHARGE_START = 13
C2_CHARGE_END = 16
C2_DISCHARGE_START = 18
C2_DISCHARGE_END = 21

OUTPUT_FILE = "pv_simulation.html"
AUTO_OPEN_BROWSER = True # ouvre le fichier dans le navigateur après génération

# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION (bibliothèque standard uniquement — pas de numpy)
# ─────────────────────────────────────────────────────────────────────────────

HOURS = list(range(24))

def gaussian(x: float, mu: float, sigma: float) -> float:
    return math.exp(-0.5 * ((x - mu) / sigma) ** 2)

def pv_profile(pv_mw: float, irr_kwh: float, pr: float) -> list:
    raw = [max(0.0, gaussian(h, 12.5, 3.2)) for h in HOURS]
    total = sum(raw)
    scale = irr_kwh / total * (pv_mw * pr)
    return [v * scale for v in raw]

def in_window(h: int, start: int, end: int) -> bool:
    return start <= h <= end

def simulate(pv_mw, irr_kwh, pr, bess_mwh, bess_mw, bess_eff_ch, bess_eff_disch, dod_max, soc_init, grid_cap_mw, c1_cs, c1_ce, c1_ds, c1_de, c2_cs, c2_ce, c2_ds, c2_de):

    pv = pv_profile(pv_mw, irr_kwh, pr)
    soc_min = (1.0 - dod_max) * bess_mwh
    soc_max = bess_mwh

    soc = [0.0] * 25
    soc[0] = bess_mwh * soc_init

    ch = [0.0] * 24
    di = [0.0] * 24
    inj_d = [0.0] * 24
    inj_b = [0.0] * 24
    curt = [0.0] * 24

    for h in HOURS:
        s = soc[h]
        pv_h = pv[h]
        ch_h = 0.0
        di_h = 0.0

        # Charge BESS
        if bess_mwh > 0 and (in_window(h, c1_cs, c1_ce) or in_window(h, c2_cs, c2_ce)):
            room = max(0.0, (soc_max - s) / bess_eff_ch)
            ch_h = min(pv_h, bess_mw, room)
            s += ch_h * bess_eff_ch

        # Décharge BESS
        if bess_mwh > 0 and (in_window(h, c1_ds, c1_de) or in_window(h, c2_ds, c2_de)):
            n_slots = (c1_de - c1_ds + 1) if in_window(h, c1_ds, c1_de) else (c2_de - c2_ds + 1)
            avail = max(0.0, (s - soc_min) * bess_eff_disch)
            di_h = min(bess_mw, avail / n_slots)
            s -= di_h / bess_eff_disch

        soc[h + 1] = min(soc_max, max(soc_min, s))
        ch[h] = ch_h
        di[h] = di_h

        pv_net = max(0.0, pv_h - ch_h)
        inj_raw = pv_net + di_h
        curt_h = max(0.0, inj_raw - grid_cap_mw)
        inj_d[h] = min(pv_net, grid_cap_mw)
        inj_b[h] = max(0.0, min(di_h, grid_cap_mw - inj_d[h]))
        curt[h] = curt_h

    inj = [inj_d[h] + inj_b[h] for h in HOURS]
    soc_s = soc[:24]
    soc_pct = [v / bess_mwh * 100 if bess_mwh > 0 else 0.0 for v in soc_s]

    tot_pv = sum(pv)
    tot_inj = sum(inj)
    tot_curt = sum(curt)
    tot_ch = sum(ch)
    tot_di = sum(di)
    tot_ib = sum(inj_b)
    cycles = tot_di / bess_mwh if bess_mwh > 0 else 0.0
    rte = tot_di / tot_ch * 100 if tot_ch > 0 else 0.0
    losses = tot_ch * bess_eff_ch - tot_di * bess_eff_disch
    curt_rt = tot_curt / tot_pv * 100 if tot_pv > 0 else 0.0
    peak_inj = max(inj)
    soc_min_pct = soc_min / bess_mwh * 100 if bess_mwh > 0 else 0.0

    return dict(
        pv=pv, ch=ch, di=di, inj_d=inj_d, inj_b=inj_b,
        inj=inj, curt=curt, soc_pct=soc_pct,
        tot_pv=tot_pv, tot_inj=tot_inj, tot_curt=tot_curt,
        tot_ch=tot_ch, tot_di=tot_di, tot_ib=tot_ib,
        cycles=cycles, rte=rte, losses=losses,
        curt_rt=curt_rt, peak_inj=peak_inj,
        soc_min_pct=soc_min_pct,
    )

# ─────────────────────────────────────────────────────────────────────────────
# GÉNÉRATION HTML
# ─────────────────────────────────────────────────────────────────────────────

def r2(v: float) -> str:
    return f"{v:.2f}"

def r1(v: float) -> str:
    return f"{v:.1f}"

def build_html(d: dict, p: dict) -> str:

    # Sérialisation des données pour Chart.js
    js_pv = json.dumps([round(v, 2) for v in d["pv"]])
    js_ch = json.dumps([round(-v, 2) for v in d["ch"]]) # négatif pour visuel
    js_injd = json.dumps([round(v, 2) for v in d["inj_d"]])
    js_injb = json.dumps([round(v, 2) for v in d["inj_b"]])
    js_curt = json.dumps([round(v, 2) for v in d["curt"]])
    js_soc = json.dumps([round(v, 2) for v in d["soc_pct"]])
    js_gcap = json.dumps([round(p["grid_cap_mw"], 1)] * 24)
    js_smin = json.dumps([round(d["soc_min_pct"], 1)] * 24)
    js_labels= json.dumps([f"{h}h" for h in range(24)])

    # Fenêtres de cycle pour les zones colorées
    windows = json.dumps([
        {"start": p["c1_cs"] - 0.5, "end": p["c1_ce"] + 0.5, "color": "rgba(181,212,244,0.18)", "label": "Charge C1"},
        {"start": p["c1_ds"] - 0.5, "end": p["c1_de"] + 0.5, "color": "rgba(186,117,23,0.12)", "label": "Décharge C1"},
        {"start": p["c2_cs"] - 0.5, "end": p["c2_ce"] + 0.5, "color": "rgba(192,221,151,0.18)", "label": "Charge C2"},
        {"start": p["c2_ds"] - 0.5, "end": p["c2_de"] + 0.5, "color": "rgba(226,75,74,0.10)", "label": "Décharge C2"},
    ])

    kpis = [
        ("Production PV", r1(d["tot_pv"]) + " MWh", "#378ADD"),
        ("Injection réseau", r1(d["tot_inj"]) + " MWh", "#EF9F27"),
        (" dont PV directe", r1(sum(d["inj_d"])) + " MWh", "#EF9F27"),
        (" dont BESS", r1(d["tot_ib"]) + " MWh", "#BA7517"),
        ("Écrêtement", r1(d["tot_curt"]) + f" MWh ({r1(d['curt_rt'])}%)", "#E24B4A"),
        ("Charge BESS", r1(d["tot_ch"]) + " MWh", "#1D9E75"),
        ("Décharge BESS", r1(d["tot_di"]) + " MWh", "#9FE1CB"),
        ("Cycles réalisés", f"{d['cycles']:.2f} / jour", "#7F77DD"),
        ("RTE BESS", r1(d["rte"]) + " %", "#7F77DD"),
        ("Pertes BESS", r1(d["losses"]) + " MWh", "#888888"),
        ("Pic injection", r1(d["peak_inj"])+ " MW", "#EF9F27"),
    ]

    kpi_rows = "\n".join(
        f'<tr><td class="kl">{label}</td><td class="kv" style="color:{color}">{value}</td></tr>'
        for label, value, color in kpis
    )

    params_info = (
        f"{p['pv_mw']} MWc &nbsp;|&nbsp; "
        f"BESS {p['bess_mwh']} MWh / {p['bess_mw']} MW &nbsp;|&nbsp; "
        f"Irradiance {p['irr_kwh']} kWh/m²/j &nbsp;|&nbsp; "
        f"PR {round(p['pr']*100)}% &nbsp;|&nbsp; "
        f"Raccordement {p['grid_cap_mw']} MW &nbsp;|&nbsp; "
        f"DoD {round(p['dod_max']*100)}%"
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Simulation PV utility-scale</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #F5F5F2; color: #222; padding: 24px; }}
    h1 {{ font-size: 15px; font-weight: 600; margin-bottom: 4px; }}
    .sub {{ font-size: 11px; color: #666; margin-bottom: 20px; }}
    .grid-kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px,1fr)); gap: 10px; margin-bottom: 20px; }}
    .kpi-card {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;padding: 12px 14px; }}
    .kpi-label {{ font-size: 10px; color: #888; margin-bottom: 4px; }}
    .kpi-value {{ font-size: 18px; font-weight: 600; }}
    .section {{ font-size: 11px; font-weight: 600; color: #888; letter-spacing: .06em;text-transform: uppercase; margin: 20px 0 6px; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 10px;font-size: 11px; color: #555; }}
    .legend span {{ display: flex; align-items: center; gap: 5px; }}
    .sq {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}
    .chart-wrap {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin-bottom: 16px; position: relative; }}
    .chart-wrap canvas {{ width: 100% !important; }}
    .layout {{ display: grid; grid-template-columns: 1fr 220px; gap: 16px; align-items: start; margin-bottom: 16px; }}
    table.kpis {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
    table.kpis tr {{ border-bottom: 1px solid #f0f0f0; }}
    td.kl {{ color: #666; padding: 5px 0; }}
    td.kv {{ text-align: right; font-weight: 600; padding: 5px 0; white-space: nowrap; }}
    .kpi-box {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;
    padding: 14px; }}
    .kpi-box h3 {{ font-size: 11px; font-weight: 600; color: #888; margin-bottom: 10px;
    text-transform: uppercase; letter-spacing: .05em; }}
</style>
</head>
<body>

<h1>Centrale PV utility-scale — Injection réseau pure — 2 cycles BESS/jour</h1>
<p class="sub">{params_info}</p>

<div class="section">KPIs journaliers</div>
<div class="grid-kpi">
<div class="kpi-card"><div class="kpi-label">Production PV</div>
<div class="kpi-value" style="color:#378ADD">{r1(d["tot_pv"])} MWh</div></div>
<div class="kpi-card"><div class="kpi-label">Injection réseau</div>
<div class="kpi-value" style="color:#EF9F27">{r1(d["tot_inj"])} MWh</div></div>
<div class="kpi-card"><div class="kpi-label">Écrêtement</div>
<div class="kpi-value" style="color:#E24B4A">{r1(d["tot_curt"])} MWh</div></div>
<div class="kpi-card"><div class="kpi-label">Cycles BESS</div>
<div class="kpi-value" style="color:#7F77DD">{d["cycles"]:.2f} / j</div></div>
<div class="kpi-card"><div class="kpi-label">RTE BESS</div>
<div class="kpi-value" style="color:#7F77DD">{r1(d["rte"])} %</div></div>
<div class="kpi-card"><div class="kpi-label">Pic injection</div>
<div class="kpi-value" style="color:#EF9F27">{r1(d["peak_inj"])} MW</div></div>
</div>

<div class="section">Flux énergétiques horaires</div>
<div class="legend">
<span><span class="sq" style="background:#378ADD"></span>Production PV</span>
<span><span class="sq" style="background:#EF9F27"></span>Injection PV directe</span>
<span><span class="sq" style="background:#BA7517"></span>Injection BESS</span>
<span><span class="sq" style="background:#1D9E75"></span>Charge BESS</span>
<span><span class="sq" style="background:#E24B4A"></span>Écrêtement</span>
<span><span class="sq" style="background:#A32D2D; height:3px; border-radius:0;"></span>Raccordement réseau</span>
</div>

<div class="layout">
<div class="chart-wrap" style="height:320px">
<canvas id="cMain"></canvas>
</div>
<div class="kpi-box">
<h3>Détail journalier</h3>
<table class="kpis">{kpi_rows}</table>
</div>
</div>

<div class="section">État de charge BESS — 2 cycles/jour</div>
<div class="chart-wrap" style="height:200px">
<canvas id="cSoc"></canvas>
</div>

<script>
const LABELS = {js_labels};
const PV = {js_pv};
const CH = {js_ch};
const INJ_D = {js_injd};
const INJ_B = {js_injb};
const CURT = {js_curt};
const SOC = {js_soc};
const GCAP = {js_gcap};
const SOC_MIN = {js_smin};
const WINDOWS = {windows};

// Plugin zones colorées (cycles)
const windowPlugin = {{
id: 'windowPlugin',
beforeDraw(chart) {{
const ctx = chart.ctx;
const xScale = chart.scales.x;
const yScale = chart.scales.y;
WINDOWS.forEach(w => {{
const x1 = xScale.getPixelForValue(w.start);
const x2 = xScale.getPixelForValue(w.end);
ctx.save();
ctx.fillStyle = w.color;
ctx.fillRect(x1, yScale.top, x2 - x1, yScale.bottom - yScale.top);
ctx.restore();
}});
}}
}};

// Graphique 1 — Flux horaires
new Chart(document.getElementById('cMain'), {{
type: 'bar',
plugins: [windowPlugin],
data: {{
labels: LABELS,
datasets: [
{{ label: 'Injection PV directe', data: INJ_D, backgroundColor: '#EF9F27', stack: 'pos' }},
{{ label: 'Injection BESS', data: INJ_B, backgroundColor: '#BA7517', stack: 'pos' }},
{{ label: 'Écrêtement', data: CURT, backgroundColor: '#E24B4A', stack: 'pos' }},
{{ label: 'Charge BESS', data: CH, backgroundColor: '#1D9E75', stack: 'neg' }},
{{ type: 'line', label: 'Production PV', data: PV,
borderColor: '#378ADD', borderWidth: 2.5, pointRadius: 2,
fill: false, tension: 0.35, stack: undefined, order: 0 }},
{{ type: 'line', label: 'Raccordement réseau', data: GCAP,
borderColor: '#A32D2D', borderWidth: 1.5, borderDash: [6,3],
pointRadius: 0, fill: false, stack: undefined, order: 0 }},
]
}},
options: {{
responsive: true, maintainAspectRatio: false,
plugins: {{
legend: {{ display: false }},
tooltip: {{ mode: 'index', intersect: false,
callbacks: {{ label: ctx => `${{ctx.dataset.label}}: ${{Math.abs(ctx.raw).toFixed(1)}} MWh` }} }}
}},
scales: {{
x: {{ stacked: true, ticks: {{ font: {{ size: 10 }}, autoSkip: false }} }},
y: {{ stacked: true, title: {{ display: true, text: 'MWh', font: {{ size: 11 }} }},
ticks: {{ font: {{ size: 10 }}, callback: v => v.toFixed(0) }} }}
}}
}}
}});

// Graphique 2 — SoC BESS
new Chart(document.getElementById('cSoc'), {{
type: 'line',
plugins: [windowPlugin],
data: {{
labels: LABELS,
datasets: [
{{ label: 'SoC (%)', data: SOC,
borderColor: '#7F77DD', backgroundColor: 'rgba(127,119,221,0.12)',
fill: true, tension: 0.4, pointRadius: 2.5 }},
{{ label: 'SoC min (DoD {round(p["dod_max"]*100)}%)', data: SOC_MIN,
borderColor: '#E24B4A', borderWidth: 1.2, borderDash: [5,3],
pointRadius: 0, fill: false }},
{{ label: 'SoC max (100%)', data: new Array(24).fill(100),
borderColor: '#1D9E75', borderWidth: 1.2, borderDash: [5,3],
pointRadius: 0, fill: false }},
]
}},
options: {{
responsive: true, maintainAspectRatio: false,
plugins: {{
legend: {{ position: 'bottom', labels: {{ font: {{ size: 10 }}, boxWidth: 12 }} }}
}},
scales: {{
x: {{ ticks: {{ font: {{ size: 10 }}, autoSkip: false }} }},
y: {{ min: 0, max: 110,
title: {{ display: true, text: 'SoC (%)', font: {{ size: 11 }} }},
ticks: {{ font: {{ size: 10 }} }} }}
}}
}}
}});
</script>
</body>
</html>"""
    return html

# ─────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────────────────────────────────────

def main():
    params = dict(
        pv_mw = PV_MW,
        irr_kwh = IRR_KWH_M2,
        pr = PR,
        bess_mwh = BESS_MWH,
        bess_mw = BESS_MW,
        bess_eff_ch = BESS_EFF_CH,
        bess_eff_disch = BESS_EFF_DISCH,
        dod_max = DOD_MAX,
        soc_init = SOC_INIT,
        grid_cap_mw= GRID_CAP_MW,
        c1_cs = C1_CHARGE_START, c1_ce = C1_CHARGE_END,
        c1_ds = C1_DISCHARGE_START, c1_de = C1_DISCHARGE_END,
        c2_cs = C2_CHARGE_START, c2_ce = C2_CHARGE_END,
        c2_ds = C2_DISCHARGE_START, c2_de = C2_DISCHARGE_END,
    )

    print("Simulation en cours...")
    data = simulate(**params)

    print("\nKPIs journaliers")
    print(f" Production PV : {data['tot_pv']:.2f} MWh")
    print(f" Injection réseau : {data['tot_inj']:.2f} MWh")
    print(f" Écrêtement : {data['tot_curt']:.2f} MWh ({data['curt_rt']:.1f}%)")
    print(f" Cycles BESS réalisés: {data['cycles']:.2f} / jour")
    print(f" RTE BESS : {data['rte']:.1f} %")
    print(f" Pic injection : {data['peak_inj']:.2f} MW")

    html_content = build_html(data, params)

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILE)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\nFichier généré : {output_path}")

    if AUTO_OPEN_BROWSER:
        webbrowser.open(f"file:///{output_path.replace(os.sep, '/')}")
        print("Ouverture dans le navigateur...")


if __name__ == "__main__":
    main()