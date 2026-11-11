// Build: npm install pptxgenjs@3.12.0 && node docs/deck-src/build.js  (needs Python + Pillow for crop.py)
// Verity deck: GDG-style (soft grey canvas, white rounded cards, four Google colours with meaning).
const path = require("path");
const pptxgen = require("pptxgenjs");
const { execFileSync } = require("child_process");
const fs = require("fs");
const CROPS = path.join(__dirname, "crops");
fs.mkdirSync(CROPS, { recursive: true });
// Optional: point PPTX_SKILL_DIR at a folder with scripts/apply_theme.js to write theme colours into the file.
const SKILL = process.env.PPTX_SKILL_DIR;
const applyTheme = SKILL ? require(path.join(SKILL, "scripts/apply_theme.js")).applyTheme : async () => {};

const ROOT = path.resolve(__dirname, "..", "..");
const SHOT = (n) => `${ROOT}/docs/screenshots/${n}`;
const LOGO = path.join(__dirname, "gdg-logo.png");
const OUT = `${ROOT}/docs/Verity_LWC_Tracker.pptx`;

const THEME = {
  name: "GDG Verity",
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: "0F172A", lt1: "FFFFFF", dk2: "334155", lt2: "F0F2F5",
    accent1: "4285F4", accent2: "34A853", accent3: "FBBC04", accent4: "EA4335",
    accent5: "1967D2", accent6: "5F6368", hlink: "1967D2", folHlink: "5F6368",
  },
};
// Hex values for options that only accept hex, plus text shades and tints.
const HEX = {
  ink: "0F172A", ink2: "334155", muted: "5F6368", page: "F0F2F5", well: "F6F7F9", line: "E3E6EA",
  blue: "4285F4", red: "EA4335", yellow: "FBBC04", green: "34A853",
  tBlue: "1967D2", tRed: "C5221F", tYellow: "B06000", tGreen: "188038",
  tintBlue: "E8F0FE", tintRed: "FCE8E6", tintYellow: "FEF7E0", tintGreen: "E6F4EA",
};
const FAM = {
  blue: { fill: HEX.tintBlue, text: HEX.tBlue, solid: HEX.blue },
  red: { fill: HEX.tintRed, text: HEX.tRed, solid: HEX.red },
  yellow: { fill: HEX.tintYellow, text: HEX.tYellow, solid: HEX.yellow },
  green: { fill: HEX.tintGreen, text: HEX.tGreen, solid: HEX.green },
};
const FOOTER = "GDG on Campus NFSU Gandhinagar  ·  Learn With Communities Tracker";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.title = "Verity: Learn With Communities Tracker";
pres.author = "GDG on Campus NFSU Gandhinagar";
pres.company = "GDG on Campus NFSU Gandhinagar";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const W = 13.333;

// ---------- layouts ----------
pres.defineSlideMaster({
  title: "GDG Title",
  background: { color: HEX.page },
  objects: [],
});
pres.defineSlideMaster({
  title: "GDG Content",
  background: { color: HEX.page },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 10.6, h: 0.75, fontSize: 30, bold: true, color: HEX.ink, align: "left", valign: "middle", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "kicker", type: "body", x: 0.6, y: 1.08, w: 11.5, h: 0.4, fontSize: 14, color: HEX.muted, align: "left", valign: "top", margin: 0 }, text: "" } },
    { text: { text: FOOTER, options: { x: 0.6, y: 7.0, w: 8, h: 0.3, fontSize: 10, color: HEX.muted, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.55, h: 0.3, fontSize: 10, color: HEX.muted, align: "right" },
});

