# 問題修復說明

## 修復的問題

### 問題 1: 模型輸出異常 (已修復 ✅)

**症狀：**
```
💭 Thinking (streaming)...
0thought
After clicking "全部一鍵執行", a confirmation dialog for "購買瑪aily tasks is to purchase mana.
1.  **: xe.
Screenion wills
```

**原因：**
在 streaming 模式下，原始代碼對每個 chunk 的每個 part 都進行顯示和收集，導致：
1. 重複顯示部分文字
2. 將不同類型的 part（thought、text、function_call）混在一起
3. 每個 part 被多次添加到 `all_parts` 列表中

**解決方案：**
1. **改進文字顯示邏輯**：
   - 使用 `displayed_text_length` 追蹤已顯示的文字長度
   - 只顯示新增的文字部分（增量顯示）
   - 區分 `thought` 類型和普通 `text` 類型的 part

2. **修復 parts 收集**：
   - 不在 streaming 過程中收集所有 parts（會有重複）
   - 只在 streaming 完成後，從最後一個 chunk 獲取完整的 `final_parts`
   - 使用 `final_parts` 來檢查 function calls

**修改的代碼片段：**
```python
# Before (有問題):
all_parts = []
current_text = ""
for chunk in stream:
    for part in candidate.content.parts:
        if hasattr(part, 'text') and part.text:
            new_text = part.text[len(current_text):]
            if new_text:
                print(new_text, end="", flush=True)
                current_text = part.text
        all_parts.append(part)  # 每個 chunk 都會添加，導致重複

# After (已修復):
displayed_text_length = 0
for chunk in stream:
    for part in candidate.content.parts:
        if hasattr(part, 'text') and part.text:
            if len(part.text) > displayed_text_length:
                new_text = part.text[displayed_text_length:]
                print(new_text, end="", flush=True)
                displayed_text_length = len(part.text)

# 從最後一個 chunk 獲取完整 parts
final_parts = []
if chunk.candidates and len(chunk.candidates) > 0:
    final_candidate = chunk.candidates[0]
    if final_candidate.content and final_candidate.content.parts:
        final_parts = list(final_candidate.content.parts)
```

---

### 問題 2: 跳過功能效果不明顯 (已改進 ✅)

**症狀：**
```
⏭️  Skip signal received - moving to next turn...
s
⏭️  Skip signal received - moving to next turn...
```
- 看不到 AI 重新思考的過程
- 不清楚跳過是否真的生效

**原因：**
1. 跳過訊息不夠明顯
2. 給 AI 的提示詞太簡短，AI 可能沒有真正重新評估
3. 由於問題 1 的 bug，`function_calls` 檢測失敗，可能導致流程異常

**解決方案：**
1. **增強視覺反饋**：
   ```python
   print("\n" + "="*60)
   print("⏭️  USER INTERRUPTION - Skipping planned actions")
   print("🔄 Forcing AI to re-evaluate the situation...")
   print("="*60 + "\n")
   ```

2. **改進提示詞**：
   ```python
   Part(text="[IMPORTANT] User has interrupted the planned actions. "
             "The situation may have changed or your plan may not be optimal. "
             "Please carefully observe the current screen state and reconsider your approach. "
             "What do you see now? What should be the next best action?")
   ```

3. **增加等待時間**：從 0.3 秒增加到 0.5 秒，確保截圖穩定

---

## 修改摘要

### 文件：`agent.py`

#### 修改 1: `process_step_streaming()` 方法
- ✅ 修復 streaming 文字顯示邏輯
- ✅ 修復 parts 收集邏輯（使用 final_parts）
- ✅ 改進跳過功能的視覺反饋和提示詞

#### 修改 2: `process_step()` 方法
- ✅ 改進跳過功能的視覺反饋和提示詞（與 streaming 版本一致）

---

## 測試建議

### 測試 1: 驗證正常輸出
```bash
python agent.py --streaming --instruction "測試指令"
```
**預期結果：**
- 不再出現 "0thought" 或亂碼
- Thinking 過程流暢顯示
- Function calls 正確執行

### 測試 2: 驗證跳過功能
```bash
python agent.py --streaming --instruction "複雜任務"
# 在 AI 思考完、準備執行動作時按 's' + Enter
```
**預期結果：**
```
--- Turn 2 ---
💭 Thinking (streaming)...
[AI的思考過程...]

🎯 Executing 3 action(s)...
[此時按 's' + Enter]

============================================================
⏭️  USER INTERRUPTION - Skipping planned actions
🔄 Forcing AI to re-evaluate the situation...
============================================================

--- Turn 3 ---
💭 Thinking (streaming)...
[AI 重新思考...]
```

---

## 技術細節

### Streaming API 的 Part 結構
Gemini API 在 streaming 時，每個 chunk 可能包含：
- `thought` 類型的 part（思考模式）
- `text` 類型的 part（回應文字）
- `function_call` 類型的 part（工具調用）
- `executable_code` 類型的 part（可執行代碼）

每個 chunk 的 part 是**累積的**，不是增量的。例如：
- Chunk 1: Part(text="Hello")
- Chunk 2: Part(text="Hello world")  ← 完整文字，不是 " world"
- Chunk 3: Part(text="Hello world!") ← 完整文字，不是 "!"

因此我們需要：
1. 追蹤已顯示的長度 (`displayed_text_length`)
2. 只顯示新增的部分 (`part.text[displayed_text_length:]`)
3. 只在最後使用完整的 parts

---

## 已知限制

1. **鍵盤監聽**：需要按 Enter 才能觸發（不是立即響應）
2. **時機控制**：只在「AI 已思考完，準備執行動作」時才能跳過
3. **平台差異**：Windows 和 Unix/Mac 使用不同的輸入檢測機制

如需進一步改進，可以考慮：
- 使用專門的鍵盤庫（如 `pynput`）實現無需 Enter 的即時響應
- 在 streaming 過程中也允許中斷（需要更複雜的流控制）
