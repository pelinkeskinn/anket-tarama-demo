export type CaptureRegion = { x: number; y: number; width: number; height: number };

export const MAX_CAPTURE_SIDE = 2000;
export const CAMERA_JPEG_QUALITY = 0.8;

export function captureScale(width: number, height: number, maxSide = MAX_CAPTURE_SIDE): number {
  return Math.min(1, maxSide / Math.max(width, height, 1));
}

export function fullCameraFrame(video: HTMLVideoElement): CaptureRegion {
  const videoWidth = video.videoWidth || 1920;
  const videoHeight = video.videoHeight || 1080;
  return { x: 0, y: 0, width: videoWidth, height: videoHeight };
}

export function guideCaptureRegion(video: HTMLVideoElement, guide: HTMLElement | null): CaptureRegion {
  const fallback = fullCameraFrame(video);
  if (!guide || fallback.width <= 1 || fallback.height <= 1) return fallback;

  const videoRect = video.getBoundingClientRect();
  const guideRect = guide.getBoundingClientRect();
  if (videoRect.width <= 1 || videoRect.height <= 1 || guideRect.width <= 1 || guideRect.height <= 1) return fallback;

  // CSS object-fit: cover scales the camera frame and crops its overflow.
  // Reverse that transform so the visible A4 guide maps to real camera pixels.
  const coverScale = Math.max(videoRect.width / fallback.width, videoRect.height / fallback.height);
  const renderedWidth = fallback.width * coverScale;
  const renderedHeight = fallback.height * coverScale;
  const offsetX = (videoRect.width - renderedWidth) / 2;
  const offsetY = (videoRect.height - renderedHeight) / 2;
  // Keep only a tiny safety margin: the guide itself represents the sheet
  // boundary and the backend can use this crop as normalized page geometry.
  const padding = Math.min(guideRect.width, guideRect.height) * 0.01;

  const displayLeft = guideRect.left - videoRect.left - padding;
  const displayTop = guideRect.top - videoRect.top - padding;
  const displayRight = guideRect.right - videoRect.left + padding;
  const displayBottom = guideRect.bottom - videoRect.top + padding;
  const left = clamp((displayLeft - offsetX) / coverScale, 0, fallback.width - 1);
  const top = clamp((displayTop - offsetY) / coverScale, 0, fallback.height - 1);
  const right = clamp((displayRight - offsetX) / coverScale, left + 1, fallback.width);
  const bottom = clamp((displayBottom - offsetY) / coverScale, top + 1, fallback.height);

  if (right - left < fallback.width * 0.18 || bottom - top < fallback.height * 0.35) return fallback;
  return { x: left, y: top, width: right - left, height: bottom - top };
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}