// ---------- helpers ----------
let objN = 0;
const oname = (p) => `${p}-${++objN}`;
function card(s, x, y, w, h, fill = HEX.ink === "" ? "" : "FFFFFF", r = 0.22) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: r, fill: { color: fill }, line: { type: "none" }, objectName: oname("card") });
}
function tile(s, x, y, fam, label, size = 0.62) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: size, h: size, rectRadius: 0.16, fill: { color: FAM[fam].fill }, line: { type: "none" }, objectName: oname("tile") });
  s.addText(label, { x, y, w: size, h: size, align: "center", valign: "middle", fontSize: 18, bold: true, color: FAM[fam].text, margin: 0, isTextBox: true, objectName: oname("tile-label") });
}
function dot(s, x, y, color, d = 0.13) {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color }, line: { type: "none" }, objectName: oname("dot") });
}
function chip(s, x, y, text, fam, w) {
  const f = fam ? FAM[fam] : { fill: "FFFFFF", text: HEX.ink2 };
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.38, rectRadius: 0.19, fill: { color: f.fill }, line: fam ? { type: "none" } : { color: HEX.line, width: 1 }, objectName: oname("chip") });
  s.addText(text, { x, y, w, h: 0.38, align: "center", valign: "middle", fontSize: 12, bold: true, color: f.text, margin: 0, isTextBox: true, objectName: oname("chip-text") });
}
function shot(s, file, x, y, w, h, pad = 0.12, anchor = "top") {
  card(s, x, y, w, h, "FFFFFF", 0.22);
  const iw = w - 2 * pad, ih = h - 2 * pad;
  // Pre-crop to the frame's aspect ratio so screenshots are never stretched.
  const out = path.join(CROPS, `${objN}-${file}`);
  execFileSync("python", [path.join(__dirname, "crop.py"), SHOT(file), String(iw / ih), out, anchor]);
  s.addImage({ path: out, x: x + pad, y: y + pad, w: iw, h: ih, objectName: oname("shot"), altText: `Screenshot of the Verity dashboard: ${file.replace(/^\d+-|\.png$/g, "").replace(/-/g, " ")}` });
}
function content(title, kicker, section) {
  const s = pres.addSlide({ masterName: "GDG Content", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  if (kicker) s.addText(kicker, { placeholder: "kicker" });
  return s;
}
function body(s, runs, opt) {
  s.addText(runs, { margin: 0, valign: "top", fontSize: 15, color: HEX.ink2, isTextBox: true, paraSpaceAfter: 6, objectName: oname("body"), ...opt });
}
const bullets = (items, size = 15) => items.map((t, i) => ({ text: t, options: { bullet: { indent: 16 }, fontSize: size, breakLine: i < items.length - 1 } }));

// ================= 1. Title =================
pres.addSection({ title: "Opening" });
{
  const s = pres.addSlide({ masterName: "GDG Title", sectionTitle: "Opening" });
  s.addImage({ path: LOGO, x: 0.6, y: 0.45, w: 0.82, h: 0.453, objectName: "gdg-logo", altText: "Google Developer Groups logo" });
  s.addText([{ text: "GDG ", options: { color: HEX.ink, bold: true } }, { text: "on Campus NFSU Gandhinagar", options: { color: "8A9099" } }],
    { x: 1.55, y: 0.45, w: 6, h: 0.45, fontSize: 18, valign: "middle", margin: 0, isTextBox: true, objectName: "brand" });
  card(s, 0.6, 1.2, 7.0, 5.7);
  s.addText([{ text: "Learn With Communities ", options: { color: HEX.ink } }, { text: "Tracker", options: { color: HEX.blue } }],
    { x: 1.1, y: 1.5, w: 6.2, h: 2.4, fontSize: 44, bold: true, valign: "top", margin: 0, isTextBox: true, objectName: "deck-title" });
  s.addText("Verity: a secure, rate-limited verifier for Google Skills public profiles", { x: 1.1, y: 4.0, w: 6.0, h: 0.75, fontSize: 18, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: "deck-subtitle" });
  chip(s, 1.1, 4.95, "Web dashboard", "blue", 1.75);
  chip(s, 2.95, 4.95, "CLI", "green", 0.8);
  chip(s, 3.85, 4.95, "Secure by design", "red", 1.95);
  chip(s, 5.9, 4.95, "Rate-limited", "yellow", 1.55);
  s.addText("TECH & DEVELOPMENT  ·  LEAD TASK", { x: 1.1, y: 5.8, w: 6, h: 0.3, fontSize: 11, bold: true, color: HEX.muted, charSpacing: 2, margin: 0, isTextBox: true, objectName: "eyebrow" });
  s.addText("Problem · need · logic · tech stack · process · impact", { x: 1.1, y: 6.15, w: 6, h: 0.35, fontSize: 14, color: HEX.ink2, margin: 0, isTextBox: true, objectName: "agenda-line" });
  shot(s, "01-landing.png", 7.9, 1.2, 4.83, 5.7, 0.12, "left");
  s.addNotes("Introduce Verity: the tracker built for the Learn With Communities campaign lead task. One engine, two front ends: a web dashboard and a CLI. The talk covers the problem, why we need it, how it decides who completed, the security controls, the stack and the impact.");
}

// ================= 2. Problem =================
pres.addSection({ title: "Problem and need" });
{
  const s = content("Checking badges by hand does not scale", "Every participant submits a public profile. Today an organiser opens each one and counts.", "Problem and need");
  card(s, 0.6, 1.75, 4.1, 4.95);
  s.addText("1,000", { x: 0.95, y: 2.1, w: 3.5, h: 1.2, fontSize: 72, bold: true, color: HEX.tRed, margin: 0, isTextBox: true, objectName: "stat-big" });
  s.addText("badge checks for a 100-person cohort (100 profiles × 10 required badges), repeated every time someone asks “am I done?”", { x: 0.95, y: 3.35, w: 3.5, h: 1.6, fontSize: 15, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: "stat-text" });
  s.addText("Estimate at about 45 to 60 s per profile: 75 to 100 minutes of clicking per review round.", { x: 0.95, y: 5.4, w: 3.5, h: 0.9, fontSize: 12, color: HEX.muted, italic: true, margin: 0, valign: "top", isTextBox: true, objectName: "stat-note" });
  const pains = [
    ["red", "1", "Slow and repetitive", "Open a profile, scroll, count, record. Then repeat for every row in the sheet."],
    ["yellow", "2", "Error-prone counts", "Arcade and course badges sit next to skill badges. Easy to count the wrong ones."],
    ["blue", "3", "Easy to game", "Two students can submit the same profile, or a profile that is not theirs."],
    ["green", "4", "No campaign picture", "Organisers cannot see which badge is the bottleneck in time to help."],
  ];
  pains.forEach(([fam, n, head, text], i) => {
    const x = 5.0 + (i % 2) * 3.9, y = 1.75 + Math.floor(i / 2) * 2.55;
    card(s, x, y, 3.7, 2.4);
    tile(s, x + 0.35, y + 0.35, fam, n);
    s.addText(head, { x: x + 0.35, y: y + 1.1, w: 3.0, h: 0.4, fontSize: 17, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: oname("pain-head") });
    s.addText(text, { x: x + 0.35, y: y + 1.5, w: 3.05, h: 0.8, fontSize: 13, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: oname("pain-text") });
  });
  s.addNotes("The lead task asks us to count completed skill badges from public profiles. Done by hand, a 100-person cohort means about a thousand checks per review round. The 45 to 60 seconds per profile figure is our estimate, not a measurement. Beyond time, manual counting mixes badge types, misses shared profiles and gives no campaign-level view.");
}

// ================= 3. Need =================
{
  const s = content("What the campaign needs from a tracker", "Requirements from the problem statement, plus what organisers told us matters.", "Problem and need");
  const reqs = [
    ["blue", "Customisable roster", "Accept the CSV shared on Discord, whatever its column order or headers."],
    ["green", "Accurate completion", "Count only the 10 campaign skill badges, not every badge on the page."],
    ["yellow", "Polite, reliable fetching", "Rate limiting, retries and clear errors so a bad row never stops the run."],
    ["red", "Safe to run and share", "Treat every CSV cell and every fetched page as untrusted input."],
  ];
  reqs.forEach(([fam, head, text], i) => {
    const y = 1.75 + i * 1.22;
    card(s, 0.6, y, 6.6, 1.08);
    dot(s, 0.95, y + 0.47, FAM[fam].solid, 0.16);
    s.addText(head, { x: 1.35, y: y + 0.17, w: 5.6, h: 0.36, fontSize: 16, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: oname("req-head") });
    s.addText(text, { x: 1.35, y: y + 0.53, w: 5.6, h: 0.42, fontSize: 13, color: HEX.ink2, margin: 0, isTextBox: true, objectName: oname("req-text") });
  });
  card(s, 7.5, 1.75, 5.23, 4.74);
  s.addText("Who uses it", { x: 7.9, y: 2.05, w: 4.5, h: 0.4, fontSize: 18, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: "who-head" });
  const who = [
    ["Leads and organisers", "verify the whole cohort in minutes and export a sheet for certificates."],
    ["Facilitators", "see the badge most people are stuck on and plan a help session for it."],
    ["Participants", "get a consistent, explainable answer: which badges counted, which are missing."],
  ];
  who.forEach(([h, t], i) => {
    s.addText([{ text: h + "  ", options: { bold: true, color: HEX.ink } }, { text: t, options: { color: HEX.ink2 } }],
      { x: 7.9, y: 2.6 + i * 1.22, w: 4.5, h: 1.05, fontSize: 14, margin: 0, valign: "top", isTextBox: true, objectName: oname("who") });
  });
  s.addNotes("These are the four requirements we designed against. The CSV structure is only shared on Discord, so the parser detects columns by content. Completion counts only the campaign badges. Fetching has to be polite and resilient. And because the tool reads files and web pages it did not write, everything is treated as untrusted.");
}

// ================= 4. Solution =================
pres.addSection({ title: "Solution" });
{
  const s = content("Verity: one engine, two front ends", "A web dashboard for organisers and a CLI for scripts, sharing the same verified logic.", "Solution");
  shot(s, "04-overview.png", 0.6, 1.75, 7.6, 4.95);
  const feats = [
    ["blue", "Upload or paste", "CSV with auto column detection, or paste links. Bad rows are listed before any request is sent."],
    ["green", "Live verification", "Progress, rate and ETA while profiles are checked; results stream in row by row."],
    ["yellow", "Campaign insight", "Badge distribution and “where participants are stuck”, lowest badge first."],
    ["red", "Integrity flags", "Shared profiles, name mismatches and invalid links surface in a Needs attention filter."],
  ];
  feats.forEach(([fam, h, t], i) => {
    const y = 1.75 + i * 1.25;
    tile(s, 8.5, y + 0.05, fam, String(i + 1), 0.55);
    s.addText(h, { x: 9.25, y, w: 3.5, h: 0.36, fontSize: 16, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: oname("feat-head") });
    s.addText(t, { x: 9.25, y: y + 0.38, w: 3.5, h: 0.8, fontSize: 12.5, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: oname("feat-text") });
  });
  s.addNotes("Verity is a Python package with a FastAPI web app and a Rich command line tool on top of the same engine. The screenshot is the live overview from a demo run of 48 rows.");
}

// ================= 5. Process =================
{
  const s = content("From CSV to verified results in six steps", "No profile is requested until its link has passed validation.", "Solution");
  const steps = [
    ["blue", "Upload", "CSV or pasted links; size and row limits checked first"],
    ["red", "Validate", "Extract the profile ID; reject other sites, ports and paths"],
    ["yellow", "De-duplicate", "Each unique profile fetched once; shared ones flagged"],
    ["green", "Fetch", "Token bucket pacing, retries, timeouts, size cap"],
    ["blue", "Parse and match", "Read badge titles and dates; match the 10 campaign badges"],
    ["green", "Report", "Live dashboard, filters, detail view, CSV and JSON export"],
  ];
  const cw = 1.92, gap = 0.11;
  steps.forEach(([fam, h, t], i) => {
    const x = 0.6 + i * (cw + gap), y = 1.85;
    card(s, x, y, cw, 3.3);
    s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: y + 0.3, w: 0.62, h: 0.62, fill: { color: FAM[fam].solid }, line: { type: "none" }, objectName: oname("step-circle") });
    s.addText(String(i + 1), { x: x + 0.3, y: y + 0.3, w: 0.62, h: 0.62, align: "center", valign: "middle", fontSize: 18, bold: true, color: fam === "yellow" ? HEX.ink : "FFFFFF", margin: 0, isTextBox: true, objectName: oname("step-num") });
    s.addText(h, { x: x + 0.3, y: y + 1.15, w: cw - 0.45, h: 0.4, fontSize: 15, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: oname("step-head") });
    s.addText(t, { x: x + 0.3, y: y + 1.6, w: cw - 0.5, h: 1.55, fontSize: 12.5, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: oname("step-text") });
  });
  card(s, 0.6, 5.4, 12.13, 1.3);
  s.addText([
    { text: "Statuses  ", options: { bold: true, color: HEX.ink } },
    { text: "Completed ", options: { bold: true, color: HEX.tGreen } }, { text: "10 of 10   ", options: { color: HEX.ink2 } },
    { text: "In progress ", options: { bold: true, color: HEX.tBlue } }, { text: "1 to 9   ", options: { color: HEX.ink2 } },
    { text: "Not started ", options: { bold: true, color: HEX.tYellow } }, { text: "0   ", options: { color: HEX.ink2 } },
    { text: "Needs attention ", options: { bold: true, color: HEX.tRed } }, { text: "invalid link, not found, fetch or parse error", options: { color: HEX.ink2 } },
  ], { x: 0.95, y: 5.55, w: 11.5, h: 1.0, fontSize: 14, margin: 0, valign: "middle", isTextBox: true, objectName: "status-legend" });
  s.addNotes("Walk the pipeline left to right. The key design choice is that validation happens before any network request, and de-duplication means a shared profile costs one request but gets flagged on every row that uses it.");
}

