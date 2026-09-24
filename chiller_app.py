"""
chiller_app.py — Electric Chiller Simulation App (Streamlit)

Install & run:
    pip install streamlit pandas matplotlib
    streamlit run chiller_app.py
"""

import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
import chiller_core as cc

st.set_page_config(page_title="Electric Chiller Simulation", page_icon="❄️", layout="wide")
st.title("❄️ Electric Water-Cooled Chiller — Simulation")
st.caption("Evaporator capacity → COP from vendor part-load table (interpolated) → heat rejection. "
           "COP corrected 1.35 %/K around CHWS 6.7 °C and CWS 29.4 °C design.")

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("⚙️ Units")
    u_temp  = st.selectbox("Temperature", ["°C", "°F"])
    u_flow  = st.selectbox("Flow", ["L/s", "GPM"])
    u_power = st.selectbox("Power / Capacity", ["kW", "RT"])
    u_eff   = st.selectbox("Efficiency", ["COP (kW/kW)", "kW/RT"])

    def temp_in(label, lo_c, hi_c, def_c, key):
        if u_temp == "°C":
            return st.number_input(f"{label} [°C]", lo_c, hi_c, def_c, 0.1, key=key)
        return cc.f_to_c(st.number_input(f"{label} [°F]", cc.c_to_f(lo_c),
                                         cc.c_to_f(hi_c), cc.c_to_f(def_c), 0.1, key=key))

    def flow_in(label, def_lps, key, hi_lps=1500.0):
        if u_flow == "L/s":
            return st.number_input(f"{label} [L/s]", 0.0, hi_lps, def_lps, 0.1, key=key)
        return cc.gpm_to_lps(st.number_input(f"{label} [GPM]", 0.0, cc.lps_to_gpm(hi_lps),
                                             cc.lps_to_gpm(def_lps), 1.0, key=key))

    st.header("🧊 Evaporator / Chilled Water")
    chws  = temp_in("CHW Supply Temp", 5.5, 10.0, 6.7, "chws")
    chwr  = temp_in("CHW Return Temp", 9.0, 16.0, 12.2, "chwr")
    chw_f = flow_in("CHW Flow", 251.4, "chwf")

    st.header("🌡️ Condenser / Cooling Water")
    cws  = temp_in("CW Supply Temp", 25.0, 32.0, 29.4, "cws")
    cwr  = temp_in("CW Return Temp", 28.0, 37.0, 35.0, "cwr")
    cw_f = flow_in("CW Flow", 283.2, "cwf")

    st.header("💰 Energy (optional)")
    op_hrs = st.number_input("Operating hours / year", 0, 8760, 3000, 100)
    avg_ld = st.slider("Average load [%]", 20, 100, 70, format="%d%%")
    tariff = st.number_input("Tariff [currency/kWh]", 0.0, 2.0, 0.10, 0.01, format="%.2f")
    co2f   = st.number_input("Grid CO₂ factor [kg/kWh]", 0.0, 1.5, 0.45, 0.05, format="%.2f")

# ------------------------------------------------------------------- model
inp    = cc.ChillerInputs(chws_c=chws, chwr_c=chwr, chw_flow_lps=chw_f,
                          cws_c=cws, cwr_c=cwr, cw_flow_lps=cw_f)
errors = cc.validate(inp)
if errors:
    for e in errors:
        st.error("⚠️ " + e)
    st.stop()

res = cc.simulate(inp)
for w in res.warnings:
    st.warning("⚠️ " + w)

# display helpers (respect selected units)
def p_main(kw): return f"{cc.kw_to_rt(kw):,.1f} RT" if u_power == "RT" else f"{kw:,.1f} kW"
def p_sub(kw):  return f"= {kw:,.1f} kW" if u_power == "RT" else f"= {cc.kw_to_rt(kw):,.1f} RT"
def e_str(cop): return f"{cc.KW_PER_RT/cop:.3f} kW/RT" if u_eff == "kW/RT" else f"{cop:.3f} COP"
def e_lab():    return "Efficiency [kW/RT]" if u_eff == "kW/RT" else "Efficiency [COP]"
def t_str(c):   v = c if u_temp == "°C" else cc.c_to_f(c); return f"{v:.1f} {u_temp}"

# ------------------------------------------------------- operating point
st.subheader("Operating Point")
m = st.columns(6)
m[0].metric("Cooling Capacity", p_main(res.cooling_kw), p_sub(res.cooling_kw))
m[1].metric("Chiller Load", f"{res.load_pct:.1f} %", f"of {cc.FULL_LOAD_KW:,.0f} kW design")
m[2].metric("Compressor Input", p_main(res.input_kw), f"base {res.cop_base:.3f} COP")
m[3].metric(e_lab(), e_str(res.cop_adj), f"corr {res.temp_correction_pct:+.2f} %")
m[4].metric("Heat Rejection", p_main(res.heat_rejection_kw), p_sub(res.heat_rejection_kw))
m[5].metric("Calculated CWR", t_str(res.cwr_calc_c), f"entered {t_str(cwr)}")
st.caption(f"CHW ΔT {res.chw_dt_k:.2f} K · CW ΔT {res.cw_dt_k:.2f} K · "
           f"Evap PD {res.evap_pd_kpa:.1f} kPa · Cond PD {res.cond_pd_kpa:.1f} kPa · "
           f"Pump head ≈ {res.evap_pump_kw:.1f} + {res.cond_pump_kw:.1f} kW (hydraulic)")

