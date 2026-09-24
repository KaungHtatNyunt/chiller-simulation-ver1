"""
chiller_core.py
======================================================================
Electric water-cooled chiller simulation engine (GUI independent).

Internal (SI) units:  temperature °C | flow L/s | power kW | eff. COP (kW/kW)

Sequence:
  (1) Evaporator capacity :  Q  = V̇ · ρ · cp · (T_chwr − T_chws)
  (2) Part-load COP       :  linear interpolation of vendor table vs %load
  (3) Temp correction     :  COP = COP_tbl · [1 + 0.0135·((CHWS−6.7)+(29.4−CWS))]
  (4) Compressor power    :  P  = Q / COP
  (5) Heat rejection      :  HR = Q + P ;  CWR_calc = CWS + HR/(V̇_cw·ρ·cp)
"""

from dataclasses import dataclass, field
from typing import List

# ------------------------------------------------------------------ constants
CP_WATER   = 4.186         # kJ/kg·K  (specific heat of water)
RHO_WATER  = 1.0           # kg/L     (≈ 1000 kg/m³)
KW_PER_RT  = 3.517         # 1 refrigeration ton = 3.517 kW
GPM_TO_LPS = 0.0630902     # 1 US gpm = 0.0630902 L/s

# Design (rating) point -> basis of vendor table and the 1.35 %/K correction
DESIGN = {
    "capacity_kw":  5800.0,
    "chw_flow_lps": 251.4,
    "cw_flow_lps":  283.2,
    "chws_c":       6.7,      # base CHW supply temperature
    "chwr_c":       12.2,
    "cws_c":        29.4,     # base CW supply temperature
    "cwr_c":        35.0,
}
FULL_LOAD_KW   = DESIGN["capacity_kw"]
COP_CORR_PER_K = 0.0135    # 1.35 % COP change per K (CHWS up OR CWS down)
MIN_LOAD_PCT   = 20.0      # stable operating limit of the table

# Vendor part-load performance table
PERF_TABLE = {
    "load_pct":      [100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0],
    "capacity_kw":   [5800,  5220, 4640, 4060, 3480, 2900, 2320, 1740, 1160],
    "input_kw":      [849.6, 764.5, 697.1, 629.9, 553.8, 481.4, 406.3, 330.6, 251.7],
    "evap_flow_lps": [251.4, 226.3, 201.1, 176.0, 150.8, 125.7, 100.6, 75.42, 67.45],
    "evap_pd_kpa":   [62.8,  52.0, 42.1,  33.1,  25.1,  18.1,  11.9,  6.69, 5.35],
    "cond_pd_kpa":   [35.4,  29.3, 23.7,  18.7,  17.2,  17.2,  17.3,  17.3, 17.4],
    "cop":           [6.827, 6.828, 6.656, 6.445, 6.284, 6.024, 5.711, 5.263, 4.608],
}

# AHRI 550/590 IPLV weighting (100/75/50/25 %) and part-load condenser EWT
IPLV_LOADS   = (100.0, 75.0, 50.0, 25.0)
IPLV_WEIGHTS = (0.01, 0.42, 0.45, 0.12)
AHRI_ECWT_C  = {100.0: 29.44, 75.0: 23.89, 50.0: 18.33, 25.0: 18.33}

# Permitted input ranges (°C)
LIMITS = {
    "chws_c": (5.5, 10.0, "Chilled-water supply temperature"),
    "chwr_c": (9.0, 16.0, "Chilled-water return temperature"),
    "cws_c":  (25.0, 32.0, "Condenser-water supply temperature"),
    "cwr_c":  (28.0, 37.0, "Condenser-water return temperature"),
}

# ------------------------------------------------------------- unit helpers
def c_to_f(c):            return c * 9.0 / 5.0 + 32.0
def f_to_c(f):            return (f - 32.0) * 5.0 / 9.0
def kw_to_rt(kw):         return kw / KW_PER_RT
def rt_to_kw(rt):         return rt * KW_PER_RT
def cop_to_kw_per_rt(cop):  return KW_PER_RT / cop
def kw_per_rt_to_cop(kwrt): return KW_PER_RT / kwrt
def lps_to_gpm(lps):      return lps / GPM_TO_LPS
def gpm_to_lpm(gpm):      return gpm * GPM_TO_LPS
def gpm_to_lps(gpm):      return gpm * GPM_TO_LPS


def interp(x: float, xs, ys) -> float:
    """Piece-wise linear interpolation, clamped at the ends (xs asc or desc)."""
    if x <= min(xs[0], xs[-1]):
        return ys[0] if xs[0] < xs[-1] else ys[-1]
    if x >= max(xs[0], xs[-1]):
        return ys[-1] if xs[0] < xs[-1] else ys[0]
    for i in range(len(xs) - 1):
        if min(xs[i], xs[i + 1]) <= x <= max(xs[i], xs[i + 1]):
            return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])
    return ys[-1]