// ================= 6. Logic =================
{
  const s = content("How Verity decides who completed", "Rules live in campaign.toml on the server, so a browser cannot change them.", "Solution");
  card(s, 0.6, 1.75, 6.0, 4.95);
  s.addText("Matching rules", { x: 0.95, y: 2.0, w: 5.3, h: 0.4, fontSize: 18, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: "rules-head" });
  body(s, bullets([
    "Only the 10 configured skill badges count. Other badges are listed as “not counted”.",
    "Titles are normalised: case, spacing, punctuation and dash styles do not matter.",
    "Aliases map renamed badges to their current title, so older earners still count.",
    "Optional campaign window: badges earned outside it are shown but not counted.",
    "Leave the list empty and every badge counts: the same tool works for other campaigns.",
  ], 14), { x: 0.95, y: 2.5, w: 5.35, h: 4.0 });
  card(s, 6.9, 1.75, 5.83, 4.95);
  s.addText("Integrity flags", { x: 7.25, y: 2.0, w: 5.2, h: 0.4, fontSize: 18, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: "flags-head" });
  const flags = [
    ["yellow", "Shared profile", "The same profile ID appears in more than one roster row. Fetched once, flagged on every row."],
    ["red", "Name mismatch", "The roster name shares no word with the name on the profile: check the link belongs to the student."],
    ["blue", "Outside window", "Some badges were earned before the campaign started."],
  ];
  flags.forEach(([fam, h, t], i) => {
    const y = 2.6 + i * 1.33;
    chip(s, 7.25, y, h, fam, 1.85);
    s.addText(t, { x: 9.25, y: y - 0.04, w: 3.25, h: 1.15, fontSize: 13, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: oname("flag-text") });
  });
  s.addNotes("Completion means at least 10 qualifying badges after normalisation and aliases. The flags do not change the count. They point an organiser at rows worth a human look, which keeps the tool explainable rather than accusatory.");
}

