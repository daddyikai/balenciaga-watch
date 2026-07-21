# Balenciaga Bag Watch(雲端排程版)

即使電腦關機、沒開網路,也會每 30 分鐘自動檢查一次 2ndstreet.com.tw 是否有新上架、NT$20,000 以下的 BALENCIAGA 包,有新品時透過 GitHub 寄 email 通知你。

## 運作原理

- 排程執行在 GitHub 的伺服器上(GitHub Actions),跟你自己的電腦完全無關。
- 每次執行用無頭瀏覽器(Playwright)打開該分類頁,抓取商品清單,篩選符合條件的包(邏輯與你原本 Cowork 排程一致:品牌需為 BALENCIAGA、分類含「包」但排除「錢包」「夾」、價格 ≤ NT$20,000、排除已售完)。
- 找到「新」品項(之前沒看過的商品 ID)時,會在這個 repo 建立一個 GitHub Issue。只要你有「訂閱」這個 repo,GitHub 就會自動寄 email 通知你,不需要額外設定信箱或密碼。
- 檢查過的商品 ID 記錄在 `state.json`,每次執行後自動更新並存回 repo。

## 設定步驟

### 1. 申請 GitHub 帳號(免費)

前往 https://github.com/signup 註冊。

### 2. 建立新 repo

登入後點右上角「+」→「New repository」,名稱自訂(例如 `balenciaga-watch`),Public 或 Private 皆可,建立時不用勾選任何範本檔案。

### 3. 上傳這個資料夾裡的檔案

在你新建的 repo 頁面,把以下檔案結構上傳進去(用「Add file → Upload files」,可以整批拖曳上傳,GitHub 會自動保留資料夾結構):

```
.github/workflows/balenciaga-watch.yml
scripts/check_balenciaga.py
scripts/parse.py
requirements.txt
state.json
```

（`__pycache__/` 或 `state_test.json` 這類測試殘留檔不用上傳。）

### 4. 確認 Actions 權限

Repo 頁面 → Settings → Actions → General → 拉到最下面「Workflow permissions」,選擇「Read and write permissions」,存檔。(這樣排程才能把更新後的 state.json 寫回 repo。)

### 5. 開啟通知(重要)

Repo 頁面右上角「Watch」按鈕 → 選「All Activity」(或至少要能收到 Issues 通知的選項)。這樣有新 Issue(=有新包上架)時,你綁定的 email 就會收到通知。

### 6. 手動測試一次

Repo 頁面 → Actions 分頁 → 左側選「Balenciaga Bag Watch」→ 右邊「Run workflow」按鈕,手動觸發一次,確認會不會報錯。跑完可以點進去看 log。

之後它會照 `.github/workflows/balenciaga-watch.yml` 裡設定的時間(預設每 30 分鐘一次,UTC 時間 `0,30 * * * *`)自動執行,完全不需要你的電腦開機或連網。

## 調整檢查頻率

打開 `.github/workflows/balenciaga-watch.yml`,修改這行的 cron 設定:

```yaml
- cron: "0,30 * * * *"
```

例如改成每小時一次:`"0 * * * *"`。GitHub Actions 的免費額度對這種輕量排程綽綽有餘。

## 調整價格門檻 / 篩選邏輯

價格上限在 `scripts/check_balenciaga.py` 裡的 `PRICE_LIMIT = 20000`,分類/品牌篩選邏輯在 `scripts/parse.py` 的 `is_matching_bag()`。
