import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

type Fixture = {
  users: Record<string, string>;
  primary_scenario: string;
  sibling_scenario: string;
  foreign_scenario: string;
  document_set: string;
  document: string;
  document_version: number;
};

type SafeEvidence = {
  role: string;
  console: { type: string; path: string }[];
  network: { method: string; path: string; status?: number }[];
  requestIds: string[];
  url?: string;
};

const PASSWORD = "phase-2-9-browser-only";
const REST_TOKEN = "phase-2-9-browser-rest-token";
let fixture: Fixture;
const evidenceByPage = new WeakMap<Page, SafeEvidence>();

test.beforeAll(() => {
  fixture = JSON.parse(readFileSync(
    resolve(process.cwd(), "..", ".tmp", "phase-2-9-browser-fixture.json"),
    "utf-8",
  )) as Fixture;
});

test.beforeEach(async ({ page }, testInfo) => {
  const evidence: SafeEvidence = {
    role: "unset",
    console: [] as { type: string; path: string }[],
    network: [] as { method: string; path: string; status?: number }[],
    requestIds: [] as string[],
  };
  evidenceByPage.set(page, evidence);
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      evidence.console.push({
        type: message.type(),
        path: safePath(message.location().url),
      });
    }
  });
  page.on("requestfailed", (request) => {
    evidence.network.push({ method: request.method(), path: safePath(request.url()) });
  });
  page.on("response", (response) => {
    const requestId = response.headers()["x-request-id"];
    if (requestId && evidence.requestIds.length < 10) evidence.requestIds.push(requestId);
    if (response.status() >= 500) {
      evidence.network.push({
        method: response.request().method(),
        path: safePath(response.url()),
        status: response.status(),
      });
    }
  });
  await page.addInitScript(() => {
    window.confirm = () => true;
  });
});

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status === testInfo.expectedStatus) return;
  const evidence = evidenceByPage.get(page) ?? {
    role: "unknown",
    console: [],
    network: [],
    requestIds: [],
  };
  evidence.url = safePath(page.url());
  await testInfo.attach("redacted-browser-evidence", {
    body: JSON.stringify(evidence, null, 2),
    contentType: "application/json",
  });
});

async function login(page: Page, role: string) {
  const evidence = evidenceByPage.get(page);
  if (evidence) evidence.role = role;
  await page.goto("/console/login/");
  await page.getByLabel("Kullanıcı adı").fill(fixture.users[role]);
  await page.getByLabel("Parola").fill(PASSWORD);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page).toHaveURL(/\/console\/$/);
}

function safePath(value: string): string {
  if (!value) return "";
  try {
    const url = new URL(value, "http://127.0.0.1:8011");
    return `${url.pathname}${url.search}`.slice(0, 500);
  } catch {
    return "unparseable";
  }
}

test("role-aware navigation and exact scenario scope stay aligned", async ({ page }) => {
  await login(page, "viewer");
  await expect(page.getByRole("link", { name: "Projeler", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Dokümanlar", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Çalıştırmalar", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Şu an ne çalışıyor?" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Sizi bekleyen işlemler" })).toHaveCount(0);

  await page.goto(`/console/scenarios/id/${fixture.primary_scenario}/`);
  await expect(page.getByRole("heading", { name: "Empty Workflow" })).toBeVisible();
  await page.goto(`/console/builder/?organization=demo&scenario=${fixture.primary_scenario}`);
  await expect(page.getByText("Scenario Studio · Empty Workflow")).toBeVisible();
  await expect(page.getByText("salt okunur", { exact: true })).toBeVisible();

  const csrf = (await page.context().cookies()).find((cookie) => cookie.name === "csrftoken");
  expect(csrf).toBeTruthy();
  const deniedMutation = await page.context().request.post(
    `/console/scenarios/id/${fixture.primary_scenario}/lifecycle/`,
    {
      headers: {
        Referer: page.url(),
        "X-CSRFToken": csrf?.value ?? "",
      },
      form: { action: "disable" },
      maxRedirects: 0,
    },
  );
  expect(deniedMutation.status()).toBe(403);

  for (const hiddenScenario of [fixture.sibling_scenario, fixture.foreign_scenario]) {
    await page.goto(`/console/scenarios/id/${hiddenScenario}/`);
    await expect(page.getByRole("heading", { name: "Bu sayfa kullanılamıyor" })).toBeVisible();
  }
});

