export function didEffectiveModelsChange(current, next) {
  if (current.length !== next.length) {
    return true;
  }

  return current.some((name, index) => name !== next[index]);
}
