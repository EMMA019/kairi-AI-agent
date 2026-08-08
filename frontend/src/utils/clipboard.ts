export const copyToClipboard = async (text: string): Promise<void> => {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (err) {
      console.warn("Clipboard API failed, falling back to execCommand", err);
    }
  }

  // Fallback for insecure contexts (e.g., HTTP on mobile/local network)
  const textArea = document.createElement("textarea");
  textArea.value = text;
  
  // Avoid scrolling to bottom
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";

  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  try {
    const successful = document.execCommand("copy");
    if (!successful) {
      throw new Error("Fallback: Copy command was unsuccessful");
    }
  } catch (err) {
    console.error("Fallback: Oops, unable to copy", err);
    throw err;
  } finally {
    document.body.removeChild(textArea);
  }
};
