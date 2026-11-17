import { describe, expect, it } from "vitest";
import { THEME_NAMES, nextTheme } from "./theme";

describe("nextTheme", () => {
  it("cycles auto → light → dark → auto", () => {
    expect(nextTheme("auto")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("auto");
  });

  it("names every theme", () => {
    expect(Object.keys(THEME_NAMES).sort()).toEqual(["auto", "dark", "light"]);
  });
});
