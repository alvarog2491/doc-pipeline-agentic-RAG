import { describe, expect, it } from "vitest";
import { renderCitations } from "./citations";

const citations = [
  { id: 1, page: 4, section: "A", url: "https://s3/x.pdf?sig=1#page=4" },
  { id: 2, page: 4, section: "A", url: "https://s3/x.pdf?sig=1#page=4" },
  { id: 3, page: 9, section: "B", url: null },
];

describe("renderCitations", () => {
  it("turns markers into page links attached to the preceding text", () => {
    expect(renderCitations("Max is 3 bar [[1]].", citations)).toBe(
      "Max is 3 bar [Page 4](https://s3/x.pdf?sig=1#page=4).",
    );
  });

  it("collapses duplicate pages inside one run and keeps distinct ones", () => {
    expect(renderCitations("Fact [[1]][[2]][[3]]", citations)).toBe(
      "Fact [Page 4](https://s3/x.pdf?sig=1#page=4) (Page 9)",
    );
  });

  it("hides markers that are unresolved or invented", () => {
    expect(renderCitations("Fact [[1]] and more [[99]].", undefined)).toBe("Fact and more.");
    expect(renderCitations("Fact [[99]].", citations)).toBe("Fact.");
  });

  it("hides a marker that is still streaming in", () => {
    for (const tail of ["[", "[[", "[[1", "[[1]"]) {
      expect(renderCitations(`Text ${tail}`, citations)).toBe("Text");
    }
  });

  it("leaves ordinary brackets alone", () => {
    expect(renderCitations("Use [option] here", citations)).toBe("Use [option] here");
  });
});
