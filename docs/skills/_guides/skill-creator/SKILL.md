---
name: skill-creator
description: 创建新技能、修改和改进现有技能，并衡量技能表现。用于用户想从零创建技能、编辑或优化现有技能、运行 evals 测试技能、用方差分析做 benchmark，或优化技能 description 以提升触发准确率的场景。
---

# Skill Creator

这是一个用于创建新技能并持续改进技能的 skill。

从高层看，创建一个 skill 的流程大致如下：

- 明确你希望这个 skill 做什么，以及它大致应该如何完成
- 写出 skill 草稿
- 创建几个测试 prompt，并用能够访问该 skill 的 Claude 来运行它们
- 帮助用户从定性和定量两个角度评估结果
  - 当测试运行在后台进行时，如果还没有定量 eval，就起草一些；如果已有 eval，可以直接使用，也可以按需要修改。然后向用户解释这些 eval 的检查目标；如果 eval 已经存在，就解释现有 eval
  - 使用 `eval-viewer/generate_review.py` 脚本把结果展示给用户，让用户查看输出，也能看到定量指标
- 根据用户对结果的反馈重写 skill；如果定量 benchmark 暴露了明显问题，也要据此修正
- 重复上述过程，直到结果满意
- 扩大测试集，再做更大规模测试

使用这个 skill 时，你的任务是判断用户当前处在这个流程的哪一步，然后直接帮助用户推进。例如，用户可能说“我想做一个 X 的 skill”。这时你可以帮助用户收敛需求、写草稿、写测试用例、明确评估方式、运行所有 prompt，并继续迭代。

另一种情况是，用户已经有了 skill 草稿。这时你可以直接进入 eval 和迭代环节。

当然，你应该保持灵活。如果用户说“我不需要跑一堆评测，只想让我帮忙看看感觉”，那也可以按用户的方式来。

## 与用户沟通

Skill creator 的使用者对编程术语的熟悉程度可能差异很大。有些用户很懂计算机，也有些用户只是因为模型能力变强，才开始接触终端和工具。

所以请根据上下文线索调整你的表达方式。默认情况下，可以参考下面的边界：

- “evaluation”和“benchmark”这类词有一点专业，但通常可以接受
- 对于“JSON”和“assertion”这类词，最好先看到用户确实熟悉技术语境，再不加解释地使用

如果你不确定用户是否理解某个术语，可以简短解释一下。必要时用一句话给术语下定义。

---

## 创建 skill

### 捕捉意图

先理解用户的意图。当前对话里可能已经包含了用户想沉淀成 skill 的工作流，例如用户说“把这个变成一个 skill”。如果是这样，先从对话历史中提取答案：用过哪些工具、步骤顺序是什么、用户做过哪些纠正、观察到哪些输入和输出格式。用户可能还需要补充缺失信息，并且应在进入下一步前确认。

1. 这个 skill 应该让 Claude 能做什么？
2. 这个 skill 应该在什么情况下触发？也就是哪些用户表述或上下文应该触发它？
3. 期望的输出格式是什么？
4. 是否需要设置测试用例来验证 skill 有效？如果输出可以客观验证，例如文件转换、数据抽取、代码生成、固定流程步骤，就适合写测试用例。若输出偏主观，例如写作风格或艺术创作，通常不需要强行测试。你可以根据 skill 类型推荐默认做法，但最终由用户决定。

### 访谈和研究

主动询问边界情况、输入输出格式、示例文件、成功标准和依赖项。在这些问题没有厘清之前，不要急着写测试 prompt。

检查可用的 MCP。如果研究资料、查找类似 skill、查询最佳实践会有帮助，可以并行使用子代理；如果没有子代理，就内联完成。带着上下文回来，减少用户负担。

### 编写 SKILL.md

根据对用户的访谈，填写这些组成部分：

