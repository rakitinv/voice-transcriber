import { describe, it, expect } from "vitest";
import { createPkcePair, parseOAuthRedirect, parseServiceTokensFromOAuthRedirect } from "./oauth";

describe("parseOAuthRedirect", () => {
  it("reads code and state from query", () => {
    const r = parseOAuthRedirect("https://ext/id.html?code=abc123&state=xyz");
    expect(r.code).toBe("abc123");
    expect(r.state).toBe("xyz");
    expect(r.error).toBeNull();
  });

  it("reads code from hash fragment", () => {
    const r = parseOAuthRedirect("https://ext/callback#code=hashcode&state=s1");
    expect(r.code).toBe("hashcode");
    expect(r.state).toBe("s1");
  });

  it("prefers query over hash when both present", () => {
    const r = parseOAuthRedirect("https://x/?code=q&state=sq#code=h&state=sh");
    expect(r.code).toBe("q");
    expect(r.state).toBe("sq");
  });

  it("returns nulls on invalid URL", () => {
    const r = parseOAuthRedirect("not-a-url");
    expect(r.code).toBeNull();
    expect(r.state).toBeNull();
    expect(r.error).toBeNull();
  });
});

describe("createPkcePair", () => {
  it("produces RFC 7636 lengths (verifier ≥43 chars; challenge from SHA-256)", async () => {
    const { verifier, challenge } = await createPkcePair();
    expect(verifier.length).toBeGreaterThanOrEqual(43);
    expect(verifier.length).toBeLessThanOrEqual(128);
    expect(challenge.length).toBeGreaterThanOrEqual(43);
  });
});

describe("parseServiceTokensFromOAuthRedirect", () => {
  it("reads tokens from URL fragment", () => {
    const r = parseServiceTokensFromOAuthRedirect(
      "https://abc.chromiumapp.org/oauth2#access_token=aa.bb.cc&refresh_token=secret"
    );
    expect(r.accessToken).toBe("aa.bb.cc");
    expect(r.refreshToken).toBe("secret");
    expect(r.error).toBeNull();
  });

  it("reads OAuth errors from fragment", () => {
    const r = parseServiceTokensFromOAuthRedirect(
      "https://abc.chromiumapp.org/oauth2#error=access_denied&error_description=no"
    );
    expect(r.accessToken).toBeNull();
    expect(r.error).toBe("access_denied");
    expect(r.errorDescription).toBe("no");
  });
});
