// Screenshots of saved reports, sharing and the usage report (D83), in docs/screenshots/:
// 18-report, 19-share-dialog, 20-shared-report, 21-my-reports, 22-admin-reports, 23-help.
//
//   node scripts/reports-screenshots.mjs                                # npm run dev on :5173
//   BASE=http://localhost:8080 node scripts/reports-screenshots.mjs     # docker compose app
//   CHANNEL=chrome node scripts/reports-screenshots.mjs                 # installed Chrome
//
// Signs in with the demo account, puts warfarin and fluconazole in "My pills", saves a report
// from the Scanner page, shares it, opens the link in a second browser without an account,
// then shows the administrators' usage report. Afterwards it deletes the report and puts the
// demo account's list back as it was. Fails if a step does not show what it should.
import { mkdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import { chromium } from "playwright";

const BASE = process.env.BASE ?? "http://localhost:5173";
const OUT = resolve(process.env.OUT ?? "../docs/screenshots");
const EMAIL = process.env.DEMO_EMAIL ?? "user@gmail.com";
const PASSWORD = process.env.DEMO_PASSWORD ?? "user";
const ADMIN_EMAIL = process.env.ADMIN_EMAIL ?? "admin@gmail.com";
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? "admin";

async function shot(target, name, fullPage = false) {
  await new Promise((done) => setTimeout(done, 700)); // let the entrance animations finish
  await target.screenshot({ path: join(OUT, name), type: "jpeg", quality: 82, fullPage });
}

async function signIn(context, email, password) {
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("tujya-lang", "en");
    localStorage.setItem("tujya-theme", "light");
  });
  await page.goto(`${BASE}/login`);
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').first().fill(password);
  await page.locator('input[type="password"]').first().press("Enter");
  await page.waitForURL(/\/(home|admin)/, { timeout: 20_000 });
  return page;
}

/** fetch() from the page, with its session cookie. */
function call(page, method, path, body) {
  return page.evaluate(
    async ({ method, path, body }) => {
      const response = await fetch(`/api${path}`, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`${method} ${path}: ${response.status}`);
      return response.status === 204 ? null : response.json();
    },
    { method, path, body },
  );
}

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch(process.env.CHANNEL ? { channel: process.env.CHANNEL } : {});
const viewport = { width: 1366, height: 900 };
const user = await signIn(await browser.newContext({ viewport }), EMAIL, PASSWORD);

const before = (await call(user, "GET", "/my/medicines")).items;
let reportId = null;
try {
  const find = async (q) => (await call(user, "GET", `/pills?q=${q}&limit=1`)).items[0].class_id;
  await call(user, "DELETE", "/my/medicines");
  for (const q of ["warfarin", "fluconazole"]) {
    await call(user, "POST", "/my/medicines", { class_id: await find(q), probability: 0.97 });
  }

  // Save the report from the Scanner page, as a user would.
  await user.goto(`${BASE}/scan`);
  await user.locator(".my-pills .chip").nth(1).waitFor();
  await user.getByRole("button", { name: "Save a report" }).click();
  await user.getByRole("button", { name: "Save the report" }).click();
  await user.waitForURL(/\/reports\/\d+$/, { timeout: 20_000 });
  reportId = Number(user.url().split("/").pop());
  await user.locator(".rdoc-pair").first().waitFor();
  await shot(user, "18-report.jpg", true);

  await user.getByRole("button", { name: "Share", exact: true }).click();
  await user.getByRole("button", { name: "Create the link" }).click();
  const link = await user.locator("dialog.modal input[readonly]").inputValue();
  if (!link.includes("/shared#")) throw new Error(`unexpected share link: ${link}`);
  await shot(user.locator("dialog.modal"), "19-share-dialog.jpg");
  await user.keyboard.press("Escape");

  // The pharmacist: another browser, no account, French interface.
  const guest = await (await browser.newContext({ viewport })).newPage();
  await guest.addInitScript(() => localStorage.setItem("tujya-lang", "fr"));
  await guest.goto(link);
  await guest.locator(".rdoc-pair").first().waitFor({ timeout: 20_000 });
  await shot(guest, "20-shared-report.jpg", true);

  await user.goto(`${BASE}/reports`);
  await user.locator(".report-item").first().waitFor();
  await user.mouse.move(0, 0);
  await shot(user, "21-my-reports.jpg");

  const admin = await signIn(await browser.newContext({ viewport }), ADMIN_EMAIL, ADMIN_PASSWORD);
  await admin.goto(`${BASE}/admin/reports`);
  await admin.locator(".viz-frame svg").first().waitFor({ timeout: 20_000 });
  const chart = await admin.locator(".viz-frame").first().boundingBox();
  await admin.mouse.move(chart.x + chart.width - 20, chart.y + 120); // today's tooltip
  await shot(admin, "22-admin-reports.jpg", true);

  const visitor = await (await browser.newContext({ viewport })).newPage();
  await visitor.addInitScript(() => localStorage.setItem("tujya-lang", "en"));
  await visitor.goto(`${BASE}/help`);
  await visitor.locator(".faq-item").first().waitFor();
  await shot(visitor, "23-help.jpg");
} finally {
  // Leave the demo account as it was.
  if (reportId !== null) await call(user, "DELETE", `/my/reports/${reportId}`);
  await call(user, "DELETE", "/my/medicines");
  for (const item of before) {
    await call(user, "POST", "/my/medicines", { class_id: item.class_id, probability: item.probability });
  }
  await browser.close();
}
console.log(`Screenshots 18 to 23 saved in ${OUT}`);
