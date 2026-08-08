import { useState, useRef, useEffect } from "react";
import { useViolation } from "../hooks/useViolation";
import type { ViolationType } from "../types";

interface ViolationButtonProps {
  sessionId: string;
  userMessage: string;
  aiResponse: string;
}

const VIOLATION_TYPES: ViolationType[] = [
  "Unsolicited Proposal",
  "Unauthorized Memory",
  "Repeated Questions",
  "Excessive Praise",
  "Other",
];

export function ViolationButton({
  sessionId,
  userMessage,
  aiResponse,
}: ViolationButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [showReasonInput, setShowReasonInput] = useState(false);
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const { submitViolation, isSubmitting } = useViolation();
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close popover when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setShowReasonInput(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = async (type: ViolationType) => {
    if (type === "Other" && !showReasonInput) {
      setShowReasonInput(true);
      return;
    }
    
    const success = await submitViolation(
      sessionId,
      userMessage,
      aiResponse,
      type,
      type === "Other" ? reason : undefined
    );

    if (success) {
      setSubmitted(true);
      setIsOpen(false);
    }
  };

  if (submitted) {
    return <span className="violation-submitted text-xs text-gray-500 ml-2 select-none" title="Submitted">✓ Reported</span>;
  }

  return (
    <div className="violation-wrapper relative inline-block ml-2" ref={popoverRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="text-xs text-[#8b949e] hover:text-[#c9d1d9] transition-colors p-1 rounded hover:bg-[#30363d] flex items-center justify-center"
        title="Report issue or rule violation"
        aria-label="Report issue or rule violation"
        disabled={isSubmitting}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"></path>
          <line x1="4" y1="22" x2="4" y2="15"></line>
        </svg>
      </button>

      {isOpen && (
        <>
          {/* モバイル用背景オーバーレイ */}
          <div className="fixed inset-0 z-[90] bg-black/60 sm:hidden animate-fade-in" onClick={() => setIsOpen(false)} />
          
          <div className="violation-popover z-[100] bg-[#282a2c] border-[#3c4043] overflow-hidden flex flex-col
            fixed bottom-0 left-0 right-0 rounded-t-2xl border-t sm:rounded-lg sm:border pb-safe
            sm:absolute sm:bottom-full sm:right-0 sm:left-auto sm:mb-2 sm:w-48 sm:origin-bottom-right sm:pb-0
            animate-slide-up sm:animate-none shadow-[0_-8px_30px_rgba(0,0,0,0.5)] sm:shadow-lg">
            
            <div className="text-xs text-gray-400 p-3 sm:p-2 border-b border-[#3c4043] bg-[#1e1f20] flex justify-between items-center">
              <span>What issue did you notice?</span>
              <button className="sm:hidden text-gray-500 hover:text-white p-1" onClick={() => setIsOpen(false)}>✕</button>
            </div>
          {!showReasonInput ? (
            <ul className="flex flex-col">
              {VIOLATION_TYPES.map((type) => (
                <li key={type}>
                  <button
                    className="w-full text-left px-3 py-2 text-sm hover:bg-[#37393b] text-gray-200 transition-colors"
                    onClick={() => handleSelect(type)}
                  >
                    {type}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="p-2 flex flex-col gap-2">
              <input
                type="text"
                placeholder="Please describe the reason"
                className="w-full bg-[#1e1f20] text-sm text-gray-200 border border-[#3c4043] rounded px-2 py-1 outline-none focus:border-blue-500"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                autoFocus
              />
              <div className="flex justify-end gap-2 mt-1">
                <button 
                  className="text-xs text-gray-400 hover:text-white"
                  onClick={() => setShowReasonInput(false)}
                >
                  Back
                </button>
                <button 
                  className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-2 py-1 rounded disabled:opacity-50"
                  onClick={() => handleSelect("Other")}
                  disabled={!reason.trim() || isSubmitting}
                >
                  Submit
                </button>
              </div>
            </div>
          )}
        </div>
        </>
      )}
    </div>
  );
}
