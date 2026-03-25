// This script suppresses hydration warnings from React DevTools
// These warnings are harmless and occur due to Radix UI generating random IDs

(function() {
  const originalConsoleError = console.error;
  console.error = function(...args) {
    // Suppress hydration-related warnings
    if (
      args[0] && 
      typeof args[0] === 'string' && 
      (args[0].includes('hydration') || 
       args[0].includes('Hydration failed') ||
       args[0].includes('data-testid') ||
       args[0].includes('form_signature') ||
       args[0].includes('data-slot="textarea"'))
    ) {
      return;
    }
    originalConsoleError.apply(console, args);
  };
})();
