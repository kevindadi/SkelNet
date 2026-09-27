# SkelNet 重构规格（给执行者的完整任务书）

> 本文件是 SkelNet 重构的**唯一规格**。执行者按本文逐阶段实现；复核者按
> §10 的清单验收。凡本文未写明的取舍，选最简单、可测试、与现有 ConcIR 语义一致的方案，
> 并记录到 `docs/REFACTOR_REPORT.md` 的 "Deviations / Open questions" 一节。

---

## 0. 研究主张（一切设计服务于此）

LLM 直接写并发代码不可靠，事后静态分析也无法保证正确。SkelNet 在**生成前端**引入一个
形式化骨架（Skeleton DSL）：

1. 骨架**准确反映用户需求**：每条语句可用 `@R<n>` 标注对应需求编号，可追溯。
2. 骨架**让 LLM 看得懂**：Rust 风格、块结构、词法作用域的锁，而不是 CFG/JSON。
3. 骨架**可机械地、全函数地降低（lower）为 ConcIR**，再转 Petri 网做穷尽验证。
4. 验证反馈（诊断 + 反例交错）**映射回骨架的行号与语句**，指导 LLM 修正骨架。
5. 已验证的骨架指导 LLM 写 Rust（落地语言 Rust，内存安全交给编译器）。
6. 骨架遵循度检查是**人工复核工具**，不进入实验指标；插桩/运行时监控保留为兜底手段。

**不变量**：ConcIR 是唯一的语义来源。DSL 没有自己的语义，其含义 ≡ 降低后的 ConcIR 的含义。
DSL 是 ConcIR 的**封闭子集**的具体语法：子集外的构造在解析阶段就报错（S0xx），而不是等到
后端才报 UNSUPPORTED。

---

## 1. 硬性规则（违反任何一条即视为返工）

1. **只读来源仓库**：`/Users/kevin/local-repos/ConcPlanVerify`（HEAD `8bf9fa49b`）与
   `/Users/kevin/local-repos/ConcIR`（HEAD `a35dc86`）只读，不得修改、提交、打 tag。
2. **`.env` 绝不进入 git、绝不上传 GitHub**：
   - 第一个提交之前先写好 `.gitignore`（含 `.env`、`.env.*`、`!.env.example`）。
   - 然后 `cp /Users/kevin/local-repos/ConcPlanVerify/.env /Users/kevin/local-repos/SkelNet/.env`。
   - 验证：`git check-ignore -v .env` 必须命中；`git ls-files | grep -E '(^|/)\.env$'` 必须为空。
   - 新建 `.env.example`，只含键名（`DEEPSEEK_API_KEY=`、`OPENCODE_API_KEY=`、`CURSOR_API_KEY=`、`DASHSCOPE_API_KEY=`），不含任何值。
   - 任何时候不得在终端、日志、文档、测试快照中打印 `.env` 的值。
   - 每次提交前运行 `git diff --cached | grep -nE '(sk-|key-)[A-Za-z0-9_-]{16,}'`，必须无输出。
3. **不得 `git push`**，不得修改 remote。只在本地按阶段提交；推送由人工复核后进行。
4. **重构期间不得调用任何真实 LLM API**。所有涉及模型的测试使用 fake provider / 录制的 fixture。
5. **不新增网络依赖**。Rust 只允许现有依赖（serde、serde_json、syn、proc-macro2、insta），
   必须能 `cargo build --offline`。解析器**手写**（lexer + 递归下降），不引入 pest/lalrpop/chumsky 等。
   Python 依赖不超出现有 `python/requirements.txt`（openai、cursor-sdk）+ 标准库。
6. **不得为了通过测试而修改 gold / contract / baseline**。若某 gold 无法用 DSL 表达，按 §6.3 处理并上报。
7. **不迁移历史实验结果**（experiments/、notes、paper 草稿、legacy benchmarks、real-cases 均不带）。
   历史保留在原仓库，`docs/MIGRATION.md` 记录来源 commit SHA 以便追溯。
8. 每个阶段（§9）结束：所有测试通过 → 本地提交 → 在 `docs/REFACTOR_REPORT.md` 追加该阶段记录
   （做了什么、测试命令与结果摘要、偏差）。某阶段验收不过时**停下并报告**，不要削弱测试继续往下做。

---

## 2. 目标目录结构

```
SkelNet/
├── Cargo.toml                 # [workspace] members = crates/*, runtime/concir_sync
├── rust-toolchain.toml        # 沿用 ConcIR：nightly-2026-09-04 + miri + rust-src
├── .gitignore  .env(忽略)  .env.example  README.md
├── crates/
│   ├── concir/                # 来自 ConcIR，裁剪后（§3）；lib + bins: concir-backend, concir-instrument, bind_check
│   └── skel/                  # 新建：DSL 前端（§4–§5）；lib + bin: skelnet
├── runtime/concir_sync/       # 来自 ConcPlanVerify，补 post/take（§3.3）
├── python/
│   ├── skelnet/               # 编排（§7）
│   ├── tests/
│   └── requirements.txt
├── prompts/                   # §7.3
├── benchmarks/
│   ├── tasks/<family>/<task>/ # §6
│   ├── BASELINE.json          # §6.2，由附录 A 固化
│   └── MANIFEST.json
├── experiments/               # 只放 README.md 与 .gitkeep；运行产物默认被 .gitignore 忽略原始层
└── docs/
    ├── REFACTOR_PLAN.md (本文)  REFACTOR_REPORT.md  MIGRATION.md
    ├── dsl.md                 # DSL 参考手册（给人和给 LLM 的都从这里派生）
    ├── lowering.md            # 降低规则表 + source map 格式
    ├── feedback.md            # 诊断/反例回映射与披露策略
    ├── architecture.md  experiments.md  error_codes.md
    └── concir/                # ConcIR 原 doc/ 迁移（backend-design、ebnf、syntax/*、error_codes）
```

