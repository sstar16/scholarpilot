"""
Local Knowledge Base — 本地科研文献知识库

三层架构:
  Layer 1: DuckDB 元数据 + SQLite FTS5 搜索索引
  Layer 2: SQLite 关系图（引用/共作者/主题）
  Layer 3: 语义重排 + 按需 API 补全
"""
