import { describe, expect, it } from "vitest";
import { completesPanelCollapse } from "./pdfSidePanelTransition";

describe("completesPanelCollapse", () => {
  it("unmounts after the desktop width collapse finishes", () => {
    expect(completesPanelCollapse(false, "width", true)).toBe(true);
  });

  it("unmounts after the mobile horizontal transform finishes", () => {
    expect(completesPanelCollapse(false, "transform", true)).toBe(true);
  });

  it("ignores opening and descendant transitions", () => {
    expect(completesPanelCollapse(true, "width", true)).toBe(false);
    expect(completesPanelCollapse(false, "opacity", true)).toBe(false);
    expect(completesPanelCollapse(false, "width", false)).toBe(false);
  });
});
