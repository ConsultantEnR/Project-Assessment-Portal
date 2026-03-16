/**
 * financial_model.js
 * Self-contained financial model for renewable energy investment projects.
 * Exposed as window.FinancialModel via IIFE pattern.
 *
 * Covers PV + BESS projects with:
 *  - Annual P&L over project lifetime
 *  - Monthly cashflow breakdown
 *  - KPIs: IRR (project & equity), NPV, DSCR
 *  - Multi-site aggregation helper
 */
(function (global) {
    'use strict';

    // ─────────────────────────────────────────────
    //  CONSTANTS
    // ─────────────────────────────────────────────

    /** Default financial & structural parameters */
    const DEFAULTS = {
        electricityPrice:      85,    // €/MWh
        electricityEscalation: 1.5,   // %/an
        bessSpreadPrice:       30,    // €/MWh
        inflation:             2.0,   // %/an
        tax:                   25.0,  // %
        wacc:                  8.0,   // %
        debtPercent:           70,    // % of capex financed by debt
        seniorRate:            4.5,   // %/an
        debtDuration:          18,    // years
        dsraMonths:            6,     // months of DSRA reserve
        dscrTarget:            1.15,  // minimum DSCR covenant
    };

    /**
     * Monthly irradiation normalisation factors (sum = 12).
     * Calibrated for southern Europe / Iberian Peninsula.
     */
    const MONTHLY_FACTORS = [
        0.52, 0.63, 0.86, 1.00, 1.15, 1.26,
        1.30, 1.22, 1.02, 0.78, 0.57, 0.49,
    ];

    // ─────────────────────────────────────────────
    //  MATH HELPERS
    // ─────────────────────────────────────────────

    /**
     * Net Present Value of a series of cashflows (starting at t=1).
     * @param {number} rate  - discount rate (decimal, e.g. 0.08 for 8%)
     * @param {number[]} cfs - cashflows at t=1, t=2, …, t=n
     * @returns {number}
     */
    function npv(rate, cfs) {
        let result = 0;
        for (let i = 0; i < cfs.length; i++) {
            result += cfs[i] / Math.pow(1 + rate, i + 1);
        }
        return result;
    }

    /**
     * Polynomial evaluation of NPV at a given rate (includes t=0 term).
     * @param {number[]} cfs - full cashflow series including CF at t=0
     * @param {number}   r   - rate (decimal)
     */
    function _npvFull(cfs, r) {
        let val = 0;
        for (let i = 0; i < cfs.length; i++) {
            val += cfs[i] / Math.pow(1 + r, i);
        }
        return val;
    }

    /**
     * Derivative d(NPV)/dr for Newton-Raphson.
     */
    function _dnpvFull(cfs, r) {
        let val = 0;
        for (let i = 1; i < cfs.length; i++) {
            val -= i * cfs[i] / Math.pow(1 + r, i + 1);
        }
        return val;
    }

    /**
     * Internal Rate of Return — Newton-Raphson with bisection fallback.
     * Returns NaN if no real positive or zero root is found.
     * @param {number[]} cfs   - cashflows at t=0, t=1, …, t=n  (t=0 is typically negative)
     * @param {number}  [guess] - initial guess (decimal, default 0.10)
     * @returns {number} IRR as decimal
     */
    function irr(cfs, guess) {
        if (!cfs || cfs.length < 2) return NaN;

        // Check sign change exists — necessary for a real IRR
        let hasPos = false, hasNeg = false;
        for (const c of cfs) {
            if (c > 0) hasPos = true;
            if (c < 0) hasNeg = true;
        }
        if (!hasPos || !hasNeg) return NaN;

        const MAX_ITER = 200;
        const TOL      = 1e-9;

        // ── Newton-Raphson ──────────────────────────────────────
        let r = (guess !== undefined && isFinite(guess)) ? guess : 0.10;
        for (let i = 0; i < MAX_ITER; i++) {
            const f  = _npvFull(cfs, r);
            const df = _dnpvFull(cfs, r);
            if (Math.abs(df) < 1e-15) break;            // derivative near zero → switch
            const rNew = r - f / df;
            if (rNew < -0.9999) {
                // stepped into invalid territory — clamp and continue
                r = (r - 0.9999) / 2;
                continue;
            }
            if (Math.abs(rNew - r) < TOL) return rNew;  // converged
            r = rNew;
        }

        // ── Bisection fallback ──────────────────────────────────
        // Find a bracket [lo, hi] such that NPV changes sign
        let lo = -0.9999, hi = 10.0;  // search from -100% to +1000%

        // Narrow the bracket adaptively
        const fLo = _npvFull(cfs, lo);
        const fHi = _npvFull(cfs, hi);

        // If no sign change in [lo, hi], try tighter positive range
        if (fLo * fHi > 0) {
            // Scan for sign change in [0, 5] with 500 steps
            const step = 0.01;
            let prev = _npvFull(cfs, 0);
            for (let rx = step; rx <= 5.0; rx += step) {
                const cur = _npvFull(cfs, rx);
                if (prev * cur <= 0) { lo = rx - step; hi = rx; break; }
                prev = cur;
            }
            if (_npvFull(cfs, lo) * _npvFull(cfs, hi) > 0) return NaN; // give up
        }

        for (let i = 0; i < MAX_ITER; i++) {
            const mid = (lo + hi) / 2;
            const fMid = _npvFull(cfs, mid);
            if (Math.abs(fMid) < TOL || (hi - lo) / 2 < TOL) return mid;
            if (_npvFull(cfs, lo) * fMid < 0) hi = mid;
            else lo = mid;
        }

        return (lo + hi) / 2;
    }

    /**
     * Annuity payment (like Excel PMT).
     * @param {number} rate    - periodic interest rate (decimal)
     * @param {number} nper    - total number of periods
     * @param {number} pv      - present value (loan amount, positive)
     * @returns {number} payment per period (positive)
     */
    function pmt(rate, nper, pv) {
        if (rate === 0) return pv / nper;
        return pv * rate * Math.pow(1 + rate, nper) / (Math.pow(1 + rate, nper) - 1);
    }

    // ─────────────────────────────────────────────
    //  FORMATTING HELPERS
    // ─────────────────────────────────────────────

    /**
     * Format a euro amount with k€ / M€ suffix (locale fr-FR).
     * @param {number} amount
     * @returns {string}
     */
    function formatEur(amount) {
        if (amount === null || amount === undefined || !isFinite(amount)) return '—';
        const abs = Math.abs(amount);
        const sign = amount < 0 ? '−' : '';
        if (abs >= 1e9) {
            return sign + (abs / 1e9).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' Md€';
        }
        if (abs >= 1e6) {
            return sign + (abs / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' M€';
        }
        if (abs >= 1e3) {
            return sign + (abs / 1e3).toLocaleString('fr-FR', { maximumFractionDigits: 1 }) + ' k€';
        }
        return sign + abs.toLocaleString('fr-FR', { maximumFractionDigits: 0 }) + ' €';
    }

    /**
     * Format a percentage value with 2 decimal places.
     * @param {number} value - already multiplied by 100 (e.g. 8.5 for 8.5%)
     * @returns {string}
     */
    function formatPct(value) {
        if (value === null || value === undefined || !isFinite(value)) return '—';
        return value.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' %';
    }

    // ─────────────────────────────────────────────
    //  MAIN COMPUTE FUNCTION
    // ─────────────────────────────────────────────

    /**
     * Compute full financial model for a single site.
     *
     * @param {Object} site          - site technical & cost data
     * @param {Object} [projectParams] - financial parameters (overrides DEFAULTS)
     * @returns {{ monthly: Object[], annual: Object[], kpis: Object, _params: Object }}
     */
    function compute(site, projectParams) {

        // ── Merge parameters with defaults ─────────────────────
        const p = Object.assign({}, DEFAULTS, projectParams || {});

        // ── Site fields with safe fallbacks ────────────────────
        const hasPV   = site.hasPV  !== false;  // default true
        const hasBESS = !!site.hasBESS;

        const pvCap      = hasPV ? (site.pvCapacity    || 0) : 0;   // kWc
        const pvProdP90  = hasPV ? (site.pvProdP90     || 0) : 0;   // kWh/kWc/an
        const pvDeg      = hasPV ? (site.pvDegradation || 0) : 0;   // %/an
        const lifetime   = site.pvLifetime || 25;                    // years

        const bessPow    = hasBESS ? (site.bessPower        || 0) : 0;  // kW
        const bessCap    = hasBESS ? (site.bessCapacity     || 0) : 0;  // kWh
        const bessDeg    = hasBESS ? (site.bessDegradation  || 0) : 0;  // %/an
        const bessMinSoH = hasBESS ? (site.bessMinSoH       || 70) : 70; // %
        const bessCpD    = hasBESS ? (site.bessCyclesPerDay || 1)  : 1;
        const bessEffDC  = hasBESS ? (site.bessEffDCAC      || 95) : 95; // %

        // OPEX per-unit rates
        const omPv    = site.omPv    || 0;  // €/kWc/an
        const insPv   = site.insPv   || 0;
        const amPv    = site.amPv    || 0;
        const rmPv    = site.rmPv    || 0;
        const omBess  = site.omBess  || 0;  // €/kW/an
        const insBess = site.insBess || 0;
        const amBess  = site.amBess  || 0;
        const rmBess  = site.rmBess  || 0;
        const rentEuros = site.rentEuros || 0; // €/an

        // CAPEX
        const capexPv   = hasPV   ? (site.capexPv   || 0) : 0;
        const capexBess = hasBESS ? (site.capexBess || 0) : 0;
        const totalCapex = capexPv + capexBess;

        // Financing
        const debtFrac  = p.debtPercent / 100;
        const debt      = totalCapex * debtFrac;
        const equity    = totalCapex * (1 - debtFrac);

        // Monthly debt payment (annuity)
        const monthlyRate = p.seniorRate / 100 / 12;
        const nMonths     = p.debtDuration * 12;
        const monthlyPmt  = debt > 0 ? pmt(monthlyRate, nMonths, debt) : 0;
        const annualPmt   = monthlyPmt * 12;

        // Straight-line depreciation
        const depreciation = totalCapex / lifetime;

        // ── Annual loop ─────────────────────────────────────────
        const annual  = [];
        const monthly = [];

        let debtRemaining = debt;

        for (let y = 1; y <= lifetime; y++) {

            // -- Production -----------------------------------------
            const degradFactor = Math.pow(1 - pvDeg / 100, y - 1);
            const annualProd   = pvCap * pvProdP90 * degradFactor; // kWh

            // -- BESS State-of-Health -----------------------------------
            const bessSOHFactor = Math.max(
                bessMinSoH / 100,
                Math.pow(1 - bessDeg / 100, y - 1)
            );
            const bessAnnualDischarge = hasBESS
                ? bessCap * bessSOHFactor * (bessEffDC / 100) * bessCpD * 365
                : 0; // kWh

            // -- Prices -----------------------------------------------
            const elecEscFactor = Math.pow(1 + p.electricityEscalation / 100, y - 1);
            const elecPrice     = p.electricityPrice * elecEscFactor; // €/MWh

            // -- Revenue ----------------------------------------------
            const pvRevenue   = hasPV   ? annualProd             * elecPrice / 1000 : 0;
            const bessRevenue = hasBESS ? bessAnnualDischarge     * p.bessSpreadPrice * elecEscFactor / 1000 : 0;
            const totalRevenue = pvRevenue + bessRevenue;

            // -- OPEX -------------------------------------------------
            const inflFactor = Math.pow(1 + p.inflation / 100, y - 1);
            const opexBase   = (omPv + insPv + amPv + rmPv) * pvCap
                             + (omBess + insBess + amBess + rmBess) * bessPow
                             + rentEuros;
            const totalOpex  = opexBase * inflFactor;

            // -- EBITDA -----------------------------------------------
            const ebitda = totalRevenue - totalOpex;

            // -- EBIT -------------------------------------------------
            const ebit = ebitda - depreciation;

            // -- Debt service -----------------------------------------
            const inDebtPeriod   = y <= p.debtDuration && debt > 0;
            const annualInterest = inDebtPeriod ? debtRemaining * (p.seniorRate / 100) : 0;

            // Principal: annuity total - interest, floored at 0, capped at remaining
            let annualPrincipal = 0;
            if (inDebtPeriod) {
                annualPrincipal = Math.min(
                    Math.max(annualPmt - annualInterest, 0),
                    debtRemaining
                );
            }
            const debtServiceY = inDebtPeriod ? annualPmt : 0;

            // -- Income statement ------------------------------------
            const ebt        = ebit - annualInterest;
            const taxAmount  = Math.max(0, ebt) * (p.tax / 100);
            const netIncome  = ebt - taxAmount;

            // -- Cashflows -------------------------------------------
            const cfads      = ebitda - taxAmount;
            const fcfProject = cfads;
            const fcfEquity  = cfads - debtServiceY;

            // -- DSCR -------------------------------------------------
            const dscr = inDebtPeriod ? cfads / debtServiceY : null;

            // -- Record -----------------------------------------------
            const debtRemainingSnapshot = debtRemaining;
            debtRemaining = Math.max(0, debtRemaining - annualPrincipal);

            annual.push({
                year:           y,
                production:     annualProd,
                pvRevenue:      pvRevenue,
                bessRevenue:    bessRevenue,
                totalRevenue:   totalRevenue,
                totalOpex:      totalOpex,
                ebitda:         ebitda,
                depreciation:   depreciation,
                ebit:           ebit,
                financialCharge: annualInterest,
                ebt:            ebt,
                taxAmount:      taxAmount,
                netIncome:      netIncome,
                cfads:          cfads,
                debtService:    debtServiceY,
                dscr:           dscr,
                fcfProject:     fcfProject,
                fcfEquity:      fcfEquity,
                debtRemaining:  debtRemainingSnapshot,
                elecPrice:      elecPrice,
            });

            // ── Monthly breakdown for this year ───────────────────
            for (let m = 0; m < 12; m++) {
                const mFactor  = MONTHLY_FACTORS[m];
                const mProd    = annualProd   * mFactor / 12;
                const mPVRev   = pvRevenue    * mFactor / 12;
                const mBessRev = bessRevenue  / 12;
                const mRevenue = mPVRev + mBessRev;
                const mOpex    = totalOpex    / 12;
                const mEbitda  = mRevenue - mOpex;
                const mTax     = taxAmount    / 12;
                const mCfads   = mEbitda - mTax;
                const mDebtSvc = inDebtPeriod ? monthlyPmt : 0;
                const mDscr    = mDebtSvc > 0
                    ? (mCfads * 12) / (mDebtSvc * 12)
                    : null;
                const mFcf     = mCfads - mDebtSvc;
                const period   = (y - 1) * 12 + m + 1;

                monthly.push({
                    year:       y,
                    month:      m + 1,
                    period:     period,
                    production: mProd,
                    pvRevenue:  mPVRev,
                    bessRevenue: mBessRev,
                    revenue:    mRevenue,
                    opex:       mOpex,
                    ebitda:     mEbitda,
                    interest:   annualInterest / 12,
                    tax:        mTax,
                    cfads:      mCfads,
                    debtSvc:    mDebtSvc,
                    dscr:       mDscr,
                    fcf:        mFcf,
                });
            }
        }

        // ── KPI computation ─────────────────────────────────────

        // IRR
        const projectCFs = [-totalCapex, ...annual.map(a => a.cfads)];
        const equityCFs  = [-equity,     ...annual.map(a => a.fcfEquity)];

        const projectIRR_dec = irr(projectCFs, 0.08);
        const equityIRR_dec  = irr(equityCFs,  0.10);

        const projectIRR = isFinite(projectIRR_dec) ? projectIRR_dec * 100 : NaN;
        const equityIRR  = isFinite(equityIRR_dec)  ? equityIRR_dec  * 100 : NaN;

        // NPV
        const van = -totalCapex + npv(p.wacc / 100, annual.map(a => a.cfads));

        // DSCR stats (debt period only)
        const dscrValues = annual.filter(a => a.dscr !== null).map(a => a.dscr);
        const dscrMin    = dscrValues.length ? Math.min(...dscrValues) : null;
        const dscrAvg    = dscrValues.length
            ? dscrValues.reduce((s, v) => s + v, 0) / dscrValues.length
            : null;

        const kpis = {
            totalCapex:    totalCapex,
            debt:          debt,
            equity:        equity,
            debtPercent:   p.debtPercent,
            lifetime:      lifetime,
            projectIRR:    projectIRR,
            equityIRR:     equityIRR,
            van:           van,
            dscrMin:       dscrMin,
            dscrAvg:       dscrAvg,
            annualRevY1:   annual[0] ? annual[0].totalRevenue : 0,
            annualOpexY1:  annual[0] ? annual[0].totalOpex    : 0,
            ebitdaY1:      annual[0] ? annual[0].ebitda       : 0,
        };

        return {
            monthly:  monthly,
            annual:   annual,
            kpis:     kpis,
            _params:  p,
        };
    }

    // ─────────────────────────────────────────────
    //  MULTI-SITE AGGREGATION
    // ─────────────────────────────────────────────

    /**
     * Aggregate results from multiple sites.
     * Sums annual and monthly cashflows by year/period,
     * then recomputes IRR, NPV and DSCR at portfolio level.
     *
     * @param {Array} siteResults - array of compute() return values
     * @returns {{ monthly: Object[], annual: Object[], kpis: Object }}
     */
    function aggregateSites(siteResults) {
        if (!siteResults || siteResults.length === 0) return null;

        const wacc = siteResults[0]._params.wacc;

        // ── Sum annual records ───────────────────────────────────
        const annualMap = {};
        const ANNUAL_SUM_FIELDS = [
            'production', 'pvRevenue', 'bessRevenue', 'totalRevenue',
            'totalOpex', 'ebitda', 'depreciation', 'ebit',
            'financialCharge', 'ebt', 'taxAmount', 'netIncome',
            'cfads', 'debtService', 'fcfProject', 'fcfEquity', 'debtRemaining',
        ];

        for (const res of siteResults) {
            for (const row of res.annual) {
                if (!annualMap[row.year]) {
                    annualMap[row.year] = { year: row.year };
                    for (const f of ANNUAL_SUM_FIELDS) annualMap[row.year][f] = 0;
                    annualMap[row.year].elecPrice = row.elecPrice; // from first site
                }
                for (const f of ANNUAL_SUM_FIELDS) {
                    annualMap[row.year][f] += row[f] || 0;
                }
            }
        }

        const annual = Object.values(annualMap).sort((a, b) => a.year - b.year);

        // Recompute DSCR for aggregated rows
        for (const row of annual) {
            row.dscr = row.debtService > 0 ? row.cfads / row.debtService : null;
        }

        // ── Sum monthly records ──────────────────────────────────
        const monthlyMap = {};
        const MONTHLY_SUM_FIELDS = [
            'production', 'pvRevenue', 'bessRevenue', 'revenue',
            'opex', 'ebitda', 'interest', 'tax',
            'cfads', 'debtSvc', 'fcf',
        ];

        for (const res of siteResults) {
            for (const row of res.monthly) {
                const key = row.period;
                if (!monthlyMap[key]) {
                    monthlyMap[key] = {
                        year: row.year, month: row.month, period: row.period,
                    };
                    for (const f of MONTHLY_SUM_FIELDS) monthlyMap[key][f] = 0;
                }
                for (const f of MONTHLY_SUM_FIELDS) {
                    monthlyMap[key][f] += row[f] || 0;
                }
            }
        }

        const monthly = Object.values(monthlyMap).sort((a, b) => a.period - b.period);

        // Recompute monthly DSCR
        for (const row of monthly) {
            row.dscr = row.debtSvc > 0
                ? (row.cfads * 12) / (row.debtSvc * 12)
                : null;
        }

        // ── Aggregate KPIs ───────────────────────────────────────
        const totalCapex = siteResults.reduce((s, r) => s + r.kpis.totalCapex, 0);
        const debt       = siteResults.reduce((s, r) => s + r.kpis.debt,       0);
        const equity     = siteResults.reduce((s, r) => s + r.kpis.equity,     0);

        const projectCFs = [-totalCapex, ...annual.map(a => a.cfads)];
        const equityCFs  = [-equity,     ...annual.map(a => a.fcfEquity)];

        const projectIRR_dec = irr(projectCFs, 0.08);
        const equityIRR_dec  = irr(equityCFs,  0.10);

        const van = -totalCapex + npv(wacc / 100, annual.map(a => a.cfads));

        const dscrValues = annual.filter(a => a.dscr !== null).map(a => a.dscr);
        const dscrMin    = dscrValues.length ? Math.min(...dscrValues) : null;
        const dscrAvg    = dscrValues.length
            ? dscrValues.reduce((s, v) => s + v, 0) / dscrValues.length
            : null;

        return {
            monthly: monthly,
            annual:  annual,
            kpis: {
                totalCapex:   totalCapex,
                debt:         debt,
                equity:       equity,
                lifetime:     annual.length,
                projectIRR:   isFinite(projectIRR_dec) ? projectIRR_dec * 100 : NaN,
                equityIRR:    isFinite(equityIRR_dec)  ? equityIRR_dec  * 100 : NaN,
                van:          van,
                dscrMin:      dscrMin,
                dscrAvg:      dscrAvg,
            },
        };
    }

    // ─────────────────────────────────────────────
    //  PUBLIC API
    // ─────────────────────────────────────────────

    const FinancialModel = {
        compute:        compute,
        aggregateSites: aggregateSites,
        npv:            npv,
        irr:            irr,
        DEFAULTS:       DEFAULTS,
        MONTHLY_FACTORS: MONTHLY_FACTORS,
        formatEur:      formatEur,
        formatPct:      formatPct,
    };

    // Expose globally
    global.FinancialModel = FinancialModel;

}(typeof window !== 'undefined' ? window : this));
