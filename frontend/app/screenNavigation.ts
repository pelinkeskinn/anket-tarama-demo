export type AppScreen =
  | "scanner"
  | "processing"
  | "manual"
  | "blankConfirm"
  | "success"
  | "duplicate"
  | "fatal"
  | "history"
  | "detail";

export function replaceAppScreen(screen: AppScreen) {
  window.history.replaceState({ screen }, "");
}

export function pushAppScreen(screen: AppScreen) {
  window.history.pushState({ screen }, "");
}

export function readPopStateScreen(event: PopStateEvent): AppScreen | null {
  const state = event.state as { screen?: unknown } | null;
  return typeof state?.screen === "string" ? (state.screen as AppScreen) : null;
}
