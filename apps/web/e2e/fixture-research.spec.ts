import { expect, test, type Page } from "@playwright/test";

const screenshotDir = process.env.STAGE2_SCREENSHOT_DIR;

async function shot(page: Page, name: string): Promise<void> {
  if (!screenshotDir) return;
  await page.screenshot({ path: `${screenshotDir}/${name}.png`, fullPage: true });
}

test("fixture 6EZ6 research streams, saves, and reopens calc 1.0.0 levels", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Research 6EZ6" })).toBeVisible();
  await expect(page.getByRole("button", { name: /place order|submit order|buy|sell/i })).toHaveCount(0);
  await shot(page, "01-fixture-start");

  await page.getByTestId("run-6ez6").click();
  await expect(page.getByText(/deterministic_ta/)).toBeVisible({ timeout: 120_000 });
  await shot(page, "02-streamed-progress");
  await expect(page.getByRole("heading", { name: "6EZ6 research", exact: true }).nth(1)).toBeVisible({
    timeout: 120_000,
  });
  await expect(page.getByText(/DEMONSTRATION|FIXTURE DATA/).first()).toBeVisible();

  const legendLevel = page.locator("[data-testid='annotation-legend'] [data-calc='1.0.0']").first();
  await expect(legendLevel).toBeVisible();
  const savedPrice = await legendLevel.getAttribute("data-saved-level");
  expect(savedPrice).toBeTruthy();
  await expect(legendLevel).toContainText("calc 1.0.0");
  const matchingLevels = page.locator(`[data-testid='saved-levels'] [data-saved-level="${savedPrice ?? ""}"]`);
  expect(await matchingLevels.count()).toBeGreaterThan(0);
  await expect(page.locator("[data-testid='annotation-legend'] [data-calc]").first()).toHaveAttribute("data-calc", "1.0.0");
  await shot(page, "03-saved-calc-levels");

  const note = "Refresh keeps this fixture sentence.";
  const editor = page.getByTestId("narrative-editor");
  await editor.click();
  await editor.evaluate((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  });
  await page.keyboard.type(` ${note}`);
  await expect(page.getByTestId("draft-status")).toHaveText("Saving draft");
  await expect(page.getByTestId("draft-status")).toHaveText("Draft saved", { timeout: 10_000 });

  await page.getByRole("radio", { name: "Agent" }).click();
  await expect(editor).toContainText(note);
  await shot(page, "04-layout-keeps-edit");
  await page.getByRole("radio", { name: "Output" }).click();
  await expect(editor).toContainText(note);

  await page.getByRole("button", { name: "Save narrative revision" }).click();
  await expect(page.getByText(/Narrative edit/)).toBeVisible();

  await page.reload();
  await expect(editor).toContainText(note, { timeout: 20_000 });
  expect(await page.locator(`[data-testid='saved-levels'] [data-saved-level="${savedPrice ?? ""}"]`).count()).toBeGreaterThan(0);
  await shot(page, "05-refresh-reopens-artifact");

  await page.getByRole("link", { name: "Agents" }).click();
  await shot(page, "06-agents-saved-artifact");
  await page.getByRole("button", { name: "Reopen" }).first().click();
  await expect(editor).toContainText(note);
  await expect(page.getByRole("button", { name: /place order|submit order/i })).toHaveCount(0);
  await shot(page, "07-reopened-no-order-entry");
});
