import {
  levelFromBytes,
  micErrorMessage,
  pickMimeType,
  recordingSupport,
} from "../src/lib/recorder";

describe("pickMimeType", () => {
  test("prefers webm/opus (Chrome, Firefox)", () => {
    expect(pickMimeType(() => true)).toBe("audio/webm;codecs=opus");
  });
  test("falls back to mp4/aac (Safari)", () => {
    expect(pickMimeType((t) => t.startsWith("audio/mp4"))).toBe("audio/mp4;codecs=mp4a.40.2");
  });
  test("ogg/opus when webm is missing", () => {
    expect(pickMimeType((t) => t.startsWith("audio/ogg"))).toBe("audio/ogg;codecs=opus");
  });
  test("null when nothing is supported, even if the probe throws", () => {
    expect(
      pickMimeType(() => {
        throw new Error("nope");
      }),
    ).toBeNull();
  });
});

describe("recordingSupport", () => {
  const good = {
    isSecureContext: true,
    navigator: { mediaDevices: { getUserMedia: () => undefined } },
    MediaRecorder: { isTypeSupported: (t: string) => t === "audio/mp4" },
  };
  test("reports the chosen type", () => {
    expect(recordingSupport(good)).toEqual({ ok: true, mimeType: "audio/mp4" });
  });
  test("explains each missing capability", () => {
    expect(recordingSupport({ ...good, isSecureContext: false })).toMatchObject({ ok: false, reason: expect.stringMatching(/https/) });
    expect(recordingSupport({ ...good, navigator: {} })).toMatchObject({ ok: false, reason: expect.stringMatching(/microphone/) });
    expect(recordingSupport({ ...good, MediaRecorder: undefined })).toMatchObject({ ok: false, reason: expect.stringMatching(/MediaRecorder/) });
    expect(recordingSupport({ ...good, MediaRecorder: { isTypeSupported: () => false } })).toMatchObject({ ok: false });
  });
});

test("mic errors get specific copy", () => {
  expect(micErrorMessage(new DOMException("x", "NotAllowedError"))).toMatch(/permission/);
  expect(micErrorMessage(new DOMException("x", "NotFoundError"))).toMatch(/No microphone/);
  expect(micErrorMessage("weird")).toMatch(/could not be opened/);
});

test("levelFromBytes: silence is 0, full scale is 1", () => {
  expect(levelFromBytes(new Uint8Array(256).fill(128))).toBe(0);
  const loud = new Uint8Array(256).map((_, i) => (i % 2 ? 255 : 0));
  expect(levelFromBytes(loud)).toBeGreaterThan(0.95);
  expect(levelFromBytes(new Uint8Array(0))).toBe(0);
});
