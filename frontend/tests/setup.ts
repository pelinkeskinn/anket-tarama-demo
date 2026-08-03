import "@testing-library/jest-dom/vitest";

HTMLCanvasElement.prototype.getContext = function getContext() {
  return {
    drawImage: vi.fn()
  } as unknown as CanvasRenderingContext2D;
};

HTMLCanvasElement.prototype.toBlob = function toBlob(callback: BlobCallback) {
  callback(new Blob(["image"], { type: "image/jpeg" }));
};