// ================= 7. Rate limiting & errors =================
pres.addSection({ title: "Reliability and security" });
{
  const s = content("Polite to the source, resilient to failure", "Defaults from campaign.toml; every value is clamped to a safe range at start-up.", "Reliability and security");
  const stats = [
    ["blue", "1 req/s", "global token bucket, burst of 2, shared by every run"],
    ["green", "3", "parallel workers, so slow pages do not block the queue"],
    ["yellow", "3 retries", "for timeouts, 5xx and 429, with exponential backoff and jitter"],
    ["red", "8 failures", "in a row open the circuit breaker and stop the run cleanly"],
  ];
  stats.forEach(([fam, big, t], i) => {
    const x = 0.6 + i * 3.08;
    card(s, x, 1.75, 2.9, 2.2);
    s.addText(big, { x: x + 0.3, y: 1.98, w: 2.4, h: 0.85, fontSize: 36, bold: true, color: FAM[fam].text, margin: 0, isTextBox: true, objectName: oname("rl-big") });
    s.addText(t, { x: x + 0.3, y: 2.88, w: 2.35, h: 0.95, fontSize: 13, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: oname("rl-text") });
  });
  card(s, 0.6, 4.15, 6.0, 2.55);
  s.addText("Outbound requests", { x: 0.95, y: 4.35, w: 5.3, h: 0.36, fontSize: 16, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: "out-head" });
  body(s, bullets([
    "Retry-After is honoured and pauses every worker, not just one",
    "5 s connect and 15 s read timeouts; 2 MB response cap",
    "Redirects are never followed: a redirect means “not found”",
    "Parsed profiles cached for 15 minutes; failures are never cached",
  ], 13), { x: 0.95, y: 4.8, w: 5.4, h: 1.8 });
  card(s, 6.9, 4.15, 5.83, 2.55);
  s.addText("Inbound and errors", { x: 7.25, y: 4.35, w: 5.2, h: 0.36, fontSize: 16, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: "in-head" });
  body(s, bullets([
    "Per-client limits: 20 uploads, 10 runs, 300 polls a minute",
    "One bad row becomes a status, never a crashed run",
    "Retry only the unfinished rows; finished rows carry over",
    "Errors shown in plain words; stack traces stay in server logs",
  ], 13), { x: 7.25, y: 4.8, w: 5.25, h: 1.8 });
  s.addNotes("Rate limiting works in both directions. Outbound, a token bucket keeps us at one request per second across all runs, and a 429 pauses everyone. Inbound, a sliding window stops anyone flooding the server. Failures are classified so only transient ones are retried.");
}

