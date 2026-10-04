import { describe, expect, it } from "vitest";
import { defangUrl, segmentUntrusted } from "./safe-text";

describe("defanging", () => {
  it("defangs scheme, host dots and userinfo; keeps the path readable", () => {
    expect(defangUrl("https://evil.example.com/a/b?x=1")).toBe("hxxps://evil[.]example[.]com/a/b?x=1");
    expect(defangUrl("http://user@evil.example/x")).toBe("hxxp://user[@]evil[.]example/x");
    expect(defangUrl("www.evil.com/pay")).toBe("www[.]evil[.]com/pay");
  });
  it("splits text into plain and link segments, leaving trailing punctuation outside", () => {
    const segs = segmentUntrusted("Visit https://evil.example/login, now! Or bank-secure.support/verify");
    const links = segs.filter((s) => s.kind === "link").map((s) => (s.kind === "link" ? s.defanged : ""));
    expect(links).toEqual(["hxxps://evil[.]example/login", "bank-secure[.]support/verify"]);
    expect(segs.map((s) => s.text).join("")).toBe("Visit https://evil.example/login, now! Or bank-secure.support/verify");
  });
  it("no links in plain prose", () => {
    expect(segmentUntrusted("Hello there, version 1.2 is fine.")).toEqual([{ kind: "text", text: "Hello there, version 1.2 is fine." }]);
  });
});