# ------------------------------------------------------------ data classes
@dataclass
class ChillerInputs:
    chws_c:       float = DESIGN["chws_c"]       # CHW supply  (5.5–10 °C)
    chwr_c:       float = DESIGN["chwr_c"]       # CHW return  (9–16 °C)
    chw_flow_lps: float = DESIGN["chw_flow_lps"] # CHW flow    (L/s)
    cws_c:        float = DESIGN["cws_c"]        # CW supply   (25–32 °C)
    cwr_c:        float = DESIGN["cwr_c"]        # CW return   (28–37 °C)
    cw_flow_lps:  float = DESIGN["cw_flow_lps"]  # CW flow     (L/s)


@dataclass
class ChillerResults:
    cooling_kw: float
    cooling_rt: float
    chw_dt_k: float
    load_pct: float
    cop_base: float
    cop_adj: float
    temp_correction_pct: float
    input_kw: float
    kw_per_rt: float
    heat_rejection_kw: float
    cw_dt_k: float
    cwr_calc_c: float
    evap_pd_kpa: float
    cond_pd_kpa: float
    evap_pump_kw: float
    cond_pump_kw: float
    clamped: bool
    warnings: List[str] = field(default_factory=list)

# ------------------------------------------------------------- calculations
def validate(inp: ChillerInputs) -> List[str]:
    """Return a list of input-range error messages (empty = OK)."""
    errors = []
    for attr, (lo, hi, name) in LIMITS.items():
        v = getattr(inp, attr)
        if not (lo - 1e-9 <= v <= hi + 1e-9):
            errors.append(f"{name} = {v:.2f} °C is outside the permitted range "
                          f"{lo}–{hi} °C.")
    if inp.chwr_c - inp.chws_c <= 0.0:
        errors.append("CHW return must be warmer than CHW supply (ΔT > 0 K).")
    if inp.chw_flow_lps <= 0.0 or inp.cw_flow_lps <= 0.0:
        errors.append("Water flow rates must be greater than zero.")
    return errors


def _temp_correction_frac(inp: ChillerInputs) -> float:
    """Fractional COP correction, e.g. +0.0135 for CHWS +1 K or CWS −1 K."""
    dtk = (inp.chws_c - DESIGN["chws_c"]) + (DESIGN["cws_c"] - inp.cws_c)
    return COP_CORR_PER_K * dtk


def simulate(inp: ChillerInputs) -> ChillerResults:
    """Run one full simulation of the operating point."""
    warns: List[str] = []

    # (1) Cooling capacity from the evaporator (chilled-water) side
    chw_dt = inp.chwr_c - inp.chws_c
    if chw_dt < 2.0:
        warns.append(f"CHW ΔT = {chw_dt:.2f} K is unusually small — please verify.")
    q_kw = inp.chw_flow_lps * RHO_WATER * CP_WATER * chw_dt          # kW
    q_rt = q_kw / KW_PER_RT

    # (2) Chiller loading + COP interpolation from the vendor table
    load_pct = q_kw / FULL_LOAD_KW * 100.0
    clamped  = load_pct < MIN_LOAD_PCT or load_pct > 100.0
    load_i   = min(max(load_pct, MIN_LOAD_PCT), 100.0)
    if load_pct > 100.0:
        warns.append(f"Load {load_pct:.1f} % exceeds full load — results held at 100 %.")
    if load_pct < MIN_LOAD_PCT:
        warns.append(f"Load {load_pct:.1f} % below {MIN_LOAD_PCT:.0f} % stable limit — "
                     "COP clamped to the 20 % table value.")
    cop_base = interp(load_i, PERF_TABLE["load_pct"], PERF_TABLE["cop"])

    # (3) CHWS / CWS correction (1.35 % per K)
    corr_frac = _temp_correction_frac(inp)
    cop_adj   = cop_base * (1.0 + corr_frac)

    # (4) Compressor (motor) input power
    p_kw = q_kw / cop_adj
    kwrt = p_kw / q_rt

    # (5) Heat rejection and condenser water side
    q_rej    = q_kw + p_kw
    cw_dt    = q_rej / (inp.cw_flow_lps * RHO_WATER * CP_WATER)
    cwr_calc = inp.cws_c + cw_dt
    if abs(cwr_calc - inp.cwr_c) > 0.5:
        warns.append(f"Heat-balance check: calculated CWR = {cwr_calc:.1f} °C vs entered "
                     f"CWR = {inp.cwr_c:.1f} °C (Δ {cwr_calc - inp.cwr_c:+.1f} K) — "
                     "check CW flow / CWR input.")

    # Pressure drops interpolated on % loading + pump hydraulic power (P[W]≈kPa·L/s)
    evap_pd   = interp(load_i, PERF_TABLE["load_pct"], PERF_TABLE["evap_pd_kpa"])
    cond_pd   = interp(load_i, PERF_TABLE["load_pct"], PERF_TABLE["cond_pd_kpa"])
    evap_pump = evap_pd * inp.chw_flow_lps / 1000.0
    cond_pump = cond_pd * inp.cw_flow_lps / 1000.0

    return ChillerResults(
        cooling_kw=q_kw, cooling_rt=q_rt, chw_dt_k=chw_dt,
        load_pct=load_pct, cop_base=cop_base, cop_adj=cop_adj,
        temp_correction_pct=corr_frac * 100.0,
        input_kw=p_kw, kw_per_rt=kwrt,
        heat_rejection_kw=q_rej, cw_dt_k=cw_dt, cwr_calc_c=cwr_calc,
        evap_pd_kpa=evap_pd, cond_pd_kpa=cond_pd,
        evap_pump_kw=evap_pump, cond_pump_kw=cond_pump,
        clamped=clamped, warnings=warns)


