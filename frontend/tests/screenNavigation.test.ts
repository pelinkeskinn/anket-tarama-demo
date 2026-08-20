import { describe, expect, test } from "vitest";

import { pushAppScreen, readPopStateScreen, replaceAppScreen } from "../app/screenNavigation";

describe("screen history", () => {
  test("stores the screen on pushState and reads it from popstate", () => {
    replaceAppScreen("scanner");
    pushAppScreen("history");
    const event = new PopStateEvent("popstate", { state: { screen: "manual" } });
    expect(readPopStateScreen(event)).toBe("manual");
    expect(readPopStateScreen(new PopStateEvent("popstate", { state: null }))).toBeNull();
  });
});