// ================= 8. Secure coding =================
{
  const s = content("Secure coding: threat by threat", "Each control is covered by an automated test.", "Reliability and security");
  const head = (t) => ({ text: t, options: { bold: true, color: HEX.muted, fontSize: 11, fill: { color: HEX.well }, charSpacing: 1 } });
  const rows = [
    ["SSRF through a crafted link", "Never request user input. Extract a UUID, check it, rebuild the URL on an allowlisted host"],
    ["CSV / formula injection", "Cells starting with = + - @ are escaped in every export"],
    ["Cross-site scripting", "Untrusted text written with textContent only; strict CSP, no inline scripts"],
    ["CSRF and DNS rebinding", "Custom request header, Origin check, Host allowlist"],
    ["Upload and request abuse", "1 MB / 5,000-row limits, Content-Length required, inbound rate limits"],
    ["Hostile or oversized pages", "Streamed 2 MB cap, no script execution, bounded parser, worker isolation"],
    ["Exposure and data leaks", "Binds to localhost; access token required beyond it; masked logs; no API docs"],
  ];
  const data = [[head("THREAT"), head("CONTROL IN VERITY")]].concat(rows.map(([a, b]) => [
    { text: a, options: { bold: true, color: HEX.ink } }, { text: b, options: { color: HEX.ink2 } },
  ]));
  card(s, 0.6, 1.7, 12.13, 5.05);
  s.addTable(data, { x: 0.85, y: 1.9, w: 11.63, colW: [3.6, 8.03], fontSize: 13, rowH: 0.56, valign: "middle", margin: [0, 0.15, 0, 0.15],
    border: { type: "solid", color: HEX.line, pt: 0.75 }, fill: { color: "FFFFFF" }, objectName: "threat-table" });
  s.addNotes("This is the secure coding slide. The most important line is the first: the fetcher can only ever request https://www.skills.google/public_profiles/ followed by a validated UUID, so SSRF is designed out rather than filtered. Every row here has a matching test in the 74-test suite.");
}