def part_load_table(inp: ChillerInputs) -> List[dict]:
    """Part-load sweep at the user's CHWS/CWS (design flows per vendor table)."""
    corr = 1.0 + _temp_correction_frac(inp)
    rows, t = [], PERF_TABLE
    for pct, cap, flow, epd, cpd in zip(t["load_pct"], t["capacity_kw"],
                                        t["evap_flow_lps"], t["evap_pd_kpa"],
                                        t["cond_pd_kpa"]):
        cop_b = interp(pct, t["load_pct"], t["cop"])
        cop_a = cop_b * corr
        rows.append(dict(load_pct=pct, capacity_kw=cap, capacity_rt=cap / KW_PER_RT,
                         input_kw=cap / cop_a, cop_base=cop_b, cop_adj=cop_a,
                         kw_per_rt=KW_PER_RT / cop_a, chw_flow_lps=flow,
                         evap_pd_kpa=epd, cond_pd_kpa=cpd))
    return rows


def input_kw_at_load(inp: ChillerInputs, load_pct: float) -> float:
    """Compressor kW at any % load (user CHWS/CWS correction applied)."""
    load_i = min(max(load_pct, MIN_LOAD_PCT), 100.0)
    cop = interp(load_i, PERF_TABLE["load_pct"], PERF_TABLE["cop"]) * (1.0 + _temp_correction_frac(inp))
    return FULL_LOAD_KW * load_pct / 100.0 / cop


def iplv_cop(inp: ChillerInputs, condenser: str = "fixed") -> float:
    """
    IPLV COP with AHRI 550/590 weighting (1/42/45/12 % at 100/75/50/25 %).
      condenser='fixed' -> user's CWS held constant at all part loads
      condenser='ahri'  -> AHRI part-load ECWT relief (29.44/23.89/18.33/18.33 °C)
    """
    chws_frac = COP_CORR_PER_K * (inp.chws_c - DESIGN["chws_c"])
    total = 0.0
    for pct, w in zip(IPLV_LOADS, IPLV_WEIGHTS):
        cws = AHRI_ECWT_C[pct] if condenser == "ahri" else inp.cws_c
        cop = interp(pct, PERF_TABLE["load_pct"], PERF_TABLE["cop"])
        cop *= 1.0 + chws_frac + COP_CORR_PER_K * (DESIGN["cws_c"] - cws)
        total += w / cop
    return 1.0 / total

# --------------------------------------------------------------- self test
if __name__ == "__main__":
    cases = [("Design point (defaults)", ChillerInputs()),
             ("CHWS = 7.7 C  (+1 K)     ", ChillerInputs(chws_c=7.7)),
             ("CWS  = 28.4 C  (-1 K)    ", ChillerInputs(cws_c=28.4)),
             ("~50 % part load          ", ChillerInputs(chw_flow_lps=125.7))]
    print(f"{'Case':<26}{'Q kW':>8}{'RT':>7}{'Load%':>7}{'COP':>7}{'kW/RT':>7}"
          f"{'P kW':>8}{'HR kW':>8}{'CWRcalc':>9}")
    for name, c in cases:
        errs = validate(c)
        if errs:
            print(f"{name:<26}INVALID: {'; '.join(errs)}"); continue
        r = simulate(c)
        print(f"{name:<26}{r.cooling_kw:8.0f}{r.cooling_rt:7.0f}{r.load_pct:7.1f}"
              f"{r.cop_adj:7.3f}{r.kw_per_rt:7.3f}{r.input_kw:8.1f}"
              f"{r.heat_rejection_kw:8.0f}{r.cwr_calc_c:9.2f}")