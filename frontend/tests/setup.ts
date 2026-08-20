import { vi } from "vitest";
import "@testing-library/jest-dom/vitest";

Object.defineProperty(window, "isSecureContext", {
  configurable: true,
  value: true
});

window.scrollTo = vi.fn();

HTMLCanvasElement.prototype.getContext = function getContext() {
  return {
    drawImage: vi.fn()
  } as unknown as CanvasRenderingContext2D;
};

HTMLCanvasElement.prototype.toBlob = function toBlob(callback: BlobCallback) {
  callback(new Blob(["image"], { type: "image/jpeg" }));
};

