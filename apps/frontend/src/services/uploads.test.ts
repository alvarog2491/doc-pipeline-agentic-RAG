import { describe, expect, it, vi } from "vitest";
import { MAX_UPLOAD_BYTES, parseUploadTicket, type UploadTicket } from "@doc-pipeline/shared-types";
import { requestUpload, uploadToS3, validateFile, type UploadRequestLike } from "./uploads";

const ticket: UploadTicket = {
  url: "https://bucket.s3.eu-central-1.amazonaws.com/",
  fields: { key: "uploads/a.pdf", policy: "p", "x-amz-signature": "s" },
  key: "uploads/a.pdf",
  maxBytes: MAX_UPLOAD_BYTES,
};

describe("validateFile", () => {
  it("accepts PDFs by type or by extension", () => {
    expect(validateFile({ name: "a.pdf", size: 10, type: "application/pdf" })).toBeNull();
    expect(validateFile({ name: "A.PDF", size: 10, type: "" })).toBeNull();
  });

  it.each([
    [{ name: "a.txt", size: 10, type: "text/plain" }, "Only PDF"],
    [{ name: "a.pdf", size: 0, type: "application/pdf" }, "empty"],
    [{ name: "a.pdf", size: MAX_UPLOAD_BYTES + 1, type: "application/pdf" }, "larger than"],
  ])("rejects %j", (file, message) => {
    expect(validateFile(file)).toContain(message);
  });
});

describe("parseUploadTicket", () => {
  it("accepts a well-formed ticket", () => {
    expect(parseUploadTicket(ticket)).toEqual(ticket);
  });

  it.each([
    ["plain http url", { ...ticket, url: "http://x.example/" }],
    ["missing fields", { ...ticket, fields: undefined }],
    ["non-string field value", { ...ticket, fields: { key: 1 } }],
    ["missing key", { ...ticket, key: undefined }],
  ])("rejects %s", (_label, value) => {
    expect(() => parseUploadTicket(value)).toThrow("Unsupported upload ticket");
  });
});

describe("requestUpload", () => {
  it("posts the file name and size, omitting the default chunking", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify(ticket)));

    const result = await requestUpload({ name: "a.pdf", size: 5 }, "semantic", fetchImpl as unknown as typeof fetch);

    expect(result).toEqual(ticket);
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1].body))).toEqual({ filename: "a.pdf", sizeBytes: 5 });
  });

  it("sends a non-default chunking choice", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify(ticket)));

    await requestUpload({ name: "a.pdf", size: 5 }, "none", fetchImpl as unknown as typeof fetch);

    expect(JSON.parse(String(fetchImpl.mock.calls[0][1].body)).chunking).toBe("none");
  });

  it("surfaces the server's reason when the request is refused", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "The file exceeds the 100 MB limit" }), { status: 422 }));

    await expect(requestUpload({ name: "a.pdf", size: 5 }, undefined, fetchImpl as unknown as typeof fetch)).rejects.toThrow(
      "The file exceeds the 100 MB limit",
    );
  });
});

class FakeRequest implements UploadRequestLike {
  upload: UploadRequestLike["upload"] = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 204;
  opened: [string, string] | null = null;
  body: FormData | null = null;
  aborted = false;
  open(method: string, url: string) {
    this.opened = [method, url];
  }
  send(body: FormData) {
    this.body = body;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
}

describe("uploadToS3", () => {
  it("posts the signed fields first and the file last, reporting progress", async () => {
    const request = new FakeRequest();
    const progress: number[] = [];
    const file = new Blob(["%PDF"], { type: "application/pdf" });

    const done = uploadToS3(ticket, file, (f) => progress.push(f), undefined, () => request);
    request.upload.onprogress?.({ loaded: 1, total: 4, lengthComputable: true });
    request.onload?.();
    await done;

    expect(request.opened).toEqual(["POST", ticket.url]);
    expect([...(request.body as FormData).keys()]).toEqual(["key", "policy", "x-amz-signature", "file"]);
    expect(progress).toEqual([0.25, 1]);
  });

  it("rejects when S3 refuses the file", async () => {
    const request = new FakeRequest();
    request.status = 403;

    const done = uploadToS3(ticket, new Blob(["x"]), () => {}, undefined, () => request);
    request.onload?.();

    await expect(done).rejects.toThrow("status 403");
  });

  it("rejects on a network failure and can be cancelled", async () => {
    const failing = new FakeRequest();
    const failed = uploadToS3(ticket, new Blob(["x"]), () => {}, undefined, () => failing);
    failing.onerror?.();
    await expect(failed).rejects.toThrow("connection");

    const cancellable = new FakeRequest();
    const controller = new AbortController();
    const cancelled = uploadToS3(ticket, new Blob(["x"]), () => {}, controller.signal, () => cancellable);
    controller.abort();
    await expect(cancelled).rejects.toThrow("cancelled");
    expect(cancellable.aborted).toBe(true);
  });
});
