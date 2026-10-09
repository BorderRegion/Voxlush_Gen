import { expect, test } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:8067/__test/reset");
});

test("composition filters, honest mode statistics and weighted export controls", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "样本作品", exact: true }).click();
  await page
    .getByLabel("场景构成", { exact: true })
    .selectOption("pure_target");
  await expect(page.locator(".sample-card")).toHaveCount(12);
  await expect(page.locator(".sample-card").first()).toContainText(
    "纯目标建筑",
  );
  const state = await (
    await request.get("http://127.0.0.1:8067/__test/state")
  ).json();
  expect(
    state.requests.some(
      (r: { query: Record<string, string> }) =>
        r.query.composition_mode === "pure_target",
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "覆盖与质量", exact: true }).click();
  const table = page.locator("table").filter({ hasText: "正式 / 暂定" });
  await expect(table).toContainText("0 / 3");
  await expect(table).toContainText("30%");
  await expect(table).toContainText("75%");
  await expect(table).toContainText("环境占地过广 × 2");
  await page.getByRole("button", { name: "活动与设置", exact: true }).click();
  await page.getByLabel("导出构成", { exact: true }).selectOption("mixed");
  await page.getByLabel("混合样本数", { exact: true }).fill("20");
  await page.getByLabel("纯目标建筑份额", { exact: true }).fill("50");
  await page
    .getByLabel("包含候选校准数据（保持 calibration / excluded）", {
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "创建可重建发布", exact: true })
    .click();
  await expect(page.getByRole("link", { name: "下载发布工件" })).toBeVisible();
  const result = await (
    await request.get("http://127.0.0.1:8067/__test/state")
  ).json();
  expect(result.exportPosts).toHaveLength(1);
  expect(result.exportPosts[0]).toMatchObject({
    composition_count: 20,
    include_provisional: true,
    composition_weights: {
      pure_target: 50,
      light_context: 30,
      contextual: 20,
      environment_rich: 10,
    },
  });
  await page.getByText("建筑场景构成配额", { exact: true }).click();
  await page
    .getByRole("textbox", { name: "活动名称", exact: true })
    .fill("composition-ui-fixture");
  for (const [mode, value] of Object.entries({
    pure_target: "70",
    light_context: "20",
    contextual: "10",
    environment_rich: "0",
  })) {
    await page.locator(`input[name="composition_${mode}"]`).fill(value);
  }
  await page.getByRole("button", { name: "创建活动", exact: true }).click();
  await expect(page.getByText(/已创建：/)).toBeVisible();
  const created = await (
    await request.get("http://127.0.0.1:8067/__test/state")
  ).json();
  expect(created.campaignPosts[0].composition_weights).toEqual({
    pure_target: 70,
    light_context: 20,
    contextual: 10,
    environment_rich: 0,
  });
});

test("R09: repeated snapshot stays stale while fresh idle snapshots stay live", async ({
  page,
  request,
}) => {
  await page.clock.install();
  await request.post("http://127.0.0.1:8067/__test/change", {
    data: { frozenTime: 123 },
  });
  await page.goto("/");
  await expect(page.getByText("实时连接", { exact: true })).toBeVisible();
  await page.clock.fastForward(17000);
  await expect(
    page.getByRole("status").filter({ hasText: "快照已过期" }),
  ).toBeVisible();
  // The stream continues sending the same old server_time every second.
  await page.waitForTimeout(1200);
  await expect(
    page.getByRole("status").filter({ hasText: "快照已过期" }),
  ).toBeVisible();
  await request.post("http://127.0.0.1:8067/__test/change", {
    data: { frozenTime: null },
  });
  await expect(page.getByText("实时连接", { exact: true })).toBeVisible();
  await page.clock.fastForward(17000);
  await page.waitForTimeout(1200);
  await expect(page.getByText("实时连接", { exact: true })).toBeVisible();
});

test("T25: one live stream, disconnect freezes counters, reconnect reconciles snapshot", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(page.getByText("实时连接", { exact: true })).toBeVisible();
  await expect(page.locator(".stat").first().locator("strong")).toHaveText(
    "2 / 100",
  );
  await page.getByRole("button", { name: "覆盖与质量", exact: true }).click();
  await expect(page.getByText("群岛与水岸")).toBeVisible();
  await request.post("http://127.0.0.1:8067/__test/change", {
    data: { offline: true },
  });
  await expect(page.getByText(/连接断开 · 重连中/)).toBeVisible();
  await page.getByRole("button", { name: "运行总览", exact: true }).click();
  await expect(page.locator(".stat").first().locator("strong")).toHaveText(
    "2 / 100",
  );
  await request.post("http://127.0.0.1:8067/__test/change", {
    data: { offline: false, accepted: 3 },
  });
  await expect(page.getByText("实时连接", { exact: true })).toBeVisible();
  await expect(page.locator(".stat").first().locator("strong")).toHaveText(
    "3 / 100",
  );
  const state = await (
    await request.get("http://127.0.0.1:8067/__test/state")
  ).json();
  expect(state.maxStreams).toBeLessThanOrEqual(1);
});