- **name**：skill 标识符
- **description**：什么时候触发、它做什么。这是主要触发机制，必须同时包含 skill 做什么，以及具体哪些场景应该使用它。所有“何时使用”的信息都应该写在这里，而不是写在正文里。注意：目前 Claude 有 undertrigger 的倾向，也就是明明有用却不调用 skill。为了抵消这个问题，description 可以稍微“主动”一点。例如，不要只写“如何构建一个简单快速的 dashboard 来展示 Anthropic 内部数据”，可以写成“如何构建一个简单快速的 dashboard 来展示 Anthropic 内部数据。当用户提到 dashboard、数据可视化、内部指标，或者想展示任何公司数据时，即使没有明确说 dashboard，也一定要使用这个 skill。”
- **compatibility**：所需工具和依赖，可选，通常很少需要
- **skill 的其他正文内容**

### Skill 写作指南

#### Skill 的组成结构

```text
skill-name/
├── SKILL.md（必需）
│   ├── YAML frontmatter（必需，包含 name 和 description）
│   └── Markdown instructions（必需）
└── Bundled Resources（可选）
    ├── scripts/    - 用于确定性或重复性任务的可执行代码
    ├── references/ - 需要时加载到上下文中的文档
    └── assets/     - 输出中会用到的文件，例如模板、图标、字体
```

#### 渐进式披露

Skills 使用三层加载系统：

1. **Metadata**，也就是 name 和 description：始终在上下文中，约 100 词
2. **SKILL.md body**：当 skill 触发时进入上下文，理想情况下少于 500 行
3. **Bundled resources**：按需使用，大小不限，scripts 可以在不加载全文的情况下执行

这些字数只是近似值，如果确实需要，也可以更长。

**关键模式：**

- 保持 SKILL.md 少于 500 行；如果接近这个限制，就增加一层层级，并提供明确指针，说明后续应该读哪里
- 在 SKILL.md 中清楚引用文件，并说明什么时候应该读取它们
- 对于大型 reference 文件，例如超过 300 行的文件，要包含目录

**领域组织方式**：当一个 skill 支持多个领域或框架时，按变体组织：

```text
cloud-deploy/
├── SKILL.md（工作流和选择逻辑）
└── references/
    ├── aws.md
    ├── gcp.md
    └── azure.md
```

Claude 只读取相关的 reference 文件。

#### 不制造意外原则

不必多说，skills 不能包含恶意软件、漏洞利用代码，或任何会危害系统安全的内容。skill 的内容不应该背离用户基于描述所能预期到的意图。不要配合创建误导性 skill，也不要创建用于未授权访问、数据外传或其他恶意行为的 skill。类似“扮演某个角色”这样的 roleplay 通常可以接受。

#### 写作模式

优先使用祈使句来写指令。

**定义输出格式**，可以这样写：

```markdown
## Report structure
ALWAYS use this exact template:
# [Title]
## Executive summary
## Key findings
## Recommendations
```

**示例模式**，加入示例通常很有用。可以这样写：

```markdown
## Commit message format
**Example 1:**
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication
```

### 写作风格

尽量向模型解释为什么某件事重要，而不是堆很多强硬的 MUST。要利用模型的理解能力，让 skill 具有一般性，不要过度绑定少数具体例子。先写草稿，然后用新的眼光重新审视并改进。

### 测试用例

写完 skill 草稿后，构造 2 到 3 个真实的测试 prompt，也就是用户真的可能会说的话。把它们展示给用户，例如：“这里有几个我想试的测试用例。你觉得合适吗？要不要增加更多？”然后运行它们。

