import React from "react";
import { copyToClipboard } from "../utils/clipboard";

type State = {
  hasError: boolean;
  error: Error | null;
  copied: boolean;
};

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { hasError: false, error: null, copied: false };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error, copied: false };
  }

  private diagnostics(): string {
    const err = this.state.error;
    const lines = [
      "Kairi diagnostics",
      `time: ${new Date().toISOString()}`,
      `url: ${typeof location !== "undefined" ? location.href : ""}`,
      `ua: ${typeof navigator !== "undefined" ? navigator.userAgent : ""}`,
      `error: ${err?.toString() || "unknown"}`,
      "",
      err?.stack || "",
    ];
    return lines.join("\n");
  }

  private handleCopy = async () => {
    await copyToClipboard(this.diagnostics());
    this.setState({ copied: true });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: 24,
            color: "#e5e7eb",
            backgroundColor: "#0e121a",
            height: "100vh",
            width: "100vw",
            overflow: "auto",
            fontFamily: "ui-sans-serif, system-ui, sans-serif",
          }}
        >
          <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>Something went wrong</h1>
          <p style={{ fontSize: 13, color: "#9ca3af", marginBottom: 16, maxWidth: 520 }}>
            Copy the diagnostics below if you need help with startup or key setup. Restart the desktop
            window after fixing the issue.
          </p>
          <p style={{ fontWeight: 600, color: "#fca5a5", marginBottom: 12 }}>
            {this.state.error?.toString()}
          </p>
          <button
            type="button"
            onClick={() => void this.handleCopy()}
            style={{
              marginBottom: 12,
              padding: "8px 14px",
              borderRadius: 10,
              border: "1px solid #334155",
              background: "#1e293b",
              color: "#e2e8f0",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            {this.state.copied ? "Copied" : "Copy diagnostics"}
          </button>
          <pre
            style={{
              fontSize: 12,
              marginTop: 8,
              padding: 12,
              borderRadius: 10,
              background: "#020617",
              border: "1px solid #1e293b",
              whiteSpace: "pre-wrap",
              color: "#94a3b8",
            }}
          >
            {this.state.error?.stack}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}
