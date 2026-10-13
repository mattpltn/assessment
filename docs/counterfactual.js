// Browser port of src/scoring/counterfactual.py -- given a scored item,
// find the smallest set of answer changes that flips Outcome C to a
// target option. Keep logic in sync with the Python version.

function enumerateLevels(field) {
  const formula = field.formula;
  if (!formula) return [];
  const flat = formula.replace(/\n/g, " ");

  let probes = [];
  if (/\{(?:"opt\d+",?)+\}/.test(flat)) {
    const n = (flat.match(/"opt\d+"/g) || []).length;
    for (let i = 1; i <= n; i++) probes.push(`opt${i}`);
  } else if (/YEAR\(TODAY\(\)\)-\{v\}/.test(flat)) {
    const thisYear = new Date().getFullYear();
    probes = [1, 3, 6, 11, 21].map((off) => thisYear - off);
  } else if (/YEARFRAC\(\{v\},TODAY\(\)\)/.test(flat)) {
    const today = new Date();
    probes = [30, 400, 1200, 3000, 4500].map((d) => {
      const dt = new Date(today);
      dt.setDate(dt.getDate() - d);
      return dt.toISOString().slice(0, 10);
    });
  } else if (/\{v\}\s*(?:>=|>|<=|<)\s*-?\d+(?:\.\d+)?/.test(flat)) {
    const nums = [...flat.matchAll(/\{v\}\s*(?:>=|>|<=|<)\s*(-?\d+(?:\.\d+)?)/g)].map((m) => parseFloat(m[1]));
    const uniq = [...new Set(nums)].sort((a, b) => a - b);
    for (const n of uniq) {
      probes.push(n, n + 1, Number.isInteger(n) ? n - 1 : Math.round((n - 0.01) * 100) / 100);
    }
    probes.push(0);
  } else {
    probes = ["yes", "no"];
  }

  const seen = new Map();
  for (const raw of probes) {
    let score;
    try {
      score = Scoring.evaluateFormula(formula, raw);
    } catch (e) {
      if (e instanceof Scoring.FormulaError) continue;
      throw e;
    }
    if (!seen.has(score)) seen.set(score, raw);
  }
  return [...seen.entries()].map(([score, raw]) => [raw, score]);
}

function currentScore(field, raw) {
  if (!field.formula || raw === undefined || raw === null || raw === "") return null;
  try {
    return Scoring.evaluateFormula(field.formula, raw);
  } catch (e) {
    if (e instanceof Scoring.FormulaError) return null;
    throw e;
  }
}

function candidateChanges(model, answers) {
  const out = [];
  for (const field of Object.values(model.fields)) {
    if (!field.formula) continue;
    const fid = field.id;
    const oldRaw = answers[fid];
    const oldScore = currentScore(field, oldRaw);
    for (const [newRaw, newScore] of enumerateLevels(field)) {
      if (newScore !== oldScore) out.push({ fid, oldRaw, newRaw, oldScore, newScore });
    }
  }
  return out;
}

function* combinations(arr, r) {
  const n = arr.length;
  if (r > n) return;
  const idx = Array.from({ length: r }, (_, i) => i);
  while (true) {
    yield idx.map((i) => arr[i]);
    let i = r - 1;
    while (i >= 0 && idx[i] === n - r + i) i--;
    if (i < 0) return;
    idx[i]++;
    for (let j = i + 1; j < r; j++) idx[j] = idx[j - 1] + 1;
  }
}

function scoreOnce(model, answers) {
  return Scoring.evaluateBatch(model, [answers])[0];
}

function findMinChanges(model, answers, targetOption, maxDepth = 3, beamWidth = 25) {
  const baseline = scoreOnce(model, answers);
  if (baseline.outcomeC === targetOption) {
    return { depth: 0, solutions: [], message: "already at target" };
  }

  const candidates = candidateChanges(model, answers);
  const depth1Hits = [];
  const leverage = [];

  for (const cand of candidates) {
    const trial = { ...answers, [cand.fid]: cand.newRaw };
    const result = scoreOnce(model, trial);
    const targetScore = result.optionScores[targetOption];
    const bestOther = Math.max(...Object.entries(result.optionScores).filter(([k]) => k !== targetOption).map(([, v]) => v));
    leverage.push([targetScore - bestOther, cand]);
    if (result.outcomeC === targetOption) depth1Hits.push([cand]);
  }

  if (depth1Hits.length) return { depth: 1, solutions: depth1Hits };

  leverage.sort((a, b) => b[0] - a[0]);
  const shortlist = leverage.slice(0, beamWidth).map(([, cand]) => cand);

  for (let depth = 2; depth <= maxDepth; depth++) {
    const hits = [];
    for (const combo of combinations(shortlist, depth)) {
      const trial = { ...answers };
      for (const c of combo) trial[c.fid] = c.newRaw;
      const result = scoreOnce(model, trial);
      if (result.outcomeC === targetOption) hits.push(combo);
    }
    if (hits.length) return { depth, solutions: hits };
  }

  return { depth: null, solutions: [], message: `no solution found within depth ${maxDepth} / beam ${beamWidth}` };
}

window.Counterfactual = { findMinChanges };