把测试用例保存到 `evals/evals.json`。暂时不要写 assertions，只写 prompt。下一步会在运行期间起草 assertions。

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User's task prompt",
      "expected_output": "Description of expected result",
      "files": []
    }
  ]
}
```

完整 schema 见 `references/schemas.md`，其中包括稍后会加入的 `assertions` 字段。

## 运行和评估测试用例

这一节是一个连续流程，不要中途停止。不要使用 `/skill-test` 或任何其他测试 skill。

把结果放到 `<skill-name>-workspace/` 中，它应该是 skill 目录的兄弟目录。在 workspace 内按迭代组织结果，例如 `iteration-1/`、`iteration-2/`；在每个 iteration 内，每个测试用例有自己的目录，例如 `eval-0/`、`eval-1/`。不要一开始就创建所有目录，只在执行到对应步骤时创建。

### Step 1：在同一轮中启动所有运行，包括 with-skill 和 baseline

对每个测试用例，在同一轮里启动两个子代理：一个带 skill，一个不带 skill。这很重要：不要先启动 with-skill，再回来补 baseline。要一次性全部启动，这样它们会在相近时间完成。

**With-skill run：**

```text
Execute this task:
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>/with_skill/outputs/
- Outputs to save: <what the user cares about, e.g., "the .docx file", "the final CSV">
```

**Baseline run**，同一个 prompt，但 baseline 取决于上下文：

- **创建新 skill**：完全不使用 skill。同一个 prompt，不传 skill path，保存到 `without_skill/outputs/`
- **改进已有 skill**：使用旧版本。编辑前先快照 skill，例如 `cp -r <skill-path> <workspace>/skill-snapshot/`，然后让 baseline 子代理指向这个快照。保存到 `old_skill/outputs/`

为每个测试用例写一个 `eval_metadata.json`，assertions 暂时可以为空。给每个 eval 起一个描述性名字，说明它在测试什么，不要只叫 `eval-0`。目录名也使用这个名字。如果本轮使用了新的或修改过的 eval prompt，要为每个新的 eval 目录创建这些文件，不要假设它们会从上一次迭代继承。

```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "assertions": []
}
```

### Step 2：运行过程中起草 assertions

不要只是等待运行完成，要利用这段时间起草每个测试用例的定量 assertions，并向用户解释它们检查什么。如果 `evals/evals.json` 中已经有 assertions，就审查并解释已有 assertions。

好的 assertions 应该客观可验证，并且名称清晰。它们在 benchmark viewer 中应该一眼能看出每项检查的含义。主观类 skill，例如写作风格或设计质量，更适合定性评估，不要强行把需要人工判断的内容变成 assertions。

起草完成后，更新 `eval_metadata.json` 文件和 `evals/evals.json`。同时告诉用户他们将在 viewer 里看到什么，包括定性输出和定量 benchmark。

### Step 3：每个运行完成时捕获 timing 数据

当每个子代理任务完成时，你会收到一条通知，其中包含 `total_tokens` 和 `duration_ms`。立刻把这些数据保存到对应 run 目录的 `timing.json`：

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

这是捕获这些数据的唯一机会。它来自任务通知，不会保存在其他地方。每条通知到达时就处理，不要等到最后批量处理。

### Step 4：打分、聚合并启动 viewer

所有运行完成后：

1. **为每个运行打分**：启动 grader 子代理，或者内联打分。grader 读取 `agents/grader.md`，根据输出评估每条 assertion。把结果保存为每个 run 目录下的 `grading.json`。`grading.json` 的 expectations 数组必须使用 `text`、`passed`、`evidence` 字段，不能使用 `name`、`met`、`details` 或其他变体，因为 viewer 依赖这些精确字段名。对于可以用程序检查的 assertions，写脚本并运行，而不是靠肉眼判断。脚本更快、更可靠，也能在后续迭代中复用。

2. **聚合成 benchmark**：从 skill-creator 目录运行聚合脚本：

   ```bash
   python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
   ```

   这会生成 `benchmark.json` 和 `benchmark.md`，包含每种配置的 pass_rate、time、tokens，并给出 mean ± stddev 和 delta。如果手动生成 `benchmark.json`，请参考 `references/schemas.md` 中 viewer 期望的精确 schema。每个 with_skill 版本应放在对应 baseline 前面。

3. **做 analyst pass**：阅读 benchmark 数据，找出聚合统计可能掩盖的模式。参考 `agents/analyzer.md` 中的 “Analyzing Benchmark Results” 部分，关注那些无论是否使用 skill 都通过的 assertions、方差很高的 eval、以及时间和 token 的权衡。

4. **启动 viewer**，同时展示定性输出和定量数据：

   ```bash
   nohup python <skill-creator-path>/eval-viewer/generate_review.py \
     <workspace>/iteration-N \
     --skill-name "my-skill" \
     --benchmark <workspace>/iteration-N/benchmark.json \
     > /dev/null 2>&1 &
   VIEWER_PID=$!
   ```

   对于第 2 次及之后的迭代，还要传入 `--previous-workspace <workspace>/iteration-<N-1>`。

   **Cowork 或 headless 环境**：如果 `webbrowser.open()` 不可用，或者环境没有显示器，就使用 `--static <output_path>` 生成一个独立 HTML 文件，而不是启动服务器。用户点击 “Submit All Reviews” 后，反馈会下载成 `feedback.json`。下载后，把 `feedback.json` 复制到 workspace 目录中，供下一次迭代读取。

注意：请使用 `generate_review.py` 创建 viewer，不需要自己写自定义 HTML。

5. **告诉用户**，可以类似这样说：“我已经在浏览器中打开结果。里面有两个 tab：Outputs 可以逐个查看测试用例并留下反馈，Benchmark 展示定量对比。你看完后回到这里告诉我。”

### 用户在 viewer 中会看到什么

“Outputs” tab 会一次展示一个测试用例：

- **Prompt**：交给 agent 的任务
- **Output**：skill 生成的文件，能内联渲染的会直接显示
- **Previous Output**，第 2 次及之后迭代：折叠区域，展示上一次迭代的输出
- **Formal Grades**，如果已打分：折叠区域，展示 assertion 的通过和失败情况
- **Feedback**：用户输入反馈的文本框，会自动保存
- **Previous Feedback**，第 2 次及之后迭代：在文本框下方展示上一次反馈

可以通过 prev/next 按钮或方向键导航。完成后，用户点击 “Submit All Reviews”，这会保存 `feedback.json`。

### Step 5：读取反馈

当用户告诉你已经完成 review 后，读取 `feedback.json`：

```json
{
  "reviews": [
    {"run_id": "eval-0-with_skill", "feedback": "the chart is missing axis labels", "timestamp": "..."},
    {"run_id": "eval-1-with_skill", "feedback": "", "timestamp": "..."},
    {"run_id": "eval-2-with_skill", "feedback": "perfect, love this", "timestamp": "..."}
  ],
  "status": "complete"
}
```

空反馈表示用户认为结果可以接受。重点改进用户提出具体问题的测试用例。

完成后关闭 viewer server：

```bash
kill $VIEWER_PID 2>/dev/null
```

---

## 改进 skill

这是整个循环的核心。你已经运行测试用例，用户也 review 了结果，现在需要根据反馈让 skill 变得更好。

### 如何思考改进

1. **从反馈中泛化。** 这里的核心是创建可以反复使用、跨很多 prompt 都有效的 skill。你和用户只是在少数几个例子上快速迭代，因为这样效率高，用户也很容易判断结果。但如果 skill 只适用于这几个例子，它就没有价值。不要加入过度拟合的小修小补，也不要写过分僵硬的 MUST。如果有顽固问题，可以尝试换一种表达方式、工作模式或指导思路，让 skill 学到更可迁移的行为。

2. **保持 prompt 精简。** 删除没有实际作用的内容。要阅读运行 transcript，而不仅是最终输出。如果发现 skill 让模型浪费大量时间做无效工作，就尝试删掉导致这些行为的指令。

3. **解释为什么。** 尽量解释每条指令背后的原因。当前的 LLM 很聪明，具备很强的意图理解能力。好的 skill 不应该只是机械约束，而应该让模型理解任务本质。如果你发现自己在频繁写 ALWAYS 或 NEVER，这通常是警号。能解释原因时，就把它改写成模型能理解的原则。

4. **寻找测试用例之间的重复工作。** 阅读测试运行的 transcript，观察子代理是否都独立写了类似 helper script，或者反复执行同一套多步骤流程。如果 3 个测试用例都让子代理写了 `create_docx.py` 或 `build_chart.py`，这强烈说明 skill 应该把这个脚本打包到 `scripts/` 中。写一次，放进 skill，告诉后续 agent 使用它。这样可以避免每次调用都重新造轮子。

这个任务很重要，思考时间通常不是瓶颈。请花时间认真理解用户真正想要什么，并把这种理解写进 skill 指令中。

### 迭代循环

改进 skill 后：

1. 应用你的改进
2. 把所有测试用例重新运行到新的 `iteration-<N+1>/` 目录中，包括 baseline。创建新 skill 时，baseline 始终是不使用 skill 的 `without_skill`。改进现有 skill 时，可以根据情况选择原始版本或上一轮版本作为 baseline
3. 使用 `--previous-workspace` 指向上一轮 iteration，启动 reviewer
4. 等待用户 review，并告诉你他们完成了
5. 读取新的反馈，再改进，继续重复

持续迭代直到：

- 用户说他们满意
- 反馈全为空，说明结果都可以
- 已经无法取得有意义的进展

---

## 高级：盲比较

当你想更严格地比较两个 skill 版本时，例如用户问“新版本真的更好吗？”，可以使用盲比较系统。详细内容见 `agents/comparator.md` 和 `agents/analyzer.md`。基本思路是：把两个输出交给独立 agent，不告诉它哪个来自哪个版本，让它判断质量。然后分析赢家为什么赢。

这是可选流程，需要子代理，大多数用户不需要。

---

## Description Optimization

`SKILL.md` frontmatter 中的 description 字段是决定 Claude 是否调用 skill 的主要机制。创建或改进 skill 后，可以主动提出为用户优化 description，以提高触发准确率。

### Step 1：生成 trigger eval queries

创建 20 条 eval queries，混合 should-trigger 和 should-not-trigger。保存为 JSON：

```json
[
  {"query": "the user prompt", "should_trigger": true},
  {"query": "another prompt", "should_trigger": false}
]
```

这些 queries 必须真实，像 Claude Code 或 Claude.ai 用户真的会输入的话。不要写抽象请求，而要写具体任务，包含一定细节。例如文件路径、个人工作背景、列名和值、公司名、URL 等。可以有一点上下文故事，也可以包含小写、缩写、拼写错误或口语表达。长度要有变化，并重点覆盖边界场景，而不是只写非常清楚的正反例。

坏例子：`"Format this data"`、`"Extract text from PDF"`、`"Create a chart"`

好例子：`"ok so my boss just sent me this xlsx file (its in my downloads, called something like 'Q4 sales final FINAL v2.xlsx') and she wants me to add a column that shows the profit margin as a percentage. The revenue is in column C and costs are in column D i think"`

对于 **should-trigger** queries，通常 8 到 10 条，要考虑覆盖面。围绕同一意图写出不同说法，有正式的，也有随意的。包括用户没有明确说出 skill 名或文件类型，但明显需要该 skill 的情况。也加入一些少见用法，以及与其他 skill 竞争但这个 skill 应该胜出的情况。

对于 **should-not-trigger** queries，通常 8 到 10 条，最有价值的是 near-miss，也就是和 skill 共享关键词或概念，但实际上需要别的能力的请求。考虑相邻领域、容易被关键词误触发的模糊表达，以及触及 skill 能力但更适合其他工具的场景。

重点避免：不要让 should-not-trigger 过于无关。比如 PDF skill 的负例写 “Write a fibonacci function” 太简单，无法测试什么。负例应该真的有迷惑性。

### Step 2：让用户 review

使用 HTML 模板向用户展示 eval set：

1. 读取 `assets/eval_review.html` 模板
2. 替换占位符：
   - `__EVAL_DATA_PLACEHOLDER__` 替换为 JSON 数组，注意不是字符串，不能额外加引号
   - `__SKILL_NAME_PLACEHOLDER__` 替换为 skill 名
   - `__SKILL_DESCRIPTION_PLACEHOLDER__` 替换为当前 skill description
3. 写入临时文件，例如 `/tmp/eval_review_<skill-name>.html`，并打开：`open /tmp/eval_review_<skill-name>.html`
4. 用户可以编辑 queries、切换 should-trigger、增删条目，然后点击 “Export Eval Set”
5. 文件会下载到 `~/Downloads/eval_set.json`。如果有多个版本，例如 `eval_set (1).json`，检查 Downloads 文件夹中最新的那个

这一步很重要。糟糕的 eval queries 会导致糟糕的 description。

### Step 3：运行优化循环

告诉用户：“这会花一些时间，我会在后台运行优化循环，并定期检查进度。”

把 eval set 保存到 workspace，然后在后台运行：

```bash
python -m scripts.run_loop \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --model <model-id-powering-this-session> \
  --max-iterations 5 \
  --verbose
