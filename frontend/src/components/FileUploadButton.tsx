import { useRef } from "react";

interface FileUploadButtonProps {
  onFileSelect: (file: File) => void;
  disabled: boolean;
}

export function FileUploadButton({ onFileSelect, disabled }: FileUploadButtonProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onFileSelect(file);
      // 同じファイルを連続で選べるようにリセット
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  return (
    <div className="relative flex items-center">
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        className="hidden"
        accept=".txt,.md,.csv,.py,.js,.ts,.json"
        disabled={disabled}
      />
      <button
        type="button"
        className={`p-2 rounded-full transition-colors flex items-center justify-center ${
          disabled 
            ? "text-gray-600 cursor-not-allowed" 
            : "text-gray-400 hover:text-white hover:bg-[#282a2c]"
        }`}
        onClick={() => fileInputRef.current?.click()}
        disabled={disabled}
        title="ファイルを添付"
        aria-label="ファイルを添付"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
        </svg>
      </button>
    </div>
  );
}