test("T25: commands await application and repeated clicks do not duplicate POST", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const pause = page.getByRole("button", { name: "暂停", exact: true });
  await expect(pause).toBeEnabled();
  await pause.evaluate((button) => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  await expect(
    page.getByRole("button", { name: "等待应用…", exact: true }),
  ).toBeDisabled();
  await expect(page.getByText(/已应用：暂停/)).toBeVisible();
  await expect(page.locator(".campaign-control .badge")).toHaveText("已暂停");
  const state = await (
    await request.get("http://127.0.0.1:8067/__test/state")
  ).json();
  expect(state.commandPosts).toHaveLength(1);
});

test("T26: failed reads never switch to demo and unknown values remain unknown", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:8067/__test/change", {
    data: { errors: true, emptyMetrics: true },
  });
  await page.goto("/");
  await expect(page.getByText("费用未知", { exact: true })).toBeVisible();
  await expect(page.locator(".stat").nth(1).locator("strong")).toHaveText("—");
  await expect(page.getByText("尚无指标窗口")).toHaveCount(2);
  await expect(page.getByText(/数据库读取测试错误/)).toBeVisible();
  await expect(page.locator(".sample-card")).toHaveCount(0);
});

test("T28: registered artifacts and model text are displayed as inert text", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", {
      name: "查看样本 transport_fixture_001",
      exact: true,
    })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByText("<script>window.unsafeExecuted = true</script>", {
      exact: true,
    }),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "查看文本" }).first().click();
  await expect(dialog.locator(".source-code")).toContainText("<script>");
  expect(await page.evaluate(() => "unsafeExecuted" in window)).toBe(false);
  const paths = await dialog
    .locator("a[download]")
    .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
  expect(paths.every((path) => path?.startsWith("/api/v1/artifacts/"))).toBe(
    true,
  );
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

test("bounded sample paging and stage filtering never fetch the whole library", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: /真实渲染/ }).click();
  await expect(page.getByRole("combobox", { name: "阶段" })).toHaveValue(
    "render",
  );
  await expect(page.locator(".sample-card")).toHaveCount(24);
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.locator(".sample-card")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled();
  const state = await (
    await request.get("http://127.0.0.1:8067/__test/state")
  ).json();
  expect(
    state.requests
      .filter((item: { path: string }) => item.path.endsWith("/samples"))
      .every(
        (item: { query: { limit: string } }) => Number(item.query.limit) <= 24,
      ),
  ).toBe(true);
});

test("HttpOnly session credentials never enter browser storage", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "会话认证" }).click();
  await page.getByLabel("访问令牌").fill("offline-only-token");
  await page.getByRole("button", { name: "建立会话" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const cookies = await context.cookies();
  expect(
    cookies.find((cookie) => cookie.name === "voxlush_session")?.httpOnly,
  ).toBe(true);
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
});

test("uncertain command delivery reuses the identical durable request", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:8067/__test/change", {
    data: { commandFailOnce: true },
  });
  await page.goto("/");
  const pause = page.getByRole("button", { name: "暂停", exact: true });
  await expect(pause).toBeEnabled();
  await pause.click();
  await expect(page.getByRole("alert")).toContainText(
    "再次提交相同内容会复用同一命令 ID",
  );
  await pause.click();
  await expect(page.getByText(/已应用：暂停/)).toBeVisible();
  const state = await (
    await request.get("http://127.0.0.1:8067/__test/state")
  ).json();
  expect(state.commandPosts).toHaveLength(2);
  expect(state.commandPosts[0]).toEqual(state.commandPosts[1]);
});

test("different cap payloads receive different command IDs after uncertain delivery", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:8067/__test/change", {
    data: { commandFailOnce: true },
  });
  await page.goto("/");
  await page.getByRole("button", { name: "活动与设置", exact: true }).click();
  await page.getByLabel("新的 API 并发硬上限").fill("1");
  await page.getByRole("button", { name: "应用并发上限" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "再次提交相同内容会复用同一命令 ID",
  );
  await page.getByLabel("新的 API 并发硬上限").fill("2");
  await page.getByRole("button", { name: "应用并发上限" }).click();
  await expect(page.getByText(/已应用：更新并发上限/)).toBeVisible();
  const state = await (
    await request.get("http://127.0.0.1:8067/__test/state")
  ).json();
  expect(state.commandPosts).toHaveLength(2);
  expect(state.commandPosts[0].command_id).not.toEqual(
    state.commandPosts[1].command_id,
  );
  expect(
    state.commandPosts.map(
      (command: { payload: { api_cap: number } }) => command.payload.api_cap,
    ),
  ).toEqual([1, 2]);
});

test("four pages fit mobile and expose true debt and background export status", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "会话认证", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  expect(
    await page
      .getByRole("dialog")
      .evaluate((dialog) => dialog.contains(document.activeElement)),
  ).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "覆盖与质量", exact: true }).click();
  await expect(page.getByText("欠 23", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "活动与设置", exact: true }).click();
  await page.getByRole("button", { name: "创建可重建发布" }).click();
  await expect(page.getByRole("link", { name: "下载发布工件" })).toBeVisible();
  await page.screenshot({
    path: "test-results/mobile-settings.png",
    fullPage: true,
  });
});