// ================= 9. Tech stack =================
pres.addSection({ title: "Build" });
{
  const s = content("Tech stack", "Small, boring dependencies chosen for auditability.", "Build");
  const stack = [
    ["blue", "Python 3.14", "Core engine, standard-library TOML config and CSV parsing"],
    ["green", "FastAPI + Uvicorn", "Web API with security middleware; API docs disabled"],
    ["yellow", "requests", "Streaming HTTP with timeouts, no proxies from the environment"],
    ["red", "BeautifulSoup", "With lxml: HTML parsing that never runs page scripts"],
    ["blue", "Vanilla JS + CSS", "No framework, no third-party scripts; Google Sans and Inter"],
    ["green", "Rich", "CLI progress bars and result tables"],
    ["yellow", "pytest", "74 tests across validation, fetching, rules and the web API"],
    ["red", "Headless Chrome", "Scripted UI checks and the screenshots in this deck"],
  ];
  stack.forEach(([fam, h, t], i) => {
    const col = i % 4, row = Math.floor(i / 4);
    const x = 0.6 + col * 3.08, y = 1.75 + row * 2.5;
    card(s, x, y, 2.9, 2.3);
    dot(s, x + 0.32, y + 0.42, FAM[fam].solid, 0.16);
    s.addText(h, { x: x + 0.6, y: y + 0.3, w: 2.15, h: 0.42, fontSize: 16, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: oname("stack-head") });
    s.addText(t, { x: x + 0.32, y: y + 0.9, w: 2.35, h: 1.25, fontSize: 13, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: oname("stack-text") });
  });
  s.addNotes("The stack is deliberately small. The front end loads no third-party JavaScript, which keeps the content security policy strict. Fonts come from Google Fonts only.");
}