---

## 3. ConcIR 迁移与裁剪（`crates/concir`）

### 3.1 保留

`ast, expr, env, fqn, hash, schema, typedef, diagnostic, codegen, conform, instrument, monitor,
validate/*, sem/*, interp/*, petri/*, explore/*, export/dot`。
CLI 子命令保留：`schema, check, support, run, explore, codegen, conform, monitor`；
bins 保留 `concir-instrument`（去掉依赖 src_mutate 的变异模式）、`bind_check`。

### 3.2 删除（非核心：修复实验线）

`repair/*`, `src_mutate.rs`，子命令 `repair, replay, repair-context, evaluate-patch, bench`。
测试：删除只覆盖上述模块的测试（`repair_e2e, repair_search, src_mutate, benchmark` 等）；
混合型回归测试（`round*_regressions.rs` 等）保留语义用例、删除修复相关用例。
`docs/MIGRATION.md` 必须逐项列出删除的文件、子命令和测试。

**验收**：`cargo test -p concir --offline` 全绿；裁剪后 `concir-backend explore` 对附录 A 的每个
gold 输出与基线一致（outcome 与逐属性 outcome 完全相同）。

### 3.3 runtime/concir_sync

保留现有 `Semaphore/Permit`（RAII）API。为 DSL 的计数信号用法新增：

- `Semaphore::post(&self)`：增加一个许可（事件记为 `semaphore_release`）；
- `Semaphore::take(&self)`：阻塞获取一个许可且不归还（等价于 `acquire().forget()`；事件记为 `semaphore_acquire`）。
  同步更新 `concir-instrument` 的 wrapper 映射与测试。**不要**恢复旧的 `Semaphore::release`。

---

## 4. Skeleton DSL（`crates/skel`）

### 4.1 设计要点

- Rust 风格、块结构。**锁是词法作用域的**：`lock m { ... }` ≡ Rust `{ let _g = m.lock().unwrap(); ... }`。
  不存在 `unlock` 语句；离开块（含 `return/break/continue` 提前退出）即按逆序释放。
- **condvar 在声明时绑定唯一 mutex**（`condvar cv for m;`），与 Rust `Condvar` 一致；
  `cv.wait()` 只能出现在 `lock m { }` 内（m 为其绑定的锁），否则 S104。
- 信号量：首选 RAII 作用域 `permit s { }`；计数信号用法用 `s.post();`（V）/`s.take();`（P）。
- 值操作一律用方法调用（LLM 熟悉的 Rust 写法）：`ch.send(e)`, `ch.recv()`, `c.load()`,
  `c.store(e)`, `c.cas(expected, desired)`, `cv.notify_one()`, `cv.notify_all()`, `h.join()`。
- 顺序计算用 `compute "描述"` 洞表示（→ ConcIR `seq_hole`），它是 Rust 阶段由 LLM 填写的地方。
- 需求追溯：`@R3` 以**前缀属性**形式附在 item 或语句前，可多个：`@R3 @R4 lock m { ... }`。
- 表达式语法**严格等于** ConcIR 的表达式语法（无 `&&`、`||`、`!`）：条件只能是单个比较或布尔原子；
  需要复合条件时用嵌套 `if`。这是有意的：不给 DSL 发明 ConcIR 没有的语义。
- 单模块简写：不写 `module` 时，所有 item 属于模块 `main`；入口固定为 `main::main`。
- provides/requires **由降低自动计算**，DSL 中不写（消除一整类接口表示错误）。

### 4.2 词法

- 标识符 `[A-Za-z_][A-Za-z0-9_]*`；整数（可带负号，负号属于表达式一元运算）；字符串 `"..."`（支持 `\"` `\\` `\n`）。
- 注释 `// ...` 到行尾。空白不敏感。
- 关键字：`skeleton module mutex condvar for semaphore channel cap shared guarded_by atomic
fn extern let lock permit scope spawn if else while loop break continue return compute reads writes
true false Bool Int`。
- **子集外保留字**（出现即 S002，并给出 hint）：`rwlock RwLock read_lock write_lock async await select
unlock release acquire drop unsafe Arc Float String struct enum match thread`。

### 4.3 文法（EBNF，权威版本；`docs/dsl.md` 必须与此一致）

