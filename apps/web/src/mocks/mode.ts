/** Dev uses MSW so the shell does not wait on harness routes. Set VITE_USE_MSW=false to call the API. */
export function shouldUseMocks(): boolean {
  const flag = import.meta.env.VITE_USE_MSW;
  if (flag === "true") return true;
  if (flag === "false") return false;
  return import.meta.env.DEV;
}
