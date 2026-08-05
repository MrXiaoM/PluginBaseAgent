# Paper 扩展规则

Paper API 只在用户明确选择 Paper，或需求已经证明没有可接受的 Spigot API 替代时使用。选择 Paper 后仍应保持调用面最小、版本锁定和线程语义可审查；不要为了便利把大量业务代码直接绑定到 Paper 类型。

## 允许进入 Paper 路径的条件

同时满足以下条件后才可引入 Paper 专有 API：

1. 已明确项目是 Paper-only，或功能被设计成可选增强并存在 Spigot 回退；
2. 指定了精确 Paper/Minecraft 版本与最低兼容版本；
3. 从该版本的源码/Javadoc 查询到实际类型、成员、文档标记和线程说明；
4. 构建脚本使用正确 `paper-api` 坐标及 Paper Maven 仓库；
5. 发布说明与 `plugin.yml` 的运行环境声明不误导 Spigot 用户；
6. 构建与目标 Paper 服务端启动验证已列入验收。

## 依赖泄漏防护

Paper 类型可在类加载阶段就使 Spigot 失败，而不需要实际执行功能。下列位置禁止无边界引用 Paper-only 类型，除非项目明确 Paper-only：

- 插件主类、基类、公共接口与公开 API；
- 自动注册模块的父类、字段、方法签名、泛型边界和注解参数；
- 静态字段、静态初始化块和枚举初始化；
- `plugin.yml` 指向的主类或 Bukkit 首次加载的监听类；
- Spigot 回退路径必须加载的配置模型、序列化对象和命令类。

若实现“Spigot 主路径 + Paper 可选增强”，将 Paper 代码放进窄适配层：

```text
<项目包>/
  compat/
    paper/
      PaperFeatureAdapter.java
  compat/
    FeatureAdapter.java
    SpigotFeatureAdapter.java
```

主路径只依赖 `FeatureAdapter` 等不含 Paper 类型的接口。适配器的创建条件、类存在性判断和回退行为必须由当前目标版本资料验证。不要用宽泛 `catch (Throwable)` 假装兼容；应记录实际不兼容的类、成员或版本。

## 线程与调度

Paper API 并不自动意味着可从异步线程调用，Folia 也不等同于普通 Paper。每个 Paper 调用都须查询：

- 方法/事件的线程限制；
- 是否涉及玩家、实体、区块或区域调度；
- 是否有异步回调及其结果应用上下文；
- 在目标最低 Paper 版本是否已经存在；
- 是否与 PluginBase `getScheduler()` 的兼容层重复或冲突。

若项目宣称 Folia 支持，参阅 `../pluginbase/concurrency-and-folia.md` 并在目标环境启动验证。

## 与 PluginBase `paper` 模块协作

PluginBase `paper` 模块的目标是为 `ItemEditor` 与 `InventoryFactory` 做运行时 Paper 优先、Bukkit 回退。它可以用于 Spigot/Paper 双端兼容项目，且不要求 `paper-api` 成为业务编译基线。

以下两者不可混淆：

- **使用 `PaperFactory`**：主类覆写工厂方法，业务通过 PluginBase 抽象操作；Spigot 仍是可支持目标。
- **直接调用 Paper API**：项目或适配层引用 Paper 专有类型；必须明确 Paper-only 或设计可验证的隔离回退。

即使项目使用 `PaperFactory`，也不得直接调用未被框架抽象的 Paper 专有方法。

## 版本升级

Paper API 中常见的风险包括新增/弃用方法、事件语义、组件和资料对象、异步行为与线程限制变化。升级前：

1. 同步新旧准确版本的 sources/Javadoc；
2. 对所有 Paper-only 导入和成员做存在性/签名比较；
3. 审查弃用、实验性和线程文档变化；
4. 重新构建并在目标 Paper 版本启动；
5. 若仍承诺 Spigot 回退，再在 Spigot 目标环境启动。

不得因 Paper API 的某一版本编译通过，推断整个支持范围不变。

## 交付说明

任何使用 Paper-only 能力的改动都应在交付说明中写明：

- Paper API 精确版本；
- 使用的类型/成员及其证据；
- 为什么 Spigot API 无法满足；
- 是否支持 Spigot；若支持，回退行为与测试结果；
- Folia/线程限制；
- 未验证的版本或运行环境。