```ebnf
File        = "skeleton", Ident, ";", ( { Item } | ModuleDecl, { ModuleDecl } ) ;
ModuleDecl  = "module", Ident, "{", { Item }, "}" ;
Item        = { Tag }, ( ResourceDecl | FnDecl | ExternFn ) ;
Tag         = "@", Ident ;                       (* 如 @R3；Ident 须匹配 R[0-9]+ ，否则 S109 *)

ResourceDecl
  = "mutex", Ident, ";"
  | "condvar", Ident, "for", Name, ";"
  | "semaphore", Ident, "=", IntLit, ";"                     (* 初始许可数 ≥ 0 *)
  | "channel", Ident, ":", Type, "cap", IntLit, ";"          (* cap 0 = rendezvous *)
  | "shared", Ident, ":", Type, "=", Literal, [ "guarded_by", Name ], ";"
  | "atomic", Ident, ":", Type, "=", Literal, ";" ;

Type        = "Bool" | "Int" | "Int", "[", IntLit, "..=", IntLit, "]" ;

FnDecl      = "fn", Ident, "(", [ Param, { ",", Param } ], ")", [ "->", Type ], Block ;
ExternFn    = "extern", "fn", Ident, "(", ")", ";" ;         (* 不透明函数：空 body *)
Param       = Ident, ":", Type ;

Block       = "{", { Stmt }, "}" ;
Stmt        = { Tag }, StmtCore ;
StmtCore
  = "lock", Name, Block
  | "permit", Name, Block
  | "scope", "{", { "spawn", Name, "(", ")", ";" }, "}"
  | "if", Expr, Block, [ "else", ( Block | IfStmt ) ]
  | "while", Expr, Block
  | "loop", Block
  | "break", ";" | "continue", ";"
  | "return", [ Expr ], ";"
  | "compute", StringLit, [ "reads", "(", NameList, ")" ], [ "writes", "(", NameList, ")" ], ";"
  | "let", Ident, [ ":", Type ], "=", Rhs, ";"
  | Name, "=", Expr, ";"                                     (* 局部变量或 shared 变量赋值 *)
  | Name, ".", Method, ";"                                   (* 无返回值的方法语句 *)
  | Call, ";" ;
IfStmt      = "if", Expr, Block, [ "else", ( Block | IfStmt ) ] ;

Rhs         = Expr
            | Name, ".", "recv", "(", ")"
            | Name, ".", "load", "(", ")"
            | Name, ".", "cas", "(", Expr, ",", Expr, ")"
            | "spawn", Call
            | Call ;
Method      = "send", "(", Expr, ")" | "recv", "(", ")" | "store", "(", Expr, ")"
            | "notify_one", "(", ")" | "notify_all", "(", ")" | "wait", "(", ")"
            | "post", "(", ")" | "take", "(", ")" | "join", "(", ")" ;
Call        = Name, "(", [ Expr, { ",", Expr } ], ")" ;
Name        = Ident, [ "::", Ident ] ;
NameList    = Name, { ",", Name } ;

(* 表达式 = ConcIR 表达式子集（docs/concir/ebnf.md 的 Expr，去掉 Struct 相关） *)
Expr        = AddExpr, [ CmpOp, AddExpr ] ;
CmpOp       = "==" | "!=" | "<" | "<=" | ">" | ">=" ;
AddExpr     = MulExpr, { ( "+" | "-" ), MulExpr } ;
MulExpr     = Unary, { ( "*" | "/" | "%" ), Unary } ;
Unary       = [ "-" ], Atom ;
Atom        = IntLit | "true" | "false" | Name | "(", Expr, ")" ;
```

### 4.4 解析器与报错要求

- 手写 lexer + 递归下降，所有 token/AST 节点带 `Span { file, start, end, line, col, end_line, end_col }`。
- 错误恢复：在 `;` 与 `}` 处同步，单次最多报告 20 条错误。
- 错误格式（人读，rustc 风格，同时用于喂给 LLM）：
  ```
  error[S104]: `cv.wait()` must be inside `lock m { ... }` (cv is bound to m)
    --> task.skel:14:9
     |
  14 |         cv.wait();
     |         ^^^^^^^^^
     = hint: wrap the wait loop in `lock m { while ready == false { cv.wait(); } }`
  ```
- `--json` 输出：`{"code","severity","message","span","hint","origin":"skel"|"concir","concir_code"?}`。
- 必须提供 `skelnet fmt`（规范化打印器）；对所有 gold：`parse(fmt(parse(x))) == parse(x)`（AST 忽略 span 比较）。

### 4.5 前端静态检查（S 码；ConcIR 能查的不要重复实现）

| 码             | 含义                                                                                       |
| -------------- | ------------------------------------------------------------------------------------------ |
| S001           | 词法错误                                                                                   |
| S002           | 子集外构造（带 hint，如 "rwlock 不在子集内，用 mutex"、"没有 unlock：离开 lock 块即释放"） |
| S003           | 语法错误（期望的 token 集合）                                                              |
| S101           | 未定义名字                                                                                 |
| S102           | 重复定义                                                                                   |
| S103           | 资源种类与操作不匹配（如 `lock s` 而 s 是 semaphore；`c.load()` 而 c 不是 atomic）         |
| S104           | `cv.wait()` 不在其绑定 mutex 的 `lock` 块内                                                |
| S105           | `break/continue` 在循环外                                                                  |
| S106           | `scope` 内 spawn 带参数或目标不是 fn                                                       |
| S107           | 对非 spawn 句柄调用 `.join()`                                                              |
| S108           | 字面量与声明类型不符 / 有界 Int 初值越界                                                   |
| S109           | 非法 tag（不是 `R<n>`）                                                                    |
| S201 (warning) | 给定 `--reqs requirements.json` 时，某需求编号在骨架中没有任何 `@R` 标注                   |
| S202 (warning) | `@R<n>` 引用了不存在的需求编号                                                             |