test("exact active index can be exercised only by its document manager", async ({ page }) => {
  await login(page, "document_manager");
  await page.goto(`/console/document-sets/id/${fixture.document_set}/`);
  await expect(page.getByText("Retrieval'a sor")).toBeVisible();
  await expect(page.getByText("silinmiş profil")).toHaveCount(0);
  await expect(page.getByText(/Pending/)).toHaveCount(0);
  await page.getByLabel("Soru").fill("İade politikası nedir?");
  await page.getByRole("button", { name: "Retrieval çalıştır" }).click();
  await expect(page.getByRole("heading", { name: "Belge retrieval sonucu" })).toBeVisible();
  await expect(page.getByText("Iade Politikasi")).toBeVisible();
  await expect(page.getByText(/14 gun icinde iade talebi/)).toBeVisible();
  await expect(page.getByText(/None/)).toHaveCount(0);
});

test("keyboard focus and narrow viewport remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await login(page, "viewer");
  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "Ana içeriğe geç" });
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeVisible();
  const outline = await skipLink.evaluate((element) => getComputedStyle(element).outlineStyle);
  expect(outline).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  const hasHorizontalPageOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(hasHorizontalPageOverflow).toBe(false);
});

test("runtime and content duties expose only their exact task surfaces", async ({ page }) => {
  await login(page, "runtime");
  await expect(page.getByRole("link", { name: "Çalıştırmalar", exact: true })).toBeVisible();
  await page.goto(`/console/scenarios/id/${fixture.primary_scenario}/`);
  await expect(page.getByRole("button", { name: "Exact senaryoyu durdur" })).toBeVisible();
  await page.goto(`/console/scenarios/id/${fixture.sibling_scenario}/`);
  await expect(page.getByRole("heading", { name: "Bu sayfa kullanılamıyor" })).toBeVisible();

  await page.context().clearCookies();
  await login(page, "content_reader");
  await expect(page.getByRole("link", { name: "Dokümanlar", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Projeler", exact: true })).toHaveCount(0);
  await page.goto(
    `/console/document-sets/id/${fixture.document_set}/documents/id/${fixture.document}/`,
  );
  await page.getByRole("link", { name: "Güvenli önizleme" }).click();
  await expect(page.getByText("Synthetic browser gate policy.")).toBeVisible();
  await page.goto(`/console/scenarios/id/${fixture.primary_scenario}/`);
  await expect(page.getByRole("heading", { name: "Bu sayfa kullanılamıyor" })).toBeVisible();
});

test("release/editor affordances, provider-disabled state and callability are truthful", async ({
  page,
  request,
}) => {
  await login(page, "editor");
  await page.goto(`/console/builder/?organization=demo&scenario=${fixture.primary_scenario}`);
  await expect(page.getByText("salt okunur", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Scenario Studio AI planner")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("profile ID");
  await expect(page.getByRole("button", { name: "Geçici aday üret" })).toBeDisabled();

  await page.context().clearCookies();
  await login(page, "releaser");
  await page.goto(`/console/scenarios/id/${fixture.primary_scenario}/`);
  await expect(page.getByRole("button", { name: "Çağrıları devre dışı bırak" })).toBeVisible();
  await expect(page.getByText(/Aktif istemci bağları.*senaryo çağrılabilir/)).toBeVisible();

  const response = await request.post("/v1/responses", {
    headers: {
      Authorization: `Bearer ${REST_TOKEN}`,
      "Idempotency-Key": `browser-${Date.now()}`,
    },
    data: { model: "empty-workflow", input: "hello" },
  });
  expect(response.status()).toBe(200);
  expect((await response.json()).status).toBe("completed");
});

test("unassigned and foreign operators cannot cross scope", async ({ page }) => {
  await login(page, "unassigned");
  await expect(page.getByRole("link", { name: "Projeler", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Dokümanlar", exact: true })).toHaveCount(0);
  await page.goto(`/console/scenarios/id/${fixture.primary_scenario}/`);
  await expect(page.getByRole("heading", { name: "Bu sayfa kullanılamıyor" })).toBeVisible();

  await page.context().clearCookies();
  await login(page, "foreign");
  await page.goto(`/console/scenarios/id/${fixture.primary_scenario}/`);
  await expect(page.getByRole("heading", { name: "Bu sayfa kullanılamıyor" })).toBeVisible();
  await page.goto(`/console/scenarios/id/${fixture.foreign_scenario}/`);
  await expect(page.getByRole("heading", { name: "Foreign scenario" })).toBeVisible();
});
