export function reduceDeleteDialogState(current, action) {
  if (action.type === "open") {
    return {
      open: true,
      provider: action.provider,
    };
  }

  if (action.type === "close") {
    return {
      open: false,
      provider: current.provider,
    };
  }

  if (action.type === "clear") {
    return {
      open: false,
      provider: null,
    };
  }

  return current;
}