受保护变量无锁访问（E309）、未 join（E401）、无限循环（E605）等**留给 ConcIR 验证器**，通过回映射呈现。

---

## 5. 降低（lowering）到 ConcIR 与 source map

### 5.1 总则

- 降低是**全函数**：任何通过 §4.5 的骨架都必须产出 ConcIR JSON（`version` 与现有 gold 一致，`"3.5.0"`），
  不得 panic。降低器不做任何优化。
- 每个函数的 sid 按发射顺序稠密编号 `s1..sn`；跳转目标用回填（backpatch）。
- **不发射死语句**：函数末尾仅当可达时追加隐式 `return`（例如 `loop {}` 无 `break` 时不追加）。
- 资源字段一律写 FQN（`main::m`）。表达式中：本模块资源与局部变量写裸名，跨模块资源写 FQN。
- provides = 本模块全部资源与函数；requires = 本模块引用到的其他模块资源/函数（排序去重）。
- 所有资源 `mode: "Sync"`。
- 被 `scope`/`spawn` 作为目标的函数设 `form: "closure"`，其余不设。

### 5.2 映射表

| DSL                                     | ConcIR                                                                                                     |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `mutex m;`                              | `{"name":"m","kind":"sync","type":"Mutex","mode":"Sync"}`                                                  |
| `condvar cv for m;`                     | `{"kind":"sync","type":"Condvar","mode":"Sync"}`；绑定信息只存在 source map 与前端检查中                   |
| `semaphore s = 2;`                      | `{"type":"Semaphore","count":2,...}`                                                                       |
| `channel ch: Int cap 0;`                | `{"type":"Channel","base":"Int","capacity":0,...}`                                                         |
| `shared x: Bool = false guarded_by m;`  | var 资源 `{"kind":"var","type":"Var","base":"Bool","init":false}` + `protection: [{"var":"x","lock":"m"}]` |
| `atomic c: Int[0..=2] = 0;`             | `{"kind":"var","type":"Atomic","base":{"Int":[0,2]},"init":0}`                                             |
| `lock m { B }`                          | `mutex_lock m`; B; `mutex_unlock m`                                                                        |
| `permit s { B }`                        | `semaphore_acquire s`; B; `semaphore_release s`                                                            |
| `s.take();` / `s.post();`               | `semaphore_acquire s` / `semaphore_release s`                                                              |
| `cv.wait();`（在 `lock m` 内）          | `condvar_wait {condvar: cv, lock: m}`                                                                      |
| `cv.notify_one();` / `cv.notify_all();` | `condvar_notify` / `condvar_notify_all`                                                                    |
| `ch.send(e);`                           | `channel_send {value: e}`                                                                                  |
| `let v = ch.recv();` / `ch.recv();`     | `channel_recv {dst: "v"}` / `{dst: "_"}`                                                                   |
| `let v = c.load();`                     | `atomic_load {dst: v}`                                                                                     |
| `c.store(e);`                           | `atomic_store {value: e}`                                                                                  |
| `let r = c.cas(e1, e2);`                | `atomic_cas {expected: e1, desired: e2, dst: r}`（r 为旧值，语义同 ConcIR）                                |
| `x = e;`（x 为 shared）                 | `write_shared {resource: x, expr: e}`                                                                      |
| `x = e;` / `let x = e;`（x 为局部）     | `assign_local`                                                                                             |
| `let v = x;`（x 为 shared）             | `read_shared {dst: v}`                                                                                     |
| `f(a);` / `let r = f(a);`               | `call {func, args, dst?}`                                                                                  |
| `let h = spawn f(a);` / `h.join();`     | `spawn {func, args, handle: h}` / `join {handle: h}`                                                       |
| `scope { spawn f(); spawn g(); }`       | `scope {funcs: [f, g]}`                                                                                    |
| `if c {A} else {B}`                     | `branch c then→A首 else→B首`；A 末 `goto` 汇合点                                                           |
| `while c {B}`                           | 头：`branch c then→B首 else→出口`；B；`goto 头`                                                            |
| `loop {B}`                              | B；`goto B首`                                                                                              |
| `break;` / `continue;`                  | `goto 出口` / `goto 头`                                                                                    |
| `return e;`                             | `return {value: e}`                                                                                        |
| `compute "d" reads(..) writes(..);`     | `seq_hole {id: "h<k>", desc: "d", reads, writes}`（k 为全程序递增）                                        |
| `extern fn f();`                        | 函数 `f`，body 为空                                                                                        |

局部变量：每个 `let` 产生一个 `locals` 条目，`modeled: true`；类型取显式注解，否则由右值推断
（`load/cas` 取 atomic 的基类型，有界 Int 推断为 `Int`；`recv` 取 channel 的 base；表达式按字面量/变量推断）。
推断失败 → S108。`let _ = ...` 不产生局部。

### 5.3 提前退出与释放顺序（必须有专门测试）

`return/break/continue` 跨越若干 `lock`/`permit` 块时，降低器在跳转**之前**按由内到外的顺序
发射对应的 `mutex_unlock` / `semaphore_release`，每条都在 source map 中标注
`construct: "implicit_release_on_exit"` 并指向触发它的 `return/break/continue` 与所属 `lock` 块。

