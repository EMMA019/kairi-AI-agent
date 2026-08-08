import { describe, it, expect, beforeEach } from "vitest";
import { t, setLocaleLocal, getLocale } from "./index";

describe("i18n", () => {
  beforeEach(() => {
    setLocaleLocal("en");
  });

  it("returns English by default", () => {
    expect(getLocale()).toBe("en");
    expect(t("input.location")).toBe("Location");
    expect(t("status.thinking")).toBe("Thinking...");
  });

  it("switches to Japanese", () => {
    setLocaleLocal("ja");
    expect(t("input.location")).toBe("現在地");
    expect(t("status.thinking")).toBe("考え中...");
    expect(t("status.pipelineHeader")).toContain("考え");
  });

  it("interpolates vars", () => {
    setLocaleLocal("en");
    expect(t("input.locationTag", { lat: "1.2", lon: "3.4" })).toBe(
      "[Location GPS: 1.2, 3.4] "
    );
  });
});
