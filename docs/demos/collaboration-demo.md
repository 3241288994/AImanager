# 多 CLI 与 API 协作：真实调用演示

日期：2026-10-21（Asia/Shanghai）。

这是一个含预置缺陷的隔离示例，所有模型调用、文件操作和测试均真实执行。图中六块内容来自实际调用的原始输出，按段摘取并渲染截图后拼接；保留原话，省略处以 … 标记，黄色下划线为后加标注。

![多 CLI 与 API 模型原始输出节选截图拼接](../assets/aimanager-collaboration-demo.png)

[查看高清原图（3360 × 3366，无损 PNG）](../assets/aimanager-collaboration-demo.png?raw=true)

## 任务与结果

将缺失的 usage_level 当作 0，会把未知额度显示成 100%。Codex CLI 复现失败，Claude Code 独立审阅输入边界；Gemini API 获得两份意见和示例代码，提出精确类型检查与小数测试建议。Claude 在原会话中采纳并补充有限性检查，随后在新的授权任务中修改代码；Codex 续接原会话复测，主控再次核验。

修复前：3 项测试，2 通过、1 失败。修复后：保留原 3 项并新增 7 项，10 项全部通过。测试数量按 unittest 报告统计，不将 subTest 另计。

## 可复现文件

- [输入合同](quota-example/README.md)
- [修改前的代码](quota-example/quota.before.py)
- [修改后的代码](quota-example/quota.py)
- [测试](quota-example/test_quota.py)
- [结构化调用结果](collaboration-demo-records.json)
- [图片排版源文件](../assets/aimanager-collaboration-demo.html)
- [六段输出的文字渲染源文件](../assets/collaboration-outputs/source.html)

原始分图：[01 · Codex 复现](../assets/collaboration-outputs/01.png) · [02 · Claude 审阅](../assets/collaboration-outputs/02.png) ·
[03 · Gemini 参考双方意见](../assets/collaboration-outputs/03.png) · [04 · Claude 采纳与修正](../assets/collaboration-outputs/04.png) ·
[05 · Claude 修改](../assets/collaboration-outputs/05.png) · [06 · Codex 复测](../assets/collaboration-outputs/06.png)。

在 quota-example 目录运行 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v`。

## 调用身份与材料范围

- Claude Code 报告模型为 `claude-opus-5-5`，依据为 CLI metadata。
- Codex CLI 请求 `gpt-6-astra`，事件流没有独立模型字段，记录为 `explicit_request_only`。
- Gemini 渠道请求/报告 `gemini-argon`（个人别名 `gemini4`），metadata 来自反代，不构成对上游模型身份的独立鉴定。
- API 仅接收选定的示例代码与审阅文本，没有工作区访问权限。
- `reply` 用于原会话续接；Claude 的只读会话没有被升级权限，执行使用新的显式授权任务。
- 以下保留完整输出；图中采用原文摘录，步骤标题为后加说明。账号标识、凭据和私人主机路径未纳入公开记录。

## 原始结果文本

### 1. Codex CLI：读取与复现

任务：`3c3783acf79044f480744f5f9666284a`；访问：`read`。

```text
我会读取三个文件，并用不写入缓存的命令运行现有测试；不修改文件，也不调用其他模型。


1. 发现：已读取三个文件。quota.py:2 将 None 当作 0，返回 100，违反 README.md:8；test_quota.py:14 失败。
2. 最小修复：计算前校验类型、有限性及 [0,1] 范围；无效返回 None，保留合法零值。
3. 易漏边界：bool 属于 int 子类，须单独排除。
4. 实执行：`cat README.md quota.py test_quota.py` 成功；`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v`：3项，2通过、1失败，退出码1。未编辑。
```

### 2. Claude Code：独立静态审阅

任务：`35459dfbcc954dec9b9feed54fc86068`；访问：`read`。

```text
**仅做了静态审阅，没有运行测试**（我只能用 Read/Glob/Grep）。我读了 README.md、quota.py 和 test_quota.py，没有修改任何文件。

