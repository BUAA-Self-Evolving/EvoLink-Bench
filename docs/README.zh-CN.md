# EvoLink-Bench 发布说明

EvoLink-Bench 用于评测智能体在长程、相互依赖的任务流中的持续演化能力。

[GitHub 仓库](https://github.com/BUAA-Self-Evolving/EvoLink-Bench) · [英文说明](../README.md) · [数据访问](datasets.md) · [复现实验](reproduction.md) · [发布操作指南](publishing.md)

## 评测维度

| 维度 | 评测重点 |
| --- | --- |
| **L1：事实进化** | 在多轮任务中获取、保留、纠正并应用可用语言表达的知识、偏好和约束。 |
| **L2：任务级能力进化** | 在多轮任务中形成、复用和修订执行能力，包括产物生成、代码修改和实验工作流。 |

任务流按照顺序组织，并可以声明跨题依赖。后续任务可以在间隔若干轮后复用或修订早期任务产生的信息和产物。时间间隔与依赖结构属于任务流协议属性，不构成额外评测维度。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install 'pytest>=8.3,<9' 'jsonschema>=4.23,<5'
```

## 离线检查

```powershell
evolink-bench --spec examples\smoke.json --output runs\smoke
python -m pytest -q
python -m compileall -q evolink_bench baseline\adapters tools tests
```

上述 smoke 使用本地脚本组件，不调用模型服务。完整数据包、隐藏评分器和历史实验结果不包含在源代码仓库中，不能仅凭源代码安装复现实验成绩。

## 许可证与数据

项目自有代码采用 MIT License。第三方代码、数据、题目资产和上游声明继续适用各自条款。L1-Arena 兼容包源自 ClawArena 的 `clawarena-real` 数据集，固定提交为 `630efd8a0d1dc8189718226c7da158cbe4c2fe64`。分发派生数据前，请阅读 [THIRD_PARTY.md](../THIRD_PARTY.md) 和[数据说明](datasets.md)。