```

使用系统 prompt 中当前会话所用的 model ID，这样触发测试才和用户实际体验一致。

运行期间，定期 tail 输出，告诉用户当前到第几轮，以及分数大致如何。

这个脚本会自动处理完整优化循环。它会把 eval set 分成 60% train 和 40% held-out test，评估当前 description，每条 query 运行 3 次以得到更可靠的触发率，然后调用 Claude 根据失败项提出改进。它会在 train 和 test 上重新评估每个新 description，最多迭代 5 次。完成后，它会在浏览器中打开 HTML 报告，展示每轮结果，并返回包含 `best_description` 的 JSON。最佳 description 根据 test score 选择，而不是 train score，以避免过拟合。

### Skill 触发机制

理解触发机制有助于设计更好的 eval queries。Skills 会以 name 和 description 的形式出现在 Claude 的 `available_skills` 列表中，Claude 会根据 description 判断是否要读取某个 skill。关键点是：Claude 通常只会在任务自己不容易直接完成时读取 skill。像“read this PDF”这种简单一步任务，即使 description 匹配得很好，也可能不会触发 skill，因为 Claude 可以直接用基础工具完成。复杂、多步骤或专业化请求，在 description 匹配时更容易稳定触发 skill。

因此，eval queries 应该足够实质化，让 Claude 确实会从 skill 中受益。像“read file X”这样的简单 query 是很差的测试，因为无论 description 写得多好，它都可能不触发 skill。

### Step 4：应用结果

从 JSON 输出中取出 `best_description`，更新 skill 的 `SKILL.md` frontmatter。向用户展示修改前后，并报告分数。

---

### Package and Present，仅当 `present_files` 工具可用

检查是否可以使用 `present_files` 工具。如果不可用，跳过此步。如果可用，就打包 skill 并把 `.skill` 文件提供给用户：

```bash
python -m scripts.package_skill <path/to/skill-folder>
```

打包后，把生成的 `.skill` 文件路径告诉用户，方便安装。

---

## Claude.ai 专用说明

在 Claude.ai 中，核心流程仍然是草稿、测试、review、改进、重复，但因为 Claude.ai 没有子代理，一些机制需要调整。

**运行测试用例**：没有子代理意味着无法并行执行。对每个测试用例，先读取 skill 的 `SKILL.md`，然后亲自按照它的指令完成测试 prompt。一次做一个。这不如独立子代理严谨，因为你写了 skill，又自己运行它，拥有完整上下文，但它仍然是有用的 sanity check。人工 review 会补偿这一点。跳过 baseline runs，只使用 skill 完成任务。

**Review 结果**：如果无法打开浏览器，例如 Claude.ai 的 VM 没有显示器，或者你在远程服务器上，就跳过 browser reviewer，直接在对话中展示结果。对每个测试用例，展示 prompt 和 output。如果 output 是用户需要查看的文件，例如 `.docx` 或 `.xlsx`，就保存到文件系统，并告诉用户路径，让他们下载和检查。然后内联询问反馈：“这个结果怎么样？有什么要改的吗？”

**Benchmarking**：跳过定量 benchmark，因为没有子代理时 baseline 比较意义不大。重点放在定性反馈。

**迭代循环**：和前面相同，改进 skill，重新运行测试用例，询问反馈，只是中间没有 browser reviewer。你仍然可以在文件系统中按 iteration 目录组织结果。

**Description optimization**：这一节需要 `claude` CLI，尤其是 `claude -p`，只在 Claude Code 中可用。Claude.ai 中跳过。

**Blind comparison**：需要子代理，跳过。

**Packaging**：`package_skill.py` 脚本在任何有 Python 和文件系统的地方都能运行。Claude.ai 中也可以运行它，用户可以下载生成的 `.skill` 文件。

**更新已有 skill**：用户可能是想更新已有 skill，而不是创建新的 skill。这种情况下：

- **保留原始 name。** 记下 skill 的目录名和 `name` frontmatter 字段，保持不变。例如，如果已安装 skill 是 `research-helper`，输出应该是 `research-helper.skill`，而不是 `research-helper-v2`
- **编辑前复制到可写位置。** 已安装 skill 路径可能是只读的。先复制到 `/tmp/skill-name/`，在那里编辑，再从副本打包
- **如果手动打包，先在 `/tmp/` 中 staging**，然后复制到输出目录。直接写入可能因为权限失败

---

## Cowork 专用说明

如果你在 Cowork 中，主要要知道：

- 你有子代理，所以主流程，包括并行启动测试用例、运行 baseline、打分等，都是可用的。如果严重超时，也可以串行运行测试 prompt
- 你没有浏览器或显示器，所以生成 eval viewer 时，使用 `--static <output_path>` 写出独立 HTML 文件，而不是启动服务器。然后提供一个用户可以点击打开的 HTML 链接
- 由于 Cowork 设置的原因，模型似乎不太倾向于在测试完成后主动生成 eval viewer。这里再次强调：无论是在 Cowork 还是 Claude Code 中，运行测试后都应该先生成 eval viewer，让人类查看例子，然后再由你自己评估输入并修改 skill。使用 `generate_review.py`，不要自己写定制 HTML。也就是说，在评估前先把结果展示给人类
- 反馈机制不同：因为没有运行中的 server，viewer 的 “Submit All Reviews” 按钮会下载 `feedback.json`。之后你可以从下载位置读取它，可能需要先请求访问
- Packaging 可用，`package_skill.py` 只需要 Python 和文件系统
- Description optimization，也就是 `run_loop.py` 和 `run_eval.py`，在 Cowork 中应该可以工作，因为它通过 subprocess 使用 `claude -p`，不依赖浏览器。但请等 skill 完全完成，并且用户同意它已经足够好之后再做
- **更新已有 skill**：用户可能想更新已有 skill。遵循 Claude.ai 部分中的更新指导

---

## Reference files

`agents/` 目录包含专用子代理的说明。需要启动对应子代理时再读取。

- `agents/grader.md`：如何根据输出评估 assertions
- `agents/comparator.md`：如何在两个输出之间做盲 A/B 比较
- `agents/analyzer.md`：如何分析一个版本为什么胜出

`references/` 目录包含额外文档：

- `references/schemas.md`：`evals.json`、`grading.json` 等 JSON 结构

---

最后再重复一次核心循环：

- 明确 skill 是关于什么的
- 起草或编辑 skill
- 在测试 prompt 上运行能够访问该 skill 的 Claude
- 和用户一起评估输出：
  - 创建 `benchmark.json`，运行 `eval-viewer/generate_review.py`，帮助用户 review 测试用例
  - 运行定量 evals
- 重复，直到你和用户都满意
- 打包最终 skill 并返回给用户

如果你有 TodoList，请把步骤加入其中，确保不会忘记。如果你在 Cowork 中，请特别把“创建 evals JSON 并运行 `eval-viewer/generate_review.py`，让人类 review 测试用例”加入 TodoList。

祝顺利。