with st.expander("📋 All results (SI + selected units)"):
    rows = [("Cooling capacity", f"{res.cooling_kw:,.1f}", "kW"),
            ("Cooling capacity", f"{res.cooling_rt:,.1f}", "RT"),
            ("Chilled-water ΔT", f"{res.chw_dt_k:.2f}", "K"),
            ("Chiller load", f"{res.load_pct:.1f}", "%"),
            ("COP — table base", f"{res.cop_base:.3f}", "kW/kW"),
            ("COP — adjusted", f"{res.cop_adj:.3f}", "kW/kW"),
            ("Efficiency", f"{res.kw_per_rt:.3f}", "kW/RT"),
            ("Compressor input", f"{res.input_kw:,.1f}", "kW"),
            ("Heat rejection", f"{res.heat_rejection_kw:,.1f}", "kW"),
            ("Condenser-water ΔT", f"{res.cw_dt_k:.2f}", "K"),
            ("CW return (calculated)", f"{res.cwr_calc_c:.2f}", "°C"),
            ("Evap / Cond PD", f"{res.evap_pd_kpa:.1f} / {res.cond_pd_kpa:.1f}", "kPa")]
    st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value", "Unit"]), hide_index=True)

pl = pd.DataFrame(cc.part_load_table(inp))
tab1, tab2, tab3, tab4 = st.tabs(["📈 Part-Load Curve", "📋 Part-Load Table",
                                  "⚡ IPLV & Energy", "🗄️ Vendor Data"])

with tab1:
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    ax[0].plot(pl.load_pct, pl.cop_base, "o--", c="#999", label="Table COP (uncorrected)")
    ax[0].plot(pl.load_pct, pl.cop_adj, "s-", c="#1f77b4", label="COP w/ CHWS & CWS correction")
    ax[0].axvline(min(max(res.load_pct, 20), 100), color="red", ls=":",
                  label=f"Operating point {res.load_pct:.0f} %")
    ax[0].set_xlabel("Chiller load [%]"); ax[0].set_ylabel("COP [kW/kW]")
    ax[0].set_title("Efficiency vs load"); ax[0].grid(alpha=.3); ax[0].legend(fontsize=8)
    ax[1].plot(pl.load_pct, pl.input_kw, "s-", c="#d62728")
    ax[1].axvline(min(max(res.load_pct, 20), 100), color="red", ls=":")
    ax[1].set_xlabel("Chiller load [%]"); ax[1].set_ylabel("Compressor input [kW]")
    ax[1].set_title("Power vs load"); ax[1].grid(alpha=.3)
    st.pyplot(fig)

with tab2:
    show = pl[["load_pct", "capacity_kw", "capacity_rt", "input_kw", "cop_adj",
               "kw_per_rt", "chw_flow_lps", "evap_pd_kpa", "cond_pd_kpa"]].copy()
    show.columns = ["Load %", "Capacity kW", "Capacity RT", "Input kW", "COP",
                    "kW/RT", "CHW Flow L/s", "Evap PD kPa", "Cond PD kPa"]
    op = min(max(res.load_pct, 20), 100)
    show.insert(0, " ", ["◀ operating" if abs(x - op) <= 5 else "" for x in show["Load %"]])
    st.dataframe(show.round(2), hide_index=True)
    st.download_button("⬇ Download CSV", show.round(3).to_csv(index=False).encode("utf-8"),
                       "chiller_part_load.csv", "text/csv")

with tab3:
    st.markdown("##### IPLV — AHRI 550/590 weighting (100/75/50/25 % → 1/42/45/12 %)")
    iplv_f, iplv_a = cc.iplv_cop(inp, "fixed"), cc.iplv_cop(inp, "ahri")
    c1, c2, c3 = st.columns(3)
    c1.metric("IPLV COP (fixed CWS)", f"{iplv_f:.3f}")
    c2.metric("IPLV COP (AHRI cond. relief)", f"{iplv_a:.3f}")
    c3.metric("IPLV (AHRI)", f"{cc.KW_PER_RT/iplv_a:.3f} kW/RT")
    st.divider()
    st.markdown("##### Annual energy & cost at average load")
    p_avg = cc.input_kw_at_load(inp, avg_ld)
    e_kwh = p_avg * op_hrs
    a, b, c4, d = st.columns(4)
    a.metric("Avg input power", f"{p_avg:,.0f} kW")
    b.metric("Energy / year", f"{e_kwh/1000:,.0f} MWh")
    c4.metric("Cost / year", f"{e_kwh*tariff:,.0f}")
    d.metric("CO₂ / year", f"{e_kwh*co2f/1000:,.1f} t")

with tab4:
    st.markdown("Vendor part-load table (design: CHWS 6.7 °C / CWS 29.4 °C / CHW 251.4 L/s)")
    st.dataframe(pd.DataFrame({"Load %": cc.PERF_TABLE["load_pct"],
                               "Capacity kW": cc.PERF_TABLE["capacity_kw"],
                               "Input kW": cc.PERF_TABLE["input_kw"],
                               "Evap Flow L/s": cc.PERF_TABLE["evap_flow_lps"],
                               "Evap PD kPa": cc.PERF_TABLE["evap_pd_kpa"],
                               "Cond PD kPa": cc.PERF_TABLE["cond_pd_kpa"],
                               "COP": cc.PERF_TABLE["cop"]}), hide_index=True)

with st.expander("🧮 Formulas used"):
    st.latex(r"Q_{evap} = \dot{V}_{chw}\cdot\rho\cdot c_p\cdot(T_{chwr}-T_{chws})")
    st.latex(r"COP_{adj} = COP_{table}\cdot\left[1+0.0135\cdot\left((T_{chws}-6.7)+(29.4-T_{cws})\right)\right]")
    st.latex(r"P_{comp} = Q_{evap}/COP_{adj}\qquad Q_{rej} = Q_{evap}+P_{comp}")
    st.latex(r"T_{cwr,calc} = T_{cws} + Q_{rej}/(\dot{V}_{cw}\cdot\rho\cdot c_p)")