**1 发现**
- `quota.py:2` 用 `usage_level or 0` 把 None 当成 0，结果是 100.0。按代码推断 `test_quota.py:13` 会失败，但我没有实际运行验证。
- `False` 和 `""` 会返回 100.0，`True` 返回 0.0。`"0.5"` 会抛 TypeError，而 README 要求返回 None。
- NaN 和 inf 没有拦截。1.5 返回 -50.0，-0.2 返回 120.0，都没有做越界检查。

**2 建议的处理规则**
先排除 bool，再只接受 int 和 float，然后要求 `math.isfinite(x)` 且 `0<=x<=1`。不满足就返回 None；满足时返回 `round((1-x)*100,1)`。

**3 需补充的测试**
用 subTest 断言以下输入都返回 None：True、False、"0.5"、""、nan、inf、-0.01、1.01。另外断言 0.5 返回 50.0。

**验证方法**
由有执行权限的一方运行 `python3 -m unittest -v`。

**待讨论**
Decimal、Fraction 这类数值类型是否接受，README 没有写明。
```

### 3. Gemini API：参考两份结果

任务：`d544234db5254b1abc329677d5fa8a73`；访问：`text`。

```text
Codex CLI与Claude Code均指出`usage_level or 0`混淆了缺失值与零值。Codex指出`bool`是`int`子类须单独排除；Claude指出数值字符串`"0.5"`会抛`TypeError`而非返回`None`，且未拦截`NaN`/`inf`及越界值。

未知值（如`None`）必须保留为`None`，否则默认转`0`会误报100%满额，掩盖数据缺失并引发透支；合法零值（`0`或`0.0`）代表已明确测得零消耗，必须区别处理以正确返回`100.0`。

**改进建议**：因输入源自JSON，无需考虑`Decimal`，用`type(x) in (int, float)`即可仅接受内置数值并排除`bool`与字符串。建议补充边界值`0`、`1`及两位小数舍入（如`0.333`→`66.7`）的测试。
```

### 4. Claude Code：续接讨论

任务：`8107b0c25fca444784bec3ae1b426528`；访问：`read`。

```text
**采纳：**
- Codex 的运行结果：3 项测试中 1 项失败，确认 None 被显示为 100%。
- Gemini 建议的 `type(x) in (int, float)`：在只接受 JSON 解码得到的 int/float 这个前提下，它能直接排除 bool、字符串和 Decimal。

**修正：**
- 0.333 有三位小数，Gemini 写成了"两位"。这个用例可以保留，但它离舍入边界很远，测不出舍入问题。
- 光靠类型检查不够：Python 的 `json.loads` 默认会把 `NaN`、`Infinity` 解析成 float，所以仍要检查有限性和范围。

**最终方案：** 只有满足 `type(x) in (int, float)`、`math.isfinite(x)` 和 `0<=x<=1` 时，才返回 `round((1-x)*100,1)`，否则返回 None。

**测试范围：**
- 返回 None：None、True、False、"0.5"、""、nan、inf、-inf、-0.01、1.01
- 返回数值：0 和 0.0 返回 100.0，1 返回 0.0，0.5 返回 50.0，0.333 返回 66.7

0.333 的结果是我静态推算的，本次没有运行任何测试。
```

### 5. Claude Code：授权修改与执行

任务：`c829a40e4ffc4a7582faae2590e08502`；访问：`exec`。

```text
`remaining_percent` is fixed and all 10 tests pass (`Ran 10 tests … OK`, exit=0). Before the fix, the original 3 tests ran with 1 failure (`test_missing_is_unknown`: `100 is not None`), which matches what Codex reported.

