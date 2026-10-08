// Ingests a raw survey-tool export (semicolon- or comma-delimited, quoted
// fields, original field codes, tool bookkeeping columns) and converts it
// into the Q01..Q69 answer-row shape scoring.js expects.
//
// kobo_map.json carries the real-world field codes and option-label text
// needed to recognize raw answers -- see the repo README for why that
// trade-off was made deliberately, with the user's sign-off, rather than
// kept out of the public page.

const KOBO_META_PREFIXES = ["_", "meta/", "__"];

function sniffDelimiter(headerLine) {
  const semi = (headerLine.match(/;/g) || []).length;
  const comma = (headerLine.match(/,/g) || []).length;
  return semi > comma ? ";" : ",";
}

function parseDelimitedCsv(text, delimiter) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  const pushField = () => {
    row.push(field);
    field = "";
  };
  const pushRow = () => {
    pushField();
    rows.push(row);
    row = [];
  };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
      continue;
    }
    if (c === '"') {
      inQuotes = true;
    } else if (c === delimiter) {
      pushField();
    } else if (c === "\n") {
      if (field !== "" || row.length > 0) pushRow();
    } else if (c === "\r") {
      // skip, \n handles the line break
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length > 0) pushRow();
  return rows;
}

function looksLikeRawExport(headerRow) {
  return headerRow.some((h) => /^P\d+$/.test(h.trim().replace(/^"|"$/g, "")));
}

function buildKoboIndex(koboMap) {
  const byKoboId = {};
  koboMap.fields.forEach((f) => (byKoboId[f.kobo_id] = f));
  return byKoboId;
}

function convertRawExport(text, koboMap) {
  const delimiter = sniffDelimiter(text.split(/\r?\n/)[0]);
  const rows = parseDelimitedCsv(text.replace(/^﻿/, ""), delimiter);
  const header = rows[0].map((h) => h.trim());
  const dataRows = rows.slice(1).filter((r) => r.some((c) => c.trim() !== ""));

  const byKoboId = buildKoboIndex(koboMap);
  const itemIds = [];
  const answerRows = [];
  const unmatched = [];

  dataRows.forEach((cells, rowIdx) => {
    const itemId = `item${rowIdx + 1}`;
    itemIds.push(itemId);
    const raw = {};
    header.forEach((h, i) => (raw[h] = cells[i] ?? ""));

    const answers = {};
    for (const [h, v] of Object.entries(raw)) {
      if (KOBO_META_PREFIXES.some((p) => h.startsWith(p))) continue;
      const field = byKoboId[h];
      if (!field || field.type === "text") continue;
      if (v === "") continue;
      let value = v;
      if (field.options) {
        const idx = field.options.indexOf(v.trim().toLowerCase());
        if (idx === -1) {
          unmatched.push({ itemId, koboId: h, qid: field.id, value: v });
          continue; // left out entirely -> scores as blank, same as the reference model
        }
        value = `opt${idx + 1}`;
      }
      answers[field.id] = value;
    }
    answerRows.push(answers);
  });

  return { itemIds, answerRows, unmatched };
}

window.Kobo = { looksLikeRawExport, convertRawExport, parseDelimitedCsv, sniffDelimiter };
