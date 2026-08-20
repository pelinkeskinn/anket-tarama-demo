import { describe, expect, test } from "vitest";

import { captureScale, framesEqual, fullCameraFrame, guideCaptureRegion } from "../app/camera";

function rect(left: number, top: number, width: number, height: number): DOMRect {
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) } as DOMRect;
}

describe("camera capture region", () => {
  test("maps the visible portrait guide into covered camera pixels", () => {
    const video = {
      videoWidth: 2560,
      videoHeight: 1920,
      getBoundingClientRect: () => rect(0, 0, 390, 600)
    } as HTMLVideoElement;
    const guide = { getBoundingClientRect: () => rect(50, 95, 290, 410) } as HTMLElement;

    const region = guideCaptureRegion(video, guide);

    expect(region.width / region.height).toBeCloseTo(210 / 297, 1);
    expect(region.width).toBeLessThan(video.videoWidth);
    expect(region.height).toBeGreaterThan(video.videoHeight * 0.65);
    expect(region.x).toBeGreaterThan(0);
  });

  test("limits capture scale to a 2000px long side", () => {
    expect(captureScale(4000, 3000)).toBeCloseTo(0.5);
    expect(captureScale(800, 600)).toBe(1);
  });

  test("falls back to the full frame before layout is available", () => {
    const video = {
      videoWidth: 1920,
      videoHeight: 1080,
      getBoundingClientRect: () => rect(0, 0, 0, 0)
    } as HTMLVideoElement;

    expect(guideCaptureRegion(video, null)).toEqual(fullCameraFrame(video));
  });

  test("detects identical frozen frames", () => {
    const frame = new Uint8ClampedArray([1, 2, 3]);
    expect(framesEqual(frame, new Uint8ClampedArray([1, 2, 3]))).toBe(true);
    expect(framesEqual(frame, new Uint8ClampedArray([1, 2, 4]))).toBe(false);
    expect(framesEqual(null, frame)).toBe(false);
  });
});