// ================= 10. Dashboard tour =================
{
  const s = content("Dashboard tour", "Filter, search, sort, then open any row to see exactly why it got its status.", "Build");
  shot(s, "05-participants.png", 0.6, 1.75, 7.2, 4.95);
  shot(s, "07-detail.png", 8.05, 1.75, 4.68, 3.2);
  card(s, 8.05, 5.15, 4.68, 1.55);
  s.addText("Every row explains itself: counted badges with dates, the ones still needed, flags and errors in plain language.", { x: 8.35, y: 5.3, w: 4.1, h: 1.25, fontSize: 13, color: HEX.ink2, margin: 0, valign: "middle", isTextBox: true, objectName: "tour-caption" });
  s.addNotes("Left: the participants table with status filters and the 10-segment progress meter. Right: the detail dialog for a flagged row, showing the shared-profile flag and counted badges.");
}

// ================= 11. Quality =================
{
  const s = content("Tested, accessible, responsive", "Quality checks we ran before calling it done.", "Build");
  card(s, 0.6, 1.75, 3.9, 4.95);
  s.addText("74", { x: 0.95, y: 2.05, w: 3.2, h: 1.3, fontSize: 80, bold: true, color: HEX.tGreen, margin: 0, isTextBox: true, objectName: "tests-big" });
  s.addText("automated tests, all passing", { x: 0.95, y: 3.35, w: 3.2, h: 0.4, fontSize: 16, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: "tests-label" });
  body(s, bullets(["28 link-validation and output-encoding cases", "Retries, 429, timeouts, circuit breaker", "CSRF, Host, upload, auth and rate-limit tests", "End-to-end run with a safe CSV export"], 13), { x: 0.95, y: 3.95, w: 3.3, h: 2.6 });
  card(s, 4.75, 1.75, 4.0, 4.95);
  s.addText("Accessibility", { x: 5.1, y: 2.05, w: 3.4, h: 0.4, fontSize: 18, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: "a11y-head" });
  body(s, bullets([
    "Visible 3 px focus ring on every control",
    "Full keyboard use: tabs, sorting, dialogs",
    "Status uses shape and text, never colour alone",
    "Live region announces run progress",
    "Text colours meet WCAG AA contrast",
    "Respects reduced-motion settings",
  ], 13), { x: 5.1, y: 2.6, w: 3.45, h: 3.9 });
  shot(s, "09-mobile.png", 9.0, 1.75, 3.73, 4.95);
  s.addNotes("The test count is the real number from the suite. The phone screenshot is a 390 px wide viewport; the focus ring on the Campaign rules button is from a keyboard Tab press.");
}

// ================= 12. Impact =================
pres.addSection({ title: "Impact" });
{
  const s = content("Practical impact", "What changes for the chapter once the tracker is in use.", "Impact");
  const big = [
    ["blue", "≈ 2 min", "to verify 100 profiles at the polite 1 request/s pace, against an estimated 75 to 100 minutes by hand"],
    ["green", "0", "manual counting errors: only the 10 campaign badges are counted, the same way every time"],
    ["red", "Day 1", "visibility of the bottleneck badge, so facilitators can run a targeted help session"],
  ];
  big.forEach(([fam, n, t], i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 1.75, 3.9, 2.75);
    s.addText(n, { x: x + 0.35, y: 2.0, w: 3.3, h: 1.0, fontSize: 44, bold: true, color: FAM[fam].text, margin: 0, isTextBox: true, objectName: oname("impact-big") });
    s.addText(t, { x: x + 0.35, y: 3.05, w: 3.25, h: 1.35, fontSize: 13.5, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: oname("impact-text") });
  });
  card(s, 0.6, 4.7, 12.13, 2.0);
  s.addText("Beyond this campaign", { x: 0.95, y: 4.9, w: 5, h: 0.4, fontSize: 17, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: "beyond-head" });
  body(s, bullets([
    "Fairer certificates: shared or mismatched profiles are caught before rewards go out",
    "Reusable: a new campaign is a new badge list in campaign.toml, no code changes",
    "Safe to hand over: next year's leads inherit a tested tool, not a spreadsheet ritual",
  ], 14), { x: 0.95, y: 5.38, w: 11.4, h: 1.25 });
  s.addNotes("The two-minute figure follows from the configured pace: 100 requests at one per second plus retries. The manual figure is our estimate. The zero-error claim is about counting logic: the tool applies the same rule to every profile.");
}

