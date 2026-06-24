import { describe, expect, it } from "bun:test";
import { readPipedSecret, trimSecret } from "../../../src/auth/client/read-secret";

// Fake a piped (non-TTY) stdin: an async iterable of chunks, the shape
// readPipedSecret consumes. The TTY path needs a real terminal, so it isn't
// unit-tested here.
async function* streamOf(...chunks: Array<string | Uint8Array>) {
  for (const chunk of chunks) yield chunk;
}

describe("read-secret (piped path)", () => {
  it("reads a piped value and trims the trailing newline", async () => {
    expect(await readPipedSecret(streamOf("sk-ant-piped\n"))).toBe("sk-ant-piped");
  });

  it("joins multiple chunks and trims surrounding whitespace", async () => {
    expect(await readPipedSecret(streamOf("  sk-ant", "-multi  \n"))).toBe("sk-ant-multi");
  });

  it("decodes Uint8Array chunks", async () => {
    const bytes = new TextEncoder().encode("sk-ant-bytes\n");
    expect(await readPipedSecret(streamOf(bytes))).toBe("sk-ant-bytes");
  });

  it("trimSecret matches hashToken's trim semantics", () => {
    expect(trimSecret("  x \n")).toBe("x");
  });
});
