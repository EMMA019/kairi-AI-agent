const KEY = "kairi_show_advanced_modes";

/** IDE / Char / Radar など上級 UI。既定は OFF（市況＋チャット本命）。 */
export function getShowAdvancedModes(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setShowAdvancedModes(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent("kairi-advanced-modes", { detail: on }));
}
