# 为 MateriaViva 贡献

**简体中文** · [English](CONTRIBUTING.md)

感谢为 MateriaViva 提交代码、文档或数据来源信息。提交前请遵守以下边界。

## 开发流程

1. 从 `main` 创建短生命周期分支。
2. Python 代码保持兼容 Python 3.10+；前端使用 Node.js 20+。
3. 运行 `make test` 和 `make build`。
4. 提交中说明行为变化、验证命令以及是否影响数据模式。

## 数据边界

- 不要向 Git 提交 `data/`、`runtime/`、原始数据库、SQLite/blob 索引、渲染缓存、
  `.part`、receipt、API token 或许可证受限的数据。
- 新来源必须在 `scripts/datasets/sources.json` 登记官方 URL、访问模式、许可、目标路径、
  当前状态和 provenance 说明。
- MateriaViva 当前只接收独特的周期结构端点；分子动力学、弛豫过程、扰动和反应路径中间帧
  不应作为独立结构导入。
- 原始来源格式可以保留，但进入服务索引前必须转换为 `Crystal Record v1`，并保留来源
  ID、来源记录 ID、版本、单位和许可信息。
- 不要在完成统一结构指纹比较前删除疑似重复来源；去重必须保留所有性质和 provenance。

## 文档

- 一个量只在一个地方有一个值。计数属于测量它的那个东西——目录、manifest、`GET /api/stats`——
  而不属于需要手工跟着改的正文。
- `docs/` 下每份文档都有英文原件与 `.zh-CN.md` 译本，改动请同时改两边。
- 文档之间、或文档与代码之间仍然对不上的地方，记在
  [`docs/doc-conflicts.zh-CN.md`](docs/doc-conflicts.zh-CN.md)，而不是留着被重新发现。

## 验证

```bash
PYTHONPATH=backend:. python -m pytest backend/tests -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

数据模式或索引器变化还需运行 `make validate-data`，或在无法访问完整数据时使用最小的
合成 fixture 覆盖变化。完整数据发布到
[Hugging Face Dataset](https://huggingface.co/datasets/AI4QC/materia-viva)，不通过 Git PR 传输。

`make validate-data` 目前强制的是旧时代的行数，对着当前的池会失败；在把它当成回归之前，
请先看 [`docs/doc-conflicts.zh-CN.md`](docs/doc-conflicts.zh-CN.md)。