// ================= 13. Run it =================
{
  const s = content("Run it, and what comes next", "Everything below works offline with the built-in demo mode.", "Impact");
  card(s, 0.6, 1.75, 6.6, 4.95, HEX.ink);
  s.addText("Quick start", { x: 0.95, y: 2.0, w: 5.9, h: 0.4, fontSize: 17, bold: true, color: "FFFFFF", margin: 0, isTextBox: true, objectName: "qs-head" });
  const cmds = [
    ["Install", "pip install -r requirements.txt"],
    ["Dry-run a roster", "python -m lwc_tracker validate roster.csv"],
    ["Verify from the terminal", "python -m lwc_tracker check roster.csv -o out.csv"],
    ["Open the dashboard", "python -m lwc_tracker serve"],
    ["Offline demo", "python -m lwc_tracker serve --demo"],
  ];
  cmds.forEach(([label, cmd], i) => {
    const y = 2.55 + i * 0.8;
    s.addText(label, { x: 0.95, y, w: 5.9, h: 0.3, fontSize: 12, color: "AECBFA", margin: 0, isTextBox: true, objectName: oname("cmd-label") });
    s.addText(cmd, { x: 0.95, y: y + 0.3, w: 5.9, h: 0.38, fontSize: 13, fontFace: "Courier New", color: "FFFFFF", margin: 0, isTextBox: true, objectName: oname("cmd") });
  });
  card(s, 7.5, 1.75, 5.23, 4.95);
  s.addText("Next steps", { x: 7.85, y: 2.0, w: 4.6, h: 0.4, fontSize: 17, bold: true, color: HEX.ink, margin: 0, isTextBox: true, objectName: "next-head" });
  const next = [
    ["blue", "Load the official roster and badge list from Discord into campaign.toml"],
    ["green", "Scheduled nightly re-checks with a change log of new completions"],
    ["yellow", "Optional Google Sheets export for the certificates team"],
    ["red", "Discord webhook to celebrate each new 10 of 10"],
  ];
  next.forEach(([fam, t], i) => {
    const y = 2.6 + i * 1.0;
    dot(s, 7.85, y + 0.12, FAM[fam].solid, 0.16);
    s.addText(t, { x: 8.25, y, w: 4.2, h: 0.85, fontSize: 14, color: HEX.ink2, margin: 0, valign: "top", isTextBox: true, objectName: oname("next") });
  });
  s.addNotes("Demo with serve --demo and the Load demo roster button: synthetic profiles, including injected 429 and 503 responses so the audience can see retries happen. Next steps are proposals, not built features.");
}

// ================= 14. Thanks =================
{
  const s = pres.addSlide({ masterName: "GDG Title", sectionTitle: "Impact" });
  card(s, 0.6, 0.6, 12.13, 6.3);
  s.addImage({ path: LOGO, x: 5.67, y: 1.35, w: 2.0, h: 1.105, objectName: "gdg-logo-end", altText: "Google Developer Groups logo" });
  s.addText([{ text: "Thank ", options: { color: HEX.ink } }, { text: "you", options: { color: HEX.blue } }],
    { x: 1.5, y: 2.8, w: 10.33, h: 1.2, fontSize: 54, bold: true, align: "center", margin: 0, isTextBox: true, objectName: "thanks" });
  s.addText("Verity · Learn With Communities Tracker", { x: 1.5, y: 4.05, w: 10.33, h: 0.5, fontSize: 18, color: HEX.ink2, align: "center", margin: 0, isTextBox: true, objectName: "thanks-sub" });
  chip(s, 4.3, 4.95, "Questions", "blue", 1.5);
  chip(s, 5.95, 4.95, "Live demo", "green", 1.45);
  chip(s, 7.55, 4.95, "Feedback", "yellow", 1.45);
  s.addText("GDG on Campus NFSU Gandhinagar  ·  Independent community project, not managed by Google", { x: 1.5, y: 5.95, w: 10.33, h: 0.4, fontSize: 12, color: HEX.muted, align: "center", margin: 0, isTextBox: true, objectName: "thanks-foot" });
  s.addNotes("Close and open for questions or the live demo.");
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
