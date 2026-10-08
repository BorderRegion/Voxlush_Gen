import { expect, test } from "@playwright/test";

test("real isolated build/render, persistent control, authenticated artifacts and empty formal export", async ({
  page,
  context,
}) => {
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto("/");
  await expect(page.getByText("登录后访问").first()).toBeVisible();
  await page.getByRole("button", { name: "会话认证", exact: true }).click();
  await page.getByLabel("访问令牌").fill("offline-browser-test-token");
  await page.getByRole("button", { name: "建立会话", exact: true }).click();
  await expect(page.getByText("实时连接", { exact: true })).toBeVisible();
  await expect(page.locator(".stat").first().locator("strong")).toHaveText(
    "0 / 3",
  );
  await expect(page.locator(".stat").first().locator("small")).toHaveText(
    "1 个暂定通过，未计入合格",
  );
  await expect(page.locator(".sample-card img")).toHaveCount(1);
  await expect
    .poll(() =>
      page
        .locator(".sample-card img")
        .evaluate((image) => (image as HTMLImageElement).naturalWidth),
    )
    .toBeGreaterThan(0);
  await page
    .getByRole("button", { name: "查看样本 browser_real_islands", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".detail-previews img")).toHaveCount(3);
  const loaded = await dialog
    .locator(".detail-previews img")
    .evaluateAll((images) =>
      images.every(
        (image) =>
          (image as HTMLImageElement).complete &&
          (image as HTMLImageElement).naturalWidth > 0,
      ),
    );
  expect(loaded).toBe(true);
  await expect(dialog.getByText("暂定通过", { exact: true })).toBeVisible();
  await expect(dialog.locator(".detail-meta")).not.toContainText("1970");
  await page.screenshot({
    path: "test-results/real-sample.png",
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "暂停", exact: true }).click();
  await expect(page.getByText(/已应用：暂停/)).toBeVisible();
  await expect(page.locator(".campaign-control .badge")).toHaveText("已暂停");
  const secondPage = await context.newPage();
  await page.close();
  await secondPage.goto("/");
  await expect(secondPage.locator(".campaign-control .badge")).toHaveText(
    "已暂停",
  );
  await secondPage
    .getByRole("button", { name: "活动与设置", exact: true })
    .click();
  await secondPage.getByRole("button", { name: "创建可重建发布" }).click();
  const card = secondPage.getByRole("link", {
    name: "下载：dataset_card.json",
    exact: true,
  });
  await expect(card).toBeVisible();
  const release = await context.request.get((await card.getAttribute("href"))!);
  expect(release.ok()).toBe(true);
  const data = await release.json();
  expect(data.counts.accepted).toBe(0);
  expect(data.counts.assets).toBe(0);
  await secondPage.getByText("查看脱敏配置与校验", { exact: true }).click();
  await secondPage
    .getByRole("button", { name: "校验配置", exact: true })
    .click();
  await expect(
    secondPage.getByText("本地配置格式通过", { exact: true }),
  ).toBeVisible();
  await secondPage.screenshot({
    path: "test-results/real-settings.png",
    fullPage: true,
  });
  const cookies = await context.cookies();
  expect(
    cookies.find((cookie) => cookie.name === "voxlush_session")?.httpOnly,
  ).toBe(true);
  expect(
    await secondPage.evaluate(() => [
      localStorage.length,
      sessionStorage.length,
    ]),
  ).toEqual([0, 0]);
  expect(browserErrors).toEqual([]);
});
