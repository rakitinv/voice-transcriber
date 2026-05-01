import { describe, it, expect } from "vitest";
import { inferAudioFormatFromFilename } from "./upload";

describe("inferAudioFormatFromFilename", () => {
  it("returns extension for known types", () => {
    expect(inferAudioFormatFromFilename("x.webm")).toBe("webm");
    expect(inferAudioFormatFromFilename("PATH/file.WAV")).toBe("wav");
    expect(inferAudioFormatFromFilename("a.m4a")).toBe("m4a");
  });

  it("returns null for unknown or missing extension", () => {
    expect(inferAudioFormatFromFilename("noext")).toBeNull();
    expect(inferAudioFormatFromFilename("x.xyz")).toBeNull();
    expect(inferAudioFormatFromFilename("")).toBeNull();
  });
});