### 5.4 Source map（`*.map.json`）

```json
{
  "skel_sha256": "...", "cir_sha256": "...", "file": "task.skel",
  "stmts": [
    {"loc": "main::waiter::s3", "construct": "condvar_wait",
     "span": {"line":12,"col":9,"end_line":12,"end_col":19},
     "block_span": null, "reqs": ["R4","R6"]},
    {"loc": "main::waiter::s5", "construct": "lock_exit",
     "span": {...lock 块的右花括号...}, "block_span": {...整个 lock 块...}, "reqs": ["R4"]}
  ],
  "functions": {"main::waiter": {"span": {...}, "reqs": []}},
  "resources": {"main::m": {"span": {...}}, "main::cv": {"span": {...}, "bound_mutex": "main::m"}},
  "json_paths": {"modules[0].functions[1].body[2]": "main::waiter::s3", "modules[0].resources[0]": "main::m"}
}
```

`construct` 取值：`lock_enter, lock_exit, permit_enter, permit_exit, implicit_release_on_exit,
branch_if, branch_while, loop_back, break, continue, implicit_return, return` 以及 §5.2 中各操作名。
标签 `reqs` 取语句自身 tag ∪ 所有外层块 tag ∪ 函数 tag。

### 5.5 反馈回映射（`skelnet check` / `skelnet verify`）

- ConcIR 诊断中的 `path`（JSON 路径）、`location`/`module::function::sid`、`cir_statements`、
  `blocked`、`doom_state.threads[].at_sid`、`counterexample_names` 全部经 source map 翻译为 DSL 位置。
  翻译不到的保留原文并标记 `unmapped: true`（测试中应为 0）。
- 反例渲染为交错表，每步一行：
  ```
  counterexample (property no-deadlock, requirements R6 R7):
    step thread fn       line  statement                  holds after
    1    T1     t1       5     lock a {                   [a]
    2    T2     t2       9     lock b {                   [b]
    3    T1     t1       6     lock b {   -- blocked      [a]
    4    T2     t2       10    lock a {   -- blocked      [b]
  final: T1 waits b (held by T2); T2 waits a (held by T1)
  ```
- **披露策略**沿用现有 `build_explore_feedback`：可给属性 id、outcome、detail、反例、阻塞/持有状态、
  `complete`、以及属性的 `req` 编号（让 LLM 对上 `@R` 标注）；**绝不**给出 contract 的 goal 公式或
  完整 contract 文件。`docs/feedback.md` 写明并给出一个完整示例。

### 5.6 `skelnet` CLI

| 命令                                                            | 作用                                                                                   |
| --------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `skelnet parse f.skel [--json]`                                 | 输出 AST（调试）                                                                       |
| `skelnet fmt f.skel [--check]`                                  | 规范化打印                                                                             |
| `skelnet lower f.skel -o f.cir.json --map f.map.json`           | 降低                                                                                   |
| `skelnet check f.skel [--reqs requirements.json] [--json]`      | 解析+前端检查+降低+ConcIR check/support，诊断回映射                                    |
| `skelnet verify f.skel contract.json [--engine petri] [--json]` | check + explore，反例回映射                                                            |
| `skelnet codegen f.skel`                                        | 调 ConcIR codegen 生成确定性 Rust 骨架，在每处注释 `// skel:L<line> @R..`（消融/兜底） |
| `skelnet adhere f.skel main.rs [--json]`                        | 骨架遵循度报告，**仅供人工复核**（§8）                                                 |

`skel` crate 以库方式依赖 `concir`（进程内调用 validate/explore），不要 shell out。
退出码：0 = 通过；1 = 诊断错误/验证失败；2 = 用法/IO 错误。`--json` 的输出 schema 写入 `docs/feedback.md`。

---

## 6. 基准迁移（`benchmarks/tasks`）

### 6.1 内容

24 个生成任务 + 3 个 boundary 任务，按原 family 目录组织。每个任务目录只带：
`requirements.json`（来自 `generation_input/`，连同 `REQUIREMENTS.md`）、`contract.json`（冻结、生成期隐藏）、
`gold.cir.json`（fixed 或 correct）、`gold.skel`（新写）、`spec.md`、`ground_truth.json`、`rust/fixed.rs`（若有）。
不带：`buggy.cir.json`、`repair_input/`、`repair_task.json`、`rust/buggy.rs`。
`benchmarks/MANIFEST.json` 由脚本生成，含每个文件的 sha256 与来源路径。

### 6.2 基线

附录 A 是在 ConcIR `a35dc86` 上对每个 gold 跑 `explore gold contract petri` 的结果，
固化为 `benchmarks/BASELINE.json`（不得修改）。

### 6.3 gold.skel 的等价性（本阶段的核心验收）

对每个任务：`skelnet lower gold.skel` → `concir explore` → **总 outcome 与逐属性 outcome
必须与 BASELINE 完全相同**（`states_explored` 可以不同，因为循环的降低形状可能不同）。
预计需要注意的点：

