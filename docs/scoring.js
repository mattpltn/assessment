// Browser port of src/scoring (interpreter.py + pipeline.py). Keep this in
// sync with the Python implementation -- see tests/test_pipeline.py there
// for the reference values both implementations must reproduce.

const FormulaError = class extends Error {};

function tokenize(text) {
  const re = /\s*(?:(\d+\.\d+|\.\d+|\d+)|("[^"]*")|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|<>|=|<|>|,|\(|\)|\{|\}|\+|-|\*|\/))/;
  const tokens = [];
  let rest = text;
  while (rest.length > 0) {
    if (/^\s+$/.test(rest[0]) || rest[0] === " ") {
      rest = rest.slice(1);
      continue;
    }
    const m = re.exec(rest);
    if (!m || m.index !== 0 || m[0].trim() === "") {
      if (rest.trim() === "") break;
      throw new FormulaError(`cannot tokenize: ${rest.slice(0, 20)}`);
    }
    if (m[1] !== undefined) tokens.push(["num", m[1]]);
    else if (m[2] !== undefined) tokens.push(["str", m[2]]);
    else if (m[3] !== undefined) tokens.push(["ident", m[3]]);
    else tokens.push(["op", m[4]]);
    rest = rest.slice(m[0].length);
  }
  return tokens;
}

class Parser {
  constructor(tokens) {
    this.tokens = tokens;
    this.pos = 0;
  }
  peek() {
    return this.pos < this.tokens.length ? this.tokens[this.pos] : [null, null];
  }
  next() {
    const t = this.peek();
    this.pos += 1;
    return t;
  }
  expect(value) {
    const [, v] = this.next();
    if (v !== value) throw new FormulaError(`expected ${value}, got ${v}`);
  }

  parseList() {
    this.expect("{");
    const items = [];
    if (this.peek()[1] !== "}") {
      while (true) {
        const [kind, value] = this.next();
        if (kind !== "str") throw new FormulaError("expected string literal in list");
        items.push(value.slice(1, -1));
        if (this.peek()[1] === ",") {
          this.next();
          continue;
        }
        break;
      }
    }
    this.expect("}");
    return items;
  }

  parseArgs() {
    const args = [];
    if (this.peek()[1] === ")") return args;
    args.push(this.parseExpr());
    while (this.peek()[1] === ",") {
      this.next();
      args.push(this.parseExpr());
    }
    return args;
  }

  callFunc(name, args) {
    const upper = name.toUpperCase();
    if (upper === "IF") {
      const [cond, then, els] = args;
      return cond ? then : els;
    }
    if (upper === "IFS") {
      if (args.length % 2 !== 0) throw new FormulaError("IFS needs an even number of args");
      for (let i = 0; i < args.length; i += 2) {
        if (args[i]) return args[i + 1];
      }
      throw new FormulaError("IFS: no condition matched");
    }
    if (upper === "LOWER") return String(args[0]).toLowerCase();
    if (upper === "YEAR") {
      const v = args[0];
      return v instanceof Date ? v.getFullYear() : parseInt(v, 10);
    }
    if (upper === "YEARFRAC") {
      const toDate = (v) => (v instanceof Date ? v : new Date(v));
      const start = toDate(args[0]);
      const end = toDate(args[1]);
      return (end - start) / (1000 * 60 * 60 * 24 * 365.25);
    }
    if (upper === "TODAY") return new Date();
    if (upper === "TRUE") return true;
    if (upper === "MAX") return Math.max(...args);
    if (upper === "MIN") return Math.min(...args);
    throw new FormulaError(`unsupported function: ${upper}`);
  }

  parsePrimary() {
    const [kind, value] = this.peek();
    if (value === "(") {
      this.next();
      const v = this.parseExpr();
      this.expect(")");
      return v;
    }
    if (value === "{") return this.parseList();
    if (kind === "num") {
      this.next();
      return parseFloat(value);
    }
    if (kind === "str") {
      this.next();
      return value.slice(1, -1);
    }
    if (kind === "ident") {
      this.next();
      const name = value;
      if (name === "TRUE" ) {
        if (this.peek()[1] === "(") {
          this.next();
          this.expect(")");
        }
        return true;
      }
      if (this.peek()[1] === "(") {
        this.next();
        if (name.toUpperCase() === "MATCH") {
          const needle = this.parseExpr();
          this.expect(",");
          const haystack = this.peek()[1] === "{" ? this.parseList() : this.parseExpr();
          this.expect(",");
          this.parseExpr(); // match-type, always exact here
          this.expect(")");
          const idx = haystack.indexOf(needle);
          if (idx === -1) throw new FormulaError(`MATCH: ${needle} not found`);
          return idx + 1;
        }
        if (name.toUpperCase() === "CHOOSE") {
          const idx = this.parseExpr();
          const choices = [];
          while (this.peek()[1] === ",") {
            this.next();
            choices.push(this.parseExpr());
          }
          this.expect(")");
          return choices[idx - 1];
        }
        const args = this.parseArgs();
        this.expect(")");
        return this.callFunc(name, args);
      }
      throw new FormulaError(`unknown identifier: ${name}`);
    }
    throw new FormulaError(`unexpected token: ${value}`);
  }

  parseUnary() {
    if (this.peek()[1] === "-") {
      this.next();
      return -this.parseUnary();
    }
    return this.parsePrimary();
  }

  parseTerm() {
    let left = this.parseUnary();
    while (this.peek()[1] === "*" || this.peek()[1] === "/") {
      const [, op] = this.next();
      const right = this.parseUnary();
      left = op === "*" ? left * right : left / right;
    }
    return left;
  }

  parseAdditive() {
    let left = this.parseTerm();
    while (this.peek()[1] === "+" || this.peek()[1] === "-") {
      const [, op] = this.next();
      const right = this.parseTerm();
      left = op === "+" ? left + right : left - right;
    }
    return left;
  }

  parseExpr() {
    const left = this.parseAdditive();
    const compareOps = {
      "<=": (a, b) => a <= b,
      ">=": (a, b) => a >= b,
      "<>": (a, b) => a !== b,
      "=": (a, b) => a === b,
      "<": (a, b) => a < b,
      ">": (a, b) => a > b,
    };
    const [, value] = this.peek();
    if (value in compareOps) {
      this.next();
      const right = this.parseAdditive();
      return compareOps[value](left, right);
    }
    return left;
  }
}

function evaluateFormula(formula, rawValue) {
  if (rawValue === null || rawValue === undefined || rawValue === "") {
    throw new FormulaError("blank value");
  }
  let isNumber = typeof rawValue === "number";
  let value = rawValue;
  if (!isNumber) {
    const asNum = Number(rawValue);
    if (!Number.isNaN(asNum) && rawValue.trim() !== "") {
      value = asNum;
      isNumber = true;
    }
  }
  const literal = isNumber ? String(value) : `"${value}"`;
  const text = formula.split("{v}").join(literal).replace(/^=/, "");
  const parser = new Parser(tokenize(text));
  const result = parser.parseExpr();
  return typeof result === "boolean" ? (result ? 1 : 0) : Number(result);
}

// ---- pipeline ----

function normalize(model, answers) {
  const scores = {};
  for (const fid of model.fieldOrder) {
    const field = model.fields[fid];
    const raw = answers[fid];
    if (!field.formula || raw === undefined || raw === null || raw === "") {
      scores[fid] = null;
      continue;
    }
    try {
      scores[fid] = evaluateFormula(field.formula, raw);
    } catch (e) {
      if (e instanceof FormulaError) scores[fid] = null;
      else throw e;
    }
  }
  return scores;
}

function groupScore(fieldScores, weights) {
  const pairs = [];
  for (const [fid, w] of Object.entries(weights)) {
    const v = fieldScores[fid];
    if (v !== null && v !== undefined) pairs.push([v, w]);
  }
  if (pairs.length === 0) return null;
  const den = pairs.reduce((s, [, w]) => s + Math.abs(w), 0);
  if (den === 0) return null;
  const num = pairs.reduce((s, [v, w]) => s + v * w, 0);
  const raw = num / den;
  return Math.max(0, Math.min(4, (raw + 4) / 2));
}

function weightedAvg(scores, weights) {
  const pairs = [];
  for (let i = 0; i < scores.length; i++) {
    if (scores[i] !== null && scores[i] !== undefined) pairs.push([scores[i], weights[i]]);
  }
  if (pairs.length === 0) return 0;
  const den = pairs.reduce((s, [, w]) => s + w, 0);
  if (den === 0) return 0;
  const num = pairs.reduce((s, [v, w]) => s + v * w, 0);
  return num / den;
}

function scoreA(model, groupAScores) {
  const weights = model.group_a.map((g) => g.weight);
  return weightedAvg(groupAScores, weights);
}

function scoreB(model, scoreAValue, groupBScores) {
  const sequence = [scoreAValue, ...groupBScores.slice(0, 11)];
  const weights = model.group_b.map((g) => g.weight);
  return weightedAvg(sequence, weights) * 25;
}

function outcomeC(model, fieldScores, groupAScores, groupDScores, scoreAForBlend, groupBScoresForBlend) {
  const aValues = {};
  model.group_a.forEach((g, i) => (aValues[g.id] = groupAScores[i]));

  const bIds = model.group_b.map((g) => g.id);
  const bSequence = [scoreAForBlend, ...groupBScoresForBlend.slice(0, 11)];
  const bValues = {};
  bIds.forEach((id, i) => (bValues[id] = bSequence[i] ?? 0));

  const dValues = {};
  model.group_d.forEach((g, i) => (dValues[g.id] = groupDScores[i]));

  const optionScores = {};
  for (const option of model.options) {
    let num = 0;
    let den = 0;
    for (const [fid, weight] of Object.entries(option.weights)) {
      let value;
      if (fid in aValues) value = aValues[fid];
      else if (fid in bValues) value = bValues[fid];
      else if (fid in dValues) value = dValues[fid];
      else value = fieldScores[fid];
      if (value === null || value === undefined) value = 0;
      const adjusted = weight >= 0 ? value : 4 - value;
      num += adjusted * Math.abs(weight);
      den += Math.abs(weight);
    }
    optionScores[option.id] = den ? num / den : 0;
  }

  const ranked = Object.entries(optionScores).sort((a, b) => b[1] - a[1]);
  const [bestId, bestScore] = ranked[0];
  const secondScore = ranked.length > 1 ? ranked[1][1] : 0;
  const certainty = (bestScore - secondScore) / 4;
  return { outcome: bestId, certainty, optionScores };
}

function scoreOne(model, answers) {
  const fieldScores = normalize(model, answers);
  const groupAScores = model.group_a.map((g) => groupScore(fieldScores, g.fields));
  const groupBScores = model.group_b.slice(0, 11).map((g) => groupScore(fieldScores, g.fields));
  const groupDScores = model.group_d.map((g) => groupScore(fieldScores, g.fields));
  const a = scoreA(model, groupAScores);
  const b = scoreB(model, a, groupBScores);
  return { fieldScores, groupAScores, groupBScores, groupDScores, scoreA: a, scoreB: b };
}

// See KNOWN_ISSUES.md: this used to inherit a batch-order-dependent bug
// from the reference model. Fixed by default -- each item is blended
// against its own Score A / group_b scores. Pass { useOwnBlend: false } to
// reproduce the original (buggy) reference-model behavior instead, e.g.
// for side-by-side comparison.
function evaluateBatch(model, answerRows, { useOwnBlend = true } = {}) {
  const items = answerRows.map((answers) => scoreOne(model, answers));

  let blendSource;
  if (useOwnBlend) {
    blendSource = items.map((item) => [item.scoreA, item.groupBScores]);
  } else {
    const order = items
      .map((_, i) => i)
      .sort((i, j) => items[j].scoreB - items[i].scoreB);
    const bySortPosition = order.map((i) => [items[i].scoreA, items[i].groupBScores]);
    blendSource = items.map((_, i) => bySortPosition[i]);
  }

  return items.map((item, i) => {
    const [blendA, blendB] = blendSource[i];
    const { outcome, certainty, optionScores } = outcomeC(
      model,
      item.fieldScores,
      item.groupAScores,
      item.groupDScores,
      blendA,
      blendB
    );
    return { scoreA: item.scoreA, scoreB: item.scoreB, outcomeC: outcome, certainty, optionScores };
  });
}

function buildModel(raw) {
  const fields = {};
  const fieldOrder = raw.fields.map((f) => f.id);
  raw.fields.forEach((f) => (fields[f.id] = f));
  return { fields, fieldOrder, group_a: raw.group_a, group_b: raw.group_b, group_d: raw.group_d, options: raw.options };
}

window.Scoring = { buildModel, evaluateBatch, evaluateFormula, normalize, scoreOne, FormulaError };
