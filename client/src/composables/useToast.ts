import { ElMessage } from 'element-plus'

const TOAST_DURATIONS = {
  success: 2000,
  error: 4000,
  warning: 3000,
  info: 2500,
}

export function useToast() {
  return {
    success: (msg: string, opts?: { duration?: number }) =>
      ElMessage({
        type: 'success',
        message: msg,
        duration: opts?.duration ?? TOAST_DURATIONS.success,
        grouping: true,
        offset: 24,
        customClass: 'sp-toast sp-toast--success',
      }),
    error: (msg: string, opts?: { duration?: number }) =>
      ElMessage({
        type: 'error',
        message: msg,
        duration: opts?.duration ?? TOAST_DURATIONS.error,
        grouping: true,
        offset: 24,
        customClass: 'sp-toast sp-toast--error',
      }),
    warning: (msg: string, opts?: { duration?: number }) =>
      ElMessage({
        type: 'warning',
        message: msg,
        duration: opts?.duration ?? TOAST_DURATIONS.warning,
        grouping: true,
        offset: 24,
        customClass: 'sp-toast sp-toast--warning',
      }),
    info: (msg: string, opts?: { duration?: number }) =>
      ElMessage({
        type: 'info',
        message: msg,
        duration: opts?.duration ?? TOAST_DURATIONS.info,
        grouping: true,
        offset: 24,
        customClass: 'sp-toast sp-toast--info',
      }),
    confirm: (...args: Parameters<typeof import('element-plus')['ElMessageBox']['confirm']>) =>
      import('element-plus').then(({ ElMessageBox }) => ElMessageBox.confirm(...args)),
  }
}
