/** pywebview creates api={} before installing its methods; readiness is atomic here. */
export function readyNativeApi(value: unknown): boolean {
  return !!value && typeof value === 'object' && ['status', 'set_mode', 'close_app'].every(
    key => typeof (value as Record<string, unknown>)[key] === 'function',
  )
}
