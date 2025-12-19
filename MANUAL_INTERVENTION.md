# 手動干預功能說明

## 功能概述

在 AI 執行任務時，您可以：
1. **簡單跳過** - 中斷當前思考/動作，讓 AI 重新評估
2. **帶提示跳過** - 給 AI 一個指示訊息，引導它調整方向

## 使用方法

### 啟動時會顯示：
```
💡 Tips:
   - Press Enter alone: Skip to next turn
   - Type a message + Enter: Send hint to AI and skip
   - Type 'q' + Enter: Quit when in instruction prompt
```

### 操作方式

| 輸入 | 效果 |
|------|------|
| **直接按 Enter** | 簡單跳過，AI 會重新觀察螢幕並思考 |
| **輸入 `s` + Enter** | 同上，簡單跳過 |
| **輸入訊息 + Enter** | 帶提示跳過，訊息會傳給 AI |

### 範例場景

#### 場景 1: AI 進錯活動
```
AI: 💭 我正在分析這個活動畫面...

User: 你進錯活動了，要進 Summer 開頭的

💬 User hint received: 你進錯活動了，要進 Summer 開頭的
⏭️  Skip signal - moving to next turn...

AI: 💭 [收到用戶提示] 我進錯活動了，讓我重新觀察...
```

#### 場景 2: AI 卡在迴圈
```
AI: 🎯 Executing scroll up...
[重複滾動多次]

User: 已經滾到頂了，換個方向

💬 User hint received: 已經滾到頂了，換個方向
⏭️  Skip signal - moving to next turn...

AI: 💭 [收到用戶提示] 讓我改用向下滾動...
```

#### 場景 3: AI 漏看元素
```
AI: 💭 我找不到「兌換」按鈕...

User: 兌換按鈕在畫面右下角

💬 User hint received: 兌換按鈕在畫面右下角
⏭️  Skip signal - moving to next turn...

AI: 💭 [收到用戶提示] 讓我看看右下角...
```

## 技術細節

### 中斷時機

1. **思考期間（Streaming）**
   - 可以在 AI 思考/生成內容時中斷
   - 包括超時自動中斷（20秒）

2. **動作執行前**
   - AI 已決定要執行動作，但還沒開始執行
   - 這是最佳的中斷時機

### 訊息傳遞

當您輸入提示訊息時，AI 會收到：
```
[USER INTERRUPTION] User says: {您的訊息}
Please re-observe the screen and adjust your approach accordingly.
```

加上最新的螢幕截圖。

### 其他功能

| 功能 | 設定 |
|------|------|
| 思考超時 | 20 秒自動跳過 |
| 動作後延遲 | 1 秒後才截圖 |
| 思考深度 | Medium (8192 tokens) |

## 注意事項

1. **需要按 Enter** - 輸入後必須按 Enter 才會送出
2. **中斷不會回滾** - 已執行的動作不會被撤銷
3. **提示要簡潔** - 給 AI 的提示應該簡短明確
