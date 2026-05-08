/**
 * PatentHub PDF 下载二次确认 helper。
 *
 * 后端策略（见 backend/app/services/patenthub_budget.py）：
 * - 单轮最多 5 次 PDF 下载（每次 ¥1）
 * - 超额返回 HTTP 402 + detail.code='patenthub_budget_exceeded'
 * - 前端弹二次确认，用户同意 → 带 force=true 重发，绕过上限
 *
 * 用法：组件里把 `searchApi.downloadFulltext(...)` 改成 `downloadFulltextWithBudgetConfirm(...)`
 * 即可获得"超额弹窗 + 自动重试"能力，非 patenthub 源无副作用。
 */
import { ElMessageBox } from 'element-plus'
import { searchApi } from '../api/client'

export async function downloadFulltextWithBudgetConfirm(
  projectId: string,
  documentId: string,
  format: 'pdf' | 'html' | 'auto' = 'auto',
) {
  try {
    return await searchApi.downloadFulltext(projectId, documentId, format, false)
  } catch (e: any) {
    const status = e?.response?.status
    const detail = e?.response?.data?.detail
    if (status !== 402 || detail?.code !== 'patenthub_budget_exceeded') {
      throw e
    }

    const used = Number(detail.used ?? 0)
    const max = Number(detail.max ?? 5)

    // 每篇 PDF 实际成本 ≈ ¥1.1（1 次详情 0.1 + 1 次 PDF 1.0），详情与搜索共享计费
    const costPer = 1.1
    const costUsed = (used * costPer).toFixed(1)
    try {
      await ElMessageBox.confirm(
        `本轮已下载 ${used}/${max} 篇 PatentHub 专利 PDF（累计 ≈ ¥${costUsed}）。确定再下 1 篇？继续将再扣约 ¥1.1（含详情接口 ¥0.1 + PDF ¥1）。`,
        '超出单轮 PDF 预算',
        {
          confirmButtonText: `继续下载（≈¥1.1）`,
          cancelButtonText: '取消',
          type: 'warning',
          dangerouslyUseHTMLString: false,
        },
      )
    } catch (cancelErr) {
      // 用户取消 → 抛原始 402 让调用方恢复 UI（如 status 置回 not_attempted）
      throw e
    }

    // 二次确认通过，force=true 重发
    return await searchApi.downloadFulltext(projectId, documentId, format, true)
  }
}
