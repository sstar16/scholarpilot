<template>
  <div class="doc-skeleton">
    <div class="skeleton-header">
      <el-skeleton-item variant="text" style="width: 60px; height: 20px" />
      <el-skeleton-item variant="text" style="width: 80px; height: 20px" />
    </div>
    <el-skeleton-item variant="h3" style="width: 80%; margin: 8px 0" />
    <el-skeleton-item variant="text" style="width: 50%; margin-bottom: 12px" />
    <div class="skeleton-body">
      <el-skeleton :rows="3" animated />
    </div>
    <div class="skeleton-shimmer"></div>
  </div>
</template>

<style scoped>
.doc-skeleton {
  background: #fff; border-radius: 8px; border: 1px solid #e4e7ed;
  padding: 20px; margin-bottom: 12px; position: relative; overflow: hidden;
  animation: slideIn 0.4s ease-out;
}
.skeleton-header { display: flex; gap: 8px; margin-bottom: 8px; }
.skeleton-body { margin-top: 12px; }
.skeleton-shimmer {
  position: absolute; top: 0; left: -100%; width: 100%; height: 100%;
  background: linear-gradient(90deg, transparent, rgba(64,158,255,0.05), transparent);
  animation: shimmer 2s infinite;
}
@keyframes shimmer { 100% { left: 100%; } }
@keyframes slideIn {
  from { opacity: 0; transform: translateX(20px); }
  to { opacity: 1; transform: translateX(0); }
}
</style>
