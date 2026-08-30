import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [sourcePath, contactsPath, qualityPath, outputPath, previewDir] = process.argv.slice(2);
if (![sourcePath, contactsPath, qualityPath, outputPath, previewDir].every(Boolean)) {
  throw new Error("usage: build_normalized_workbook.mjs <source> <contacts.ndjson> <quality.json> <output> <preview-dir>");
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));
const contacts = (await fs.readFile(contactsPath, "utf8")).split(/\r?\n/).filter(Boolean).map(JSON.parse);
const quality = JSON.parse(await fs.readFile(qualityPath, "utf8"));
const normalized = workbook.worksheets.getOrAdd("Normalized Contacts");
const qc = workbook.worksheets.getOrAdd("QC Summary");

const headers = [
  "Source Row", "Disposition", "Issues", "Display Name", "Email", "Raw Email", "LinkedIn URL",
  "Organisation", "Country", "Business", "Brand", "Brand Category", "Function", "Position",
  "Industry", "Designation", "Marketing Segment", "Status Observation", "Company Update", "Position Update",
];
const rows = contacts.map((row) => [
  row.sourceRow, row.disposition, row.issues.join("; "), row.person.displayName, row.person.email,
  row.person.rawEmail, row.person.linkedInUrl, row.organisation, row.country, row.business, row.brand,
  row.brandCategory, row.function, row.position, row.industry, row.designation, row.marketingSegment,
  row.statusObservation, row.companyUpdate, row.positionUpdate,
]);
normalized.getRangeByIndexes(0, 0, rows.length + 1, headers.length).values = [headers, ...rows];
normalized.getRange(`A1:T1`).format = { fill: "#17365D", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
normalized.getRange(`A2:A${rows.length + 1}`).format.numberFormat = "0";
normalized.getRange(`A1:T${rows.length + 1}`).format.autofitColumns();
for (const letter of ["C", "D", "F", "G", "H", "J", "K", "L", "N", "P", "R", "S", "T"]) {
  normalized.getRange(`${letter}1:${letter}${rows.length + 1}`).format.columnWidth = 24;
}
normalized.freezePanes.freezeRows(1);
normalized.showGridLines = false;
normalized.tables.add(`A1:T${rows.length + 1}`, true, "NormalizedContactsTable");

const qcRows = [["Metric", "Value"], ...Object.entries(quality).filter(([, value]) => typeof value !== "object")];
qc.getRangeByIndexes(0, 0, qcRows.length, 2).values = qcRows;
qc.getRange("A1:B1").format = { fill: "#17365D", font: { bold: true, color: "#FFFFFF" } };
qc.getRange(`A1:B${qcRows.length}`).format.autofitColumns();
qc.getRange(`A1:A${qcRows.length}`).format.columnWidth = 28;
qc.getRange(`B1:B${qcRows.length}`).format.columnWidth = 18;
qc.showGridLines = false;

const errorScan = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "normalized workbook formula error scan" });
if (errorScan.ndjson.includes('"kind":"match"')) throw new Error(`formula error scan failed: ${errorScan.ndjson}`);

await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, range] of [["Merged List", "A1:Q30"], ["Normalized Contacts", "A1:T30"], ["QC Summary", `A1:B${qcRows.length}`]]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName.replaceAll(" ", "-").toLowerCase()}.png`), new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.rm(`${outputPath}.inspect.ndjson`, { force: true });