- `atomic_lost_update`：CAS 重试写成 `loop { let l = c.load(); let r = c.cas(l, l + 1); if r == l { break; } }`。
- `bare_wait_no_predicate` / `lost_wakeup_notify_before_wait`：`lock m { while ready == false { cv.wait(); } }`。
- `notify_one_multi_waiter_wrong_pick`：使用 `s.post()` / `s.take()`。
- `partial_deadlock_bystander`（忙等）、`finite_call_loop`、`spawn_join_loop_finite`：`loop`/`while`，注意不发射死语句。
- `cross_module_cycle`：两个 `module` 块。
- `worker_with_payload`：`extern fn compute();`。
- **`condvar/same_cv_different_locks`**：原 gold 让一个 condvar 配两把锁（基线 UNSUPPORTED），
  DSL 中写不出（S104/绑定规则）。处理：①在 `tests/` 中加一个用例，确认对原结构的直译得到 S104；
  ②另写一个满足需求文本的子集内 `gold.skel`（例如每个 waiter 各用一个 condvar），
  记录其 explore 结果，标记为 `baseline_deviation`，**在 REFACTOR_REPORT 中单独列出等待人工确认**。
- boundary：`rwlock_unsupported`、`async_select_unsupported` 不写 gold.skel，改为测试
  "用 DSL 表达这些构造得到 S002"；`unbounded_int_unknown` 写 gold.skel，期望 UNKNOWN。

任何其他任务若无法等价表达：**停下并上报**，不要改 contract 或 baseline。

---

## 7. Python 编排（`python/skelnet`）

### 7.1 模块映射（只带核心）

| 新模块                                                                       | 来源（ConcPlanVerify/python/cir_workflow）                                                            | 说明                                                                     |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `env.py, models.py, json_utils.py`                                           | 同名                                                                                                  | 原样迁移                                                                 |
| `llm.py, transport.py, providers.py, channels.py, opencode_go.py, direct.py` | 同名                                                                                                  | 模型接入层，原样迁移并修 import                                          |
| `backend.py`                                                                 | `concir_client.py`                                                                                    | 保留调用归档/哈希；新增 skelnet 子命令封装                               |
| `prompts.py`                                                                 | `prompts.py`                                                                                          | 保留 `build_explore_feedback` 的披露策略，改为输出 DSL 回映射后的文本    |
| `pipeline.py`                                                                | `generation.py` + `revision_workflow.py`                                                              | 三个 arm（§7.2），单一修订循环实现                                       |
| `oracle.py`                                                                  | `rust_oracle.py, rust_arm.py, project_template.py, instrument.py, conformance.py, bounded_monitor.py` | **外部评测器**：对所有 arm 的 Rust 同一套 build/run/monitor/功能输出检查 |
| `evidence.py`                                                                | `evidence_v2.py, candidate_eval.py, binding.py`                                                       | 逐属性证据账本                                                           |
| `audit.py`                                                                   | `audit.py`                                                                                            | 产物哈希与审计                                                           |
| `cli.py` + `__main__.py`                                                     | 重写                                                                                                  | 见 §7.4                                                                  |

不迁移：`arms, experiments_v2, results, gen_results, flash_smoke, normalize, extract, patch_repair,
offline_workflow, mutation_protocol, detection, structural, contract_strength, scale, live, cursor_harness`
以及全部 `scripts/`。若迁移模块依赖其中某函数，把**最小必要部分**内联并在 MIGRATION.md 记录。

### 7.2 实验 arm（只保留三个）

- `G0`：需求 → LLM 直接写 Rust（基线）。
- `SKEL`（主方法）：需求 → LLM 写 `.skel` → `skelnet check/verify`（contract 隐藏）→ 回映射反馈 → 修订（≤ N 轮）
  → 接受的骨架 + 需求 → LLM 写 Rust。
- `CIR`（消融）：同 SKEL，但 LLM 直接写 ConcIR JSON（沿用 `concir_generation_v4` + `rust_from_cir_v2`）。
- 可选开关 `--rust-mode codegen`：Rust 阶段改用 `skelnet codegen` 的确定性骨架 + LLM 填 `compute` 洞（兜底/消融）。

所有 arm 的最终 Rust 都用 `oracle.py` 同一个评测器打分；骨架/CIR 自身的验证证据单独记录，不混入代码分数。
G1/G2 本次不迁移（在 `docs/experiments.md` 注明可按需恢复）。

### 7.3 Prompts

- `prompts/skel_generation_v1.md`：从 `docs/dsl.md` 派生的 DSL 参考 + 2 个**不在基准中**的完整示例
  （一个锁序、一个 condvar 谓词循环）+ 输出格式（只输出一个 ```skel 代码块）+ `@R` 标注要求。
- `prompts/skel_feedback_v1.md`：回映射诊断/反例的呈现模板。
- `prompts/rust_from_skel_v1.md`：必须使用骨架中的资源名与函数名作为 Rust 标识符；
  `lock m {}` → guard 作用域；`permit` → `Permit`；`post/take` → `concir_sync`；std-only + `concir_sync`；
  `compute` 处写顺序逻辑；保留 `// @R3` 注释。
- 迁移（消融/基线用，内容不改）：`concir_generation_v4.md`、`rust_from_cir_v2.md`、`rust_generation_v1.md`，
  以及它们引用的 `prompts/examples/*`。
- 每个 prompt 的 sha256 写入运行 MANIFEST。

### 7.4 运行入口（解决"实验轮次太多"的问题）

