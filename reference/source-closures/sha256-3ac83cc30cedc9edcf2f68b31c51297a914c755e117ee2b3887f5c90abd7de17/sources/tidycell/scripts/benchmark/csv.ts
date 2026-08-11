import type { CsvTable } from "./types";

export function parseCsv(csv: string): CsvTable {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let index = 0; index < csv.length; index += 1) {
    const char = csv[index];

    if (inQuotes) {
      if (char === '"') {
        if (csv[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        cell += char;
      }
      continue;
    }

    if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char === "\r") {
      if (csv[index + 1] === "\n") {
        continue;
      }
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  if (cell.length > 0 || row.length > 0 || !csv.endsWith("\n")) {
    row.push(cell);
    rows.push(row);
  }

  const headers = rows[0] ?? [];
  const dataRows = rows
    .slice(1)
    .filter((dataRow) => dataRow.length > 1 || dataRow[0] !== "");
  const records = dataRows.map((dataRow) =>
    Object.fromEntries(
      headers.map((header, index) => [header, dataRow[index] ?? ""]),
    ),
  );

  return {
    headers,
    rows: dataRows,
    records,
  };
}