**Opinions adopted**
- **Codex:** the failing-test reproduction. I re-ran it myself and got the same result.
- **Gemini:** the strict `type(x)` check. It rejects bool, str and Decimal. I kept its 0.333 → 66.7 case, which now passes when run (it was only calculated by hand before).
- **Claude (previous round):** the extra finiteness check and the 0 ≤ x ≤ 1 range check.
- **Coordinator's addition:** for huge positive or negative ints, ints skip `math.isfinite` and go straight to the range check. I confirmed that `math.isfinite(10**400)` raises `OverflowError` in this environment, so skipping it is needed.

**One change beyond the agreed plan:** the new return-type test showed that int inputs returned the int `100` / `0`. I changed `*100` to `*100.0` so the result is always a float, which matches the README's "rounded to one decimal". The original `assertEqual(…, 100.0)` passed either way. If the coordinator doesn't want this change, revert that line and delete `test_returns_float`.

**Files changed** (only these two)
- `quota.py`: the fix.
- `test_quota.py`: the original 3 tests are kept as they were, plus 7 new ones:
  - **Valid decimals:** 0.0, 1.0, 0.5, 0.333, 0.25
  - **Return type:** float for 0, 1, 0.5
  - **Types that return None:** True, False, `"0.5"`, `""`, Decimal, list, dict
  - **Non-finite values:** nan, inf, -inf
  - **JSON input:** NaN, Infinity, -Infinity passed through `json.loads`
  - **Out of range:** -0.01, 1.01, -1, 2
  - **Huge ints:** ±10**400

**Commands run** (Python 3.8.10, in the workspace directory)
1. `python3 -m unittest -v` (before fix): 3 tests, 1 failure
2. `python3 -m unittest -v` (after the first edit): 10 tests, 2 failures, both in `test_returns_float` for 0 and 1
3. `python3 -c "import math; math.isfinite(10**400)"`: `OverflowError`
4. After the float change, `python3 -m unittest -v`: 10 tests, OK

Counting each subTest separately there are about 30 checks, but unittest reports 10 tests.

**Notes**
- `git status` lists `.bashrc`, `.mcp.json` and similar dotfiles. They are `/dev/null` character devices that the sandbox mounts into the workspace, not files I created. I didn't touch them; check whether they still appear outside the sandbox.
- `__pycache__/` was there before and the test runs updated it.
- Nothing was committed and no network access was used.

**中文交付摘要（≤120字）：**
已修复remaining_percent：仅接受int/float，排除bool和字符串，校验有限性和0–1范围，超大整数返回None且不溢出，结果统一为float。保留原3项测试，新增7项，实测10项全部通过。
```

### 6. Codex CLI：续接并独立复测

任务：`3b0ed6c14dc3423cb01de34f2c67f255`；访问：`read`。

```text
我会读取当前实现和测试，实际运行指定命令，核对边界处理与原有测试是否保留。


已读取当前 README.md、quota.py、test_quota.py。原3项测试保留；None→None、0→100.0、0.333→66.7；布尔、非有限、越界及正负超大整数均返回None，无溢出。

实执行 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v`：10项全部通过，退出码0。按当前精确int/float输入约定，未发现剩余实质问题。未编辑、未调用其他模型。
```

## 主控复跑结果

```text
test_huge_ints_are_unknown_without_overflow (test_quota.QuotaTests) ... ok
test_json_nonfinite_is_unknown (test_quota.QuotaTests) ... ok
test_missing_is_unknown (test_quota.QuotaTests) ... ok
test_non_numeric_types_are_unknown (test_quota.QuotaTests) ... ok
test_nonfinite_is_unknown (test_quota.QuotaTests) ... ok
test_out_of_range_is_unknown (test_quota.QuotaTests) ... ok
test_returns_float (test_quota.QuotaTests) ... ok
test_used_is_empty (test_quota.QuotaTests) ... ok
test_valid_floats (test_quota.QuotaTests) ... ok
test_zero_is_full (test_quota.QuotaTests) ... ok

----------------------------------------------------------------------
Ran 10 tests in 0.001s

OK
```