```
python -m skelnet run    --arm SKEL --model <name> --tasks all|<glob> --reps 3 --rounds 4 --out experiments/<run_id>
python -m skelnet eval   experiments/<run_id>          # 外部评测器，离线可重跑
python -m skelnet report experiments/<run_id> [...]    # 一张总表
```

- 一次运行 = 一个目录：`MANIFEST.json`（git sha、二进制 sha、prompt sha、模型、参数、seed）、
  `cells/<task>/<rep>/...`（所有调用归档）、`SUMMARY.json`、`REPORT.md`。
- `report` 固定输出一张表：arm × model 的 骨架/CIR 首轮可解析率、check 通过率、verify PASS 率、平均修订轮数、
  Rust 构建率、功能正确率（RF）、证据充分率；并支持多个 run 目录对比。
- `--dry-run` 只统计请求预算，不调用模型（沿用 pilot 的 dry-run 思路）。

### 7.5 Python 测试

迁移仍然适用的测试（llm/transport/env/json_utils/backend/oracle/evidence/audit 相关），修 import；
新增：`test_pipeline_skel.py`（fake provider：第一轮返回有 ABBA 死锁的骨架 → 收到回映射反馈 → 第二轮修正 → 接受 → 生成 Rust → oracle 通过）、
`test_pipeline_cir.py`、`test_pipeline_g0.py`、`test_feedback_disclosure.py`（反馈中不得出现 contract goal）、
`test_env_not_tracked.py`（断言 `.env` 被 git 忽略且未被跟踪）。

---

## 8. 骨架遵循度检查（`skelnet adhere`，人工复核工具）

- 用 `syn` 解析 Rust；按函数提取同步操作序列及嵌套结构（guard 作用域、`wait`、`notify_*`、`send/recv`、
  原子操作、`scope/spawn/join`、`Permit`/`post`/`take`）。名字按 `rust_from_skel` 约定直接对应（同名）。
- 与骨架逐函数对齐，报告每个骨架语句：`matched / missing / extra / reordered / nesting_mismatch`，
  同时给 DSL 行号与 Rust 行号；输出 Markdown（人读）与 `--json`。
- 可复用 `bind_check` 的名字绑定逻辑。
- **不接入** `run/eval/report` 的任何指标。实验侧如需兜底，用 `oracle.py` 已有的插桩 + monitor。
- 测试：对每个有 `rust/fixed.rs` 的任务运行 adhere 生成快照（insta），人工抽查。

---

## 9. 阶段与提交（每阶段一个或多个本地提交）

| 阶段 | 内容                                                                                                                  | 验收                                                                       |
| ---- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| P0   | 工作区骨架、`.gitignore`、`.env` 复制与验证、`.env.example`、`docs/MIGRATION.md` 初稿（来源 SHA）                     | §1.2 的全部检查命令输出贴进 REPORT                                         |
| P1   | 迁移并裁剪 ConcIR → `crates/concir`；runtime → `runtime/concir_sync`（含 post/take）                                  | `cargo test --workspace --offline` 全绿；附录 A 基线复现                   |
| P2   | `crates/skel`：lexer/parser/AST/fmt/前端检查 + 错误渲染                                                               | 每个 S 码至少 1 个正例与 1 个反例测试；fmt 往返测试                        |
| P3   | 降低 + source map + check/verify 回映射 + 反例渲染                                                                    | 降低单测（每行映射表至少 1 例）；§5.3 提前退出测试；回映射 `unmapped == 0` |
| P4   | 基准迁移 + 全部 gold.skel + 等价性测试                                                                                | §6.3 全部通过（或按规则上报）                                              |
| P5   | Python 包 + prompts + fake-LLM 测试                                                                                   | `python -m pytest python/tests` 全绿；`run --dry-run` 可跑                 |
| P6   | `skelnet codegen` 注释 + `skelnet adhere`                                                                             | 快照测试                                                                   |
| P7   | 文档：README、dsl.md、lowering.md、feedback.md、architecture.md、experiments.md、error_codes.md；REFACTOR_REPORT 汇总 | 复核清单 §10 自检一遍                                                      |

---

## 10. 复核清单（复核者逐项检查）

1. `git log --stat` 中无 `.env`；`git check-ignore -v .env` 命中；全仓库无密钥样式字符串；无 push。
2. 原仓库 `git status` 仍干净，HEAD 未变。
3. `cargo build --workspace --offline` 与 `cargo test --workspace --offline` 全绿；无新增依赖（对比 Cargo.lock）。
4. 解析器为手写；EBNF（本文 §4.3）与 `docs/dsl.md`、实现一致；子集外关键字给出 S002 + hint。
5. 降低是全函数（fuzz/随机合法骨架不 panic 的简单性质测试）；无死语句；提前退出释放顺序正确。
6. 24+3 任务的等价性表与 BASELINE 完全一致；偏差项单列。
7. 反馈回映射：反例每一步都有 DSL 行号；反馈文本中没有 contract goal。
8. Python：三个 arm 共用同一评测器；fake-LLM 端到端测试覆盖"失败→反馈→修正→接受"。
9. `adhere` 未被 run/eval/report 引用（`grep` 验证）。
10. MIGRATION.md 列全了带入/删除的文件、子命令、测试及原因。

---

## 附录 A：基线（ConcIR `a35dc86`，`explore <gold> contract.json petri`）

