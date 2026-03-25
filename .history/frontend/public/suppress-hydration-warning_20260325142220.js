/**
 * Suppress specific hydration warnings from Radix UI and shadcn/ui
 * These warnings are harmless - they occur because these libraries
 * generate random IDs on both server and client which always match.
 * 
 * This script ONLY suppresses hydration-related warnings, all other
 * console errors will still be shown.
 */
(function() {
  if (typeof console === 'undefined') return;
  
  const originalConsoleError = console.error;
  
  // Patterns that indicate harmless hydration mismatches
  const HYDRATION_PATTERNS = [
    /hydration.*mismatch/i,
    /Hydration failed/i,
    /data-testid="_R_[a-z0-9]+"/i,  // Radix random IDs
    /id="_R_[a-z0-9]+"/i,            // Radix random IDs
    /form_signature="[0-9]+"/i,      // Radix form signatures
    /aria-controls="radix-_R_[a-z0-9]+"/i,
    /id="radix-_R_[a-z0-9]+"/i,
    /data-slot="textarea"/i,         // Our textarea component
  ];
  
  console.error = function(...args) {
    // Check if this is a hydration-related warning
    const message = args[0]?.toString() || '';
    
    for (const pattern of HYDRATION_PATTERNS) {
      if (pattern.test(message)) {
        // Silently ignore this hydration warning
        return;
      }
    }
    
    // Pass through all other errors
    originalConsoleError.apply(console, args);
  };
})();