| task                                       | gold    | outcome     | complete | 逐属性                                                                        |
| ------------------------------------------ | ------- | ----------- | -------- | ----------------------------------------------------------------------------- |
| atomic-data/atomic_lost_update             | fixed   | PASS        | true     | no-deadlock, both-increments, P:w1 completes, P:w2 completes, P:c == 2 = PASS |
| atomic-data/bounded_counter_invariant      | correct | PASS        | true     | no-deadlock, counter-bound, P:w1/w2 completes = PASS                          |
| atomic-data/counter_overflow_safety        | fixed   | PASS        | true     | no-deadlock, counter-bound, P:w1/w2 completes = PASS                          |
| boundary/async_select_unsupported          | buggy   | UNSUPPORTED | false    | —                                                                             |
| boundary/rwlock_unsupported                | buggy   | UNSUPPORTED | false    | —                                                                             |
| boundary/unbounded_int_unknown             | correct | UNKNOWN     | false    | no-deadlock = UNKNOWN                                                         |
| channel/bounded_backpressure_lock_held     | fixed   | PASS        | true     | no-deadlock, P:sender/receiver completes = PASS                               |
| channel/rendezvous_both_send               | fixed   | PASS        | true     | no-deadlock, P:s1 completes, P:the channel is drained = PASS                  |
| channel/send_while_holding_mutex           | fixed   | PASS        | true     | no-deadlock = PASS                                                            |
| condvar/bare_wait_no_predicate             | fixed   | PASS        | true     | no-deadlock, ready-set, P:waiter/notifier completes, P:ready == True = PASS   |
| condvar/lost_wakeup_notify_before_wait     | fixed   | PASS        | true     | 同上 = PASS                                                                   |
| condvar/notify_one_multi_waiter_wrong_pick | fixed   | PASS        | true     | deadlock, P:w1 holds [m] at once = PASS                                       |
| condvar/same_cv_different_locks            | correct | UNSUPPORTED | false    | —（condvar_multiple_locks；见 §6.3）                                          |
| lock-order/abba_2lock                      | fixed   | PASS        | true     | no-deadlock, P:t1/t2 completes, P:t1/t2 holds [a,b] at once = PASS            |
| lock-order/cross_module_cycle              | fixed   | PASS        | true     | no-deadlock, P:main::t1/other::t2 completes, holds [a,b] ×2 = PASS            |
| lock-order/cycle_3lock                     | fixed   | PASS        | true     | no-deadlock, P:t1/t2/t3 completes, holds ×3 = PASS                            |
| lock-order/partial_deadlock_bystander      | fixed   | PASS        | true     | no-deadlock, a-completes, b-completes, P:a/b completes, holds ×2 = PASS       |
| lock-order/two_independent_cycles          | fixed   | PASS        | true     | no-deadlock, P:t1–t4 completes, holds ×4 = PASS                               |
| semaphore/acquire_twice_no_release         | fixed   | PASS        | true     | no-deadlock, P:w1/w2 completes, P:w1 holds [s] = PASS                         |
| semaphore/permit_leak                      | fixed   | PASS        | true     | no-deadlock, P:w1/w2 completes, P:w1 holds [s] = PASS                         |
| semaphore/throttle_n_permits               | correct | PASS        | true     | no-deadlock, P:w1/w2/w3 completes = PASS                                      |
| structure/finite_call_loop                 | correct | PASS        | true     | deadlock = PASS                                                               |
| structure/nested_scope_lock_order          | fixed   | PASS        | true     | no-deadlock, P:outer completes, P:x1/x2 holds [a,b] = PASS                    |
| structure/scope_bound_k_workers            | correct | PASS        | true     | no-deadlock, P:w1/w2/w3 completes = PASS                                      |
| structure/scope_worker_abba                | fixed   | PASS        | true     | no-deadlock, P:w1/w2 completes, P:w1/w2 holds [a,b] = PASS                    |
| structure/spawn_join_loop_finite           | correct | PASS        | true     | deadlock = PASS                                                               |
| structure/worker_with_payload              | correct | PASS        | true     | no-deadlock, P:w1/w2 completes = PASS                                         |

P1 阶段必须用裁剪后的二进制重新生成此表并逐字对比（属性 id 用原始字符串），
写入 `benchmarks/BASELINE.json`。

## 附录 B：DSL 示例（ABBA 修正版，对应 lock-order/abba_2lock）

```skel
skeleton abba_2lock;

mutex a;
mutex b;

@R1
fn main() {
    scope { spawn t1(); spawn t2(); }
}

@R2 @R4
fn t1() {
    lock a { lock b { compute "update both records"; } }
}

@R3 @R4
fn t2() {
    lock a { lock b { compute "update both records"; } }
}
```

## 附录 C：DSL 示例（condvar 谓词循环，对应 condvar/bare_wait_no_predicate）

```skel
skeleton bare_wait;

mutex m;
condvar cv for m;
shared ready: Bool = false guarded_by m;

fn main() { scope { spawn waiter(); spawn notifier(); } }

@R4 @R6
fn waiter() {
    lock m {
        while ready == false { cv.wait(); }
    }
}

@R3
fn notifier() {
    lock m {
        ready = true;
        cv.notify_one();
    }
}
```

（附录中的 `@R` 编号仅为示意；gold.skel 必须按各任务 requirements.json 的真实编号标注。）